"""Viewport progress overlay for long MetaMorphosis operations.

Blender operators run on the main thread, so this overlay redraws at importer
milestones rather than moving DNA work onto an unsafe background thread.
"""

import math
import os
import time

import bpy
import blf
import gpu
from gpu_extras.batch import batch_for_shader


_handler = None
_started = 0.0
_last_draw = 0.0
_percent = 0
_stage = "Preparing"
_shader = None
_font_id = None


def _get_shader():
    global _shader
    if _shader is None:
        _shader = gpu.shader.from_builtin("SMOOTH_COLOR")
    return _shader


def _draw_vertices(vertices):
    shader = _get_shader()
    batch_for_shader(shader, "TRIS", {"pos": [v[:2] for v in vertices], "color": [v[2:] for v in vertices]}).draw(shader)


def _rect(x1, y1, x2, y2, color):
    r, g, b, a = color
    vertex = lambda x, y: (x, y, r, g, b, a)
    _draw_vertices((vertex(x1, y1), vertex(x2, y1), vertex(x2, y2), vertex(x1, y1), vertex(x2, y2), vertex(x1, y2)))


def _wave(card_x, card_y, card_w, phase, lane):
    colors = ((0.08, 0.78, 0.98), (0.36, 0.40, 1.0), (0.89, 0.30, 0.78), (0.12, 0.88, 0.78))
    count = 42
    center = card_y + 155 + lane * 9
    amplitude = 7 + lane * 1.5
    thickness = 2.0 + lane * 0.8
    vertices = []
    for i in range(count):
        x1 = card_x + 30 + (card_w - 60) * i / count
        x2 = card_x + 30 + (card_w - 60) * (i + 1) / count
        t1, t2 = i / count, (i + 1) / count
        y1 = center + math.sin(t1 * 9.0 + phase + lane) * amplitude
        y2 = center + math.sin(t2 * 9.0 + phase + lane) * amplitude
        c1, c2 = colors[(i + lane) % len(colors)], colors[(i + lane + 1) % len(colors)]
        alpha = 0.18 if lane == 0 else 0.10
        a = (x1, y1 - thickness, *c1, alpha)
        b = (x2, y2 - thickness, *c2, alpha)
        c = (x2, y2 + thickness, *c2, alpha)
        d = (x1, y1 + thickness, *c1, alpha)
        vertices.extend((a, b, c, a, c, d))
    _draw_vertices(vertices)


def _text(text, x, y, size, color, center=False):
    global _font_id
    if _font_id is None:
        # Prefer a light display face when the host provides one; fall back to
        # Blender's bundled font so the add-on has no external font dependency.
        candidates = (
            r"C:\Windows\Fonts\segoeuil.ttf",
            "/System/Library/Fonts/Supplemental/Helvetica Neue.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-ExtraLight.ttf",
        )
        for path in candidates:
            if os.path.isfile(path):
                try:
                    _font_id = blf.load(path)
                    break
                except (RuntimeError, OSError):
                    pass
        if _font_id is None:
            _font_id = 0
    font = _font_id
    blf.size(font, size)
    blf.color(font, *color)
    width, _height = blf.dimensions(font, text)
    blf.position(font, x - width / 2 if center else x, y, 0)
    blf.draw(font, text)


def _draw():
    context = bpy.context
    region = context.region
    if region is None or region.type != "WINDOW":
        return
    width, height = region.width, region.height
    if width < 1 or height < 1:
        return

    gpu.state.blend_set("ALPHA")
    _rect(0, 0, width, height, (0.008, 0.014, 0.03, 0.42))
    card_w, card_h = min(650, width - 36), 270
    card_x, card_y = (width - card_w) / 2, (height - card_h) / 2
    _rect(card_x, card_y, card_x + card_w, card_y + card_h, (0.025, 0.035, 0.065, 0.96))

    elapsed = time.perf_counter() - _started
    _wave(card_x, card_y, card_w, elapsed * 1.5, 0)
    _wave(card_x, card_y, card_w, elapsed * 1.5, 1)
    _wave(card_x, card_y, card_w, elapsed * 1.5, 2)

    center_x = width / 2
    _text("METAMORPHOSIS", center_x, card_y + 208, 17, (0.82, 0.9, 1.0, 1.0), center=True)
    _text("DNA IMPORT", center_x, card_y + 184, 10, (0.38, 0.72, 0.9, 0.95), center=True)
    _text(_stage, center_x, card_y + 91, 13, (0.91, 0.94, 1.0, 1.0), center=True)
    _text(f"{_percent:02d}%", center_x, card_y + 55, 24, (0.97, 0.98, 1.0, 1.0), center=True)

    bar_w, bar_h = min(480, card_w - 72), 5
    bar_x, bar_y = center_x - bar_w / 2, card_y + 35
    _rect(bar_x, bar_y, bar_x + bar_w, bar_y + bar_h, (0.16, 0.20, 0.28, 0.95))
    if _percent > 0:
        fill_w = bar_w * min(100, max(0, _percent)) / 100
        segments = 28
        vertices = []
        palette = ((0.08, 0.80, 0.98), (0.35, 0.48, 1.0), (0.84, 0.34, 0.86))
        for i in range(segments):
            x1 = bar_x + fill_w * i / segments
            x2 = bar_x + fill_w * (i + 1) / segments
            color1, color2 = palette[i % 3], palette[(i + 1) % 3]
            a, b = (*color1, 1.0), (*color2, 1.0)
            vertices.extend(((x1, bar_y, *a), (x2, bar_y, *b), (x2, bar_y + bar_h, *b),
                             (x1, bar_y, *a), (x2, bar_y + bar_h, *b), (x1, bar_y + bar_h, *a)))
        _draw_vertices(vertices)
    gpu.state.blend_set("NONE")


def _tag_viewports():
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type == "VIEW_3D":
                area.tag_redraw()


def _redraw_now():
    global _last_draw
    now = time.perf_counter()
    if now - _last_draw < 0.12:
        return
    _last_draw = now
    _tag_viewports()
    # This pumps one viewport draw while a synchronous Blender operator runs.
    try:
        if bpy.context.window:
            bpy.ops.wm.redraw_timer(type="DRAW_WIN_SWAP", iterations=1)
    except (RuntimeError, AttributeError, TypeError):
        pass


def begin(stage="Preparing DNA import"):
    global _handler, _started, _last_draw, _percent, _stage
    if _handler is not None:
        end()
    _started = time.perf_counter()
    _last_draw = 0.0
    _percent = 0
    _stage = stage
    try:
        _handler = bpy.types.SpaceView3D.draw_handler_add(_draw, (), "WINDOW", "POST_PIXEL")
        _redraw_now()
    except (RuntimeError, AttributeError):
        # Background and unsupported graphics contexts still import normally.
        _handler = None


def update(percent, stage=None, force=False):
    global _percent, _stage, _last_draw
    _percent = min(100, max(0, int(percent)))
    if stage:
        _stage = stage
    if force:
        _last_draw = 0.0
    _redraw_now()


def end():
    global _handler, _percent, _stage
    if _handler is not None:
        try:
            bpy.types.SpaceView3D.draw_handler_remove(_handler, "WINDOW")
        except (RuntimeError, ValueError):
            pass
        _handler = None
        _tag_viewports()
    _percent = 0
    _stage = "Preparing"
