"""Viewport progress overlay for long MetaMorphosis operations.

Renders an Apple-inspired frosted obsidian glass HUD inside the 3D Viewport
during DNA import and character assembly, using native GPU shaders.
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
_is_active = False
_started = 0.0
_last_draw = 0.0
_percent = 0
_stage = "Preparing"
_completion_time = 0.0
_shader = None
_font_id = None

# Color Palette: Apple-inspired obsidian glass with electric lime / cyan energy
LIME = (0.55, 0.98, 0.20)
CYAN = (0.20, 0.90, 0.82)
TEAL = (0.12, 0.70, 0.48)
WHITE = (0.98, 0.98, 1.0)
MUTED = (0.60, 0.62, 0.68)


def _get_shader():
    global _shader
    if _shader is None:
        _shader = gpu.shader.from_builtin("SMOOTH_COLOR")
    return _shader


def _draw_vertices(vertices):
    if not vertices:
        return
    shader = _get_shader()
    shader.bind()
    batch_for_shader(shader, "TRIS", {"pos": [v[:2] for v in vertices], "color": [v[2:] for v in vertices]}).draw(shader)


def _rect(x1, y1, x2, y2, color):
    r, g, b, a = color
    vertex = lambda x, y: (x, y, r, g, b, a)
    _draw_vertices((vertex(x1, y1), vertex(x2, y1), vertex(x2, y2), vertex(x1, y1), vertex(x2, y2), vertex(x1, y2)))


def _rounded_rect(x1, y1, x2, y2, r, top_col, bot_col=None):
    if bot_col is None:
        bot_col = top_col
    r = max(0.0, min(r, (x2 - x1) * 0.5, (y2 - y1) * 0.5))
    xa, xb = x1 + r, x2 - r
    ya, yb = y1 + r, y2 - r
    h = y2 - y1

    def vert(x, y):
        t = (y - y1) / h if h > 0.0 else 0.0
        c = tuple(b + (a - b) * t for a, b in zip(top_col, bot_col))
        return (x, y, *c)

    tris = []
    # Center middle band
    tris.extend((vert(x1, ya), vert(x2, ya), vert(x2, yb), vert(x1, ya), vert(x2, yb), vert(x1, yb)))
    # Top center band
    tris.extend((vert(xa, yb), vert(xb, yb), vert(xb, y2), vert(xa, yb), vert(xb, y2), vert(xa, y2)))
    # Bottom center band
    tris.extend((vert(xa, y1), vert(xb, y1), vert(xb, ya), vert(xa, y1), vert(xb, ya), vert(xa, ya)))

    # 4 corner fan arcs (8 steps each = 32 triangles total)
    steps = 8
    corners = (
        (xb, yb, 0.0, math.pi * 0.5),          # Top-Right
        (xa, yb, math.pi * 0.5, math.pi),       # Top-Left
        (xa, ya, math.pi, math.pi * 1.5),       # Bottom-Left
        (xb, ya, math.pi * 1.5, math.pi * 2.0), # Bottom-Right
    )
    for cx, cy, a_start, a_end in corners:
        c_pt = vert(cx, cy)
        step_rad = (a_end - a_start) / steps
        for i in range(steps):
            th1 = a_start + i * step_rad
            th2 = a_start + (i + 1) * step_rad
            p1 = vert(cx + r * math.cos(th1), cy + r * math.sin(th1))
            p2 = vert(cx + r * math.cos(th2), cy + r * math.sin(th2))
            tris.extend((c_pt, p1, p2))
    _draw_vertices(tris)


def _wave(card_x, card_y, card_w, elapsed, lane):
    count = 60
    center = card_y + 154 + lane * 6
    amplitudes = (11.0, 8.0, 6.0, 9.0)
    speeds = (1.8, 2.2, 1.4, 2.5)
    phases = (0.0, 1.0, 2.1, 3.2)
    thicknesses = (1.8, 1.4, 1.2, 1.1)

    amp = amplitudes[lane % len(amplitudes)]
    speed = speeds[lane % len(speeds)]
    phase_offset = phases[lane % len(phases)]
    thick = thicknesses[lane % len(thicknesses)]

    pad = 42.0
    span = card_w - pad * 2
    vertices = []

    for i in range(count):
        t1 = i / count
        t2 = (i + 1) / count
        x1 = card_x + pad + span * t1
        x2 = card_x + pad + span * t2

        # Smooth bell envelope pinching at ends
        env1 = math.sin(t1 * math.pi) ** 1.8
        env2 = math.sin(t2 * math.pi) ** 1.8

        ph = elapsed * speed + phase_offset
        y1 = center + math.sin(t1 * 10.5 + ph) * amp * env1
        y2 = center + math.sin(t2 * 10.5 + ph) * amp * env2

        if lane == 0:
            c1 = (0.55, 0.98, 0.20, 0.85 * env1)
            c2 = (0.20, 0.90, 0.82, 0.85 * env2)
        elif lane == 1:
            c1 = (0.20, 0.90, 0.82, 0.55 * env1)
            c2 = (0.55, 0.98, 0.20, 0.55 * env2)
        elif lane == 2:
            c1 = (0.12, 0.70, 0.48, 0.40 * env1)
            c2 = (0.15, 0.85, 0.60, 0.40 * env2)
        else:
            # Specular crest line
            c1 = (0.95, 1.0, 0.98, 0.50 * env1)
            c2 = (0.95, 1.0, 0.98, 0.50 * env2)

        a = (x1, y1 - thick, *c1)
        b = (x2, y2 - thick, *c2)
        c = (x2, y2 + thick, *c2)
        d = (x1, y1 + thick, *c1)
        vertices.extend((a, b, c, a, c, d))

    _draw_vertices(vertices)


def _text(text, x, y, size, color, center=False):
    global _font_id
    if _font_id is None:
        candidates = (
            r"C:\Windows\Fonts\segoeui.ttf",
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


def _draw_contents():
    global _completion_time
    context = bpy.context
    region = context.region
    if region is None or region.type != "WINDOW":
        return
    width, height = region.width, region.height
    if width < 320 or height < 300:
        return

    now = time.perf_counter()

    # Safety Auto-Dismiss Protection:
    # 1. If 100% complete for > 1.0s, dismiss automatically and safely without recursive redraw
    if _percent >= 100:
        if _completion_time == 0.0:
            _completion_time = now
        elif now - _completion_time > 1.0:
            _is_active = False
            if _handler is not None:
                try:
                    bpy.types.SpaceView3D.draw_handler_remove(_handler, "WINDOW")
                except Exception:
                    pass
                _handler = None
            _tag_viewports()
            return
    # 2. Watchdog timeout: auto-dismiss if running for > 180s without completion
    if now - _started > 180.0:
        _is_active = False
        if _handler is not None:
            try:
                bpy.types.SpaceView3D.draw_handler_remove(_handler, "WINDOW")
            except Exception:
                pass
            _handler = None
        _tag_viewports()
        return

    gpu.state.blend_set("ALPHA")

    # Dark backdrop vignette
    _rect(0, 0, width, height, (0.006, 0.007, 0.010, 0.60))

    # Floating Glass Card Dimensions
    card_w = min(640, width - 48)
    card_h = 290
    card_x = (width - card_w) / 2
    card_y = (height - card_h) / 2
    radius = 26.0

    # 1. Multi-Layer Diffused Ambient Drop Shadow (5-step elevation)
    for s in (5, 4, 3, 2, 1):
        spread = s * 6.5
        alpha = 0.048 * (1.0 - (s - 1) / 5.0) ** 1.8
        _rounded_rect(
            card_x - spread,
            card_y - spread - 6.0,
            card_x + card_w + spread,
            card_y + card_h + spread - 6.0,
            radius + spread * 0.5,
            (0.0, 0.0, 0.0, alpha),
        )

    # 2. Dual-Tone Specular Rim & Glass Border (1.2px)
    rim = 1.2
    _rounded_rect(
        card_x - rim,
        card_y - rim,
        card_x + card_w + rim,
        card_y + card_h + rim,
        radius + rim,
        (1.0, 1.0, 1.0, 0.38),  # Top crisp specular light
        (1.0, 1.0, 1.0, 0.06),  # Bottom subtle dark glass edge
    )

    # 3. Frosted Obsidian Glass Body
    _rounded_rect(
        card_x,
        card_y,
        card_x + card_w,
        card_y + card_h,
        radius,
        (0.065, 0.070, 0.084, 0.95),  # Top obsidian glass
        (0.032, 0.034, 0.042, 0.98),  # Deep bottom graphite
    )

    # 4. Top Horizon Sheen Reflection
    sheen_h = 92.0
    _rounded_rect(
        card_x,
        card_y + card_h - sheen_h,
        card_x + card_w,
        card_y + card_h,
        radius,
        (1.0, 1.0, 1.0, 0.065),
        (1.0, 1.0, 1.0, 0.0),
    )

    # 5. Inner Inset Line (0.8px inside the glass body)
    inset = 1.0
    _rounded_rect(
        card_x + inset,
        card_y + inset,
        card_x + card_w - inset,
        card_y + card_h - inset,
        radius - inset,
        (1.0, 1.0, 1.0, 0.05),
        (1.0, 1.0, 1.0, 0.01),
    )

    # Animated Fluid Siri-style Energy Waves (4 harmonic lanes)
    elapsed = now - _started
    _wave(card_x, card_y, card_w, elapsed, 0)
    _wave(card_x, card_y, card_w, elapsed, 1)
    _wave(card_x, card_y, card_w, elapsed, 2)
    _wave(card_x, card_y, card_w, elapsed, 3)

    center_x = width / 2

    # App Title & Category Badge
    _text("METAMORPHOSIS", center_x, card_y + 232, 18, (*WHITE, 1.0), center=True)

    badge_w, badge_h = 140.0, 20.0
    badge_x = center_x - badge_w / 2
    badge_y = card_y + 202
    # Pill badge glowing border + background
    _rounded_rect(badge_x - 1, badge_y - 1, badge_x + badge_w + 1, badge_y + badge_h + 1, (badge_h + 2) / 2, (*LIME, 0.45), (*LIME, 0.18))
    _rounded_rect(badge_x, badge_y, badge_x + badge_w, badge_y + badge_h, badge_h / 2, (0.04, 0.12, 0.06, 0.88), (0.02, 0.08, 0.04, 0.94))
    _text("METAHUMAN PIPELINE", center_x, badge_y + 4.8, 9, (*LIME, 0.98), center=True)

    # Stage Status & Big Percentage
    _text(_stage, center_x, card_y + 104, 13, (*WHITE, 0.95), center=True)
    _text(f"{_percent:02d}%", center_x, card_y + 64, 25, (*WHITE, 1.0), center=True)

    # Pill Progress Bar with Radiant Glow
    bar_w, bar_h = min(480, card_w - 96), 8.0
    bar_x, bar_y = center_x - bar_w / 2, card_y + 38

    # Bar background groove
    _rounded_rect(bar_x - 1, bar_y - 1, bar_x + bar_w + 1, bar_y + bar_h + 1, (bar_h + 2) / 2, (1, 1, 1, 0.12), (1, 1, 1, 0.04))
    _rounded_rect(bar_x, bar_y, bar_x + bar_w, bar_y + bar_h, bar_h / 2, (0.08, 0.08, 0.10, 0.92), (0.04, 0.04, 0.06, 0.96))

    if _percent > 0:
        fill_w = max(bar_h, bar_w * min(100, max(0, _percent)) / 100.0)
        # Soft outer bar glow
        _rounded_rect(bar_x - 2, bar_y - 2, bar_x + fill_w + 2, bar_y + bar_h + 2, (bar_h + 4) / 2, (*LIME, 0.20), (*CYAN, 0.10))
        # Radiant fill gradient
        _rounded_rect(bar_x, bar_y, bar_x + fill_w, bar_y + bar_h, bar_h / 2, (*LIME, 1.0), (*CYAN, 1.0))
        # Specular upper half reflection (glass liquid tube effect)
        _rounded_rect(bar_x + 1, bar_y + bar_h * 0.5, bar_x + fill_w - 1, bar_y + bar_h - 1, (bar_h * 0.5) / 2, (1.0, 1.0, 1.0, 0.30), (1.0, 1.0, 1.0, 0.0))
        # Leading edge sparkle cap
        if fill_w < bar_w:
            cap_w = min(5.0, fill_w)
            _rounded_rect(bar_x + fill_w - cap_w, bar_y, bar_x + fill_w, bar_y + bar_h, bar_h / 2, (1.0, 1.0, 1.0, 0.92))

    # Elapsed Time Subtext (Bottom Right)
    secs = int(elapsed)
    mins = secs // 60
    time_str = f"{mins:02d}:{secs % 60:02d}s"
    _text(time_str, card_x + card_w - 56, card_y + 16, 9, (*MUTED, 0.70))

    gpu.state.blend_set("NONE")


def _draw():
    if not _is_active:
        return
    previous_blend = gpu.state.blend_get()
    try:
        _draw_contents()
    finally:
        gpu.state.blend_set(previous_blend)


def _tag_viewports():
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type == "VIEW_3D":
                area.tag_redraw()


def _redraw_now():
    global _last_draw
    now = time.perf_counter()
    if now - _last_draw < 0.20:
        return
    _last_draw = now
    _tag_viewports()
    # Pump one clean window swap so the overlay updates at major importer milestones
    try:
        if bpy.context.window and not bpy.app.background:
            bpy.ops.wm.redraw_timer(type="DRAW_WIN_SWAP", iterations=1)
    except (RuntimeError, AttributeError, TypeError):
        pass


def begin(stage="Preparing DNA import"):
    global _handler, _started, _last_draw, _percent, _stage, _is_active, _completion_time
    if _handler is not None or _is_active:
        end()
    _is_active = True
    _started = time.perf_counter()
    _last_draw = 0.0
    _percent = 0
    _stage = stage
    _completion_time = 0.0
    if bpy.app.background:
        return
    try:
        _handler = bpy.types.SpaceView3D.draw_handler_add(_draw, (), "WINDOW", "POST_PIXEL")
        _redraw_now()
    except (RuntimeError, AttributeError):
        # Background and unsupported graphics contexts still import normally.
        _handler = None


def update(percent, stage=None, force=False):
    global _percent, _stage, _last_draw, _is_active
    if not _is_active:
        return
    _percent = min(100, max(0, int(percent)))
    if stage:
        _stage = stage
    if force:
        _last_draw = 0.0
    if _handler is not None and not bpy.app.background:
        _redraw_now()


def end():
    global _handler, _percent, _stage, _is_active, _completion_time
    _is_active = False
    _completion_time = 0.0
    if _handler is not None:
        try:
            bpy.types.SpaceView3D.draw_handler_remove(_handler, "WINDOW")
        except Exception:
            pass
        _handler = None
    _percent = 0
    _stage = "Preparing"
    _tag_viewports()


@bpy.app.handlers.persistent
def _on_file_load(dummy=None):
    end()


if _on_file_load not in bpy.app.handlers.load_post:
    bpy.app.handlers.load_post.append(_on_file_load)
if _on_file_load not in bpy.app.handlers.load_pre:
    bpy.app.handlers.load_pre.append(_on_file_load)
