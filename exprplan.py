"""Turn long weighted sums / products into driver-sized expression chunks.

Blender caps a scripted driver expression at 255 characters, while a single bone
channel of the MetaHuman rig can depend on dozens of RigLogic values. This module
(pure Python, no ``bpy``) splits such a sum into chunks that each fit in one
expression. The Blender-side builder then stores each chunk in a helper property
and adds the helpers up with a native ``SUM`` driver.

Only plain arithmetic is emitted (+ - * and comparisons) so every expression is
a *simple expression*: Blender evaluates it natively without running Python, so
it also works when "Auto Run Python Scripts" is disabled.
"""

from __future__ import annotations

import numpy as np

from .constants import MAX_EXPRESSION_LENGTH


def fmt_num(value: float, digits: int = 5) -> str:
    """Round to ``digits`` significant digits, then choose an equivalent short spelling."""
    value = float(value)
    if value == 0.0:
        return "0"
    text = np.format_float_positional(value, precision=digits, unique=False, fractional=False, trim="-")
    if text in ("-0", ""):
        return "0"
    # Shorter spelling of the SAME rounded coefficient permits more terms per
    # native expression. No weight or corrective is dropped to save drivers.
    compact = format(float(text), ".15g").replace("e-0", "e-").replace("e+0", "e+")
    if float(compact) != float(text):
        compact = text
    if text.startswith("0."):
        text = text[1:]
    elif text.startswith("-0."):
        text = "-" + text[2:]
    return min((text, compact), key=len)


def variable_name(index):
    return chr(ord('a') + index) if index < 26 else f"v{index}"


def _join_signed(parts: list[str]) -> str:
    """Join terms with ``+`` unless the term already starts with a minus sign."""
    out = ""
    for part in parts:
        if not out:
            out = part
        elif part.startswith("-"):
            out += part
        else:
            out += "+" + part
    return out


def _plan(terms, joiner: str, max_len: int):
    """Greedy chunking shared by sums and products.

    ``terms`` is an iterable of ``(template, keys)``; ``template`` uses ``{0}``, ``{1}``...
    placeholders that refer to ``keys`` (hashable variable identities). Returns a list of
    ``(expression, ordered_keys)`` where the expression names its variables ``v0``, ``v1``...
    """
    chunks = []
    names: dict = {}
    parts: list[str] = []
    length = 0

    def flush():
        nonlocal names, parts, length
        if parts:
            expr = _join_signed(parts) if joiner == "+" else "*".join(parts)
            chunks.append((expr, list(names.keys())))
        names = {}
        parts = []
        length = 0

    for template, keys in terms:
        for attempt in range(2):
            trial = dict(names)
            local = []
            for key in keys:
                if key not in trial:
                    trial[key] = variable_name(len(trial))
                local.append(trial[key])
            text = template.format(*local)
            extra = len(text) + (0 if (not parts or (joiner == "+" and text.startswith("-"))) else 1)
            if parts and length + extra > max_len and attempt == 0:
                flush()
                continue
            names = trial
            parts.append(text)
            length += extra
            break
    flush()
    return chunks


def plan_sum(terms, max_len: int = MAX_EXPRESSION_LENGTH):
    """Chunk ``a*x + b*y + ...`` into expressions no longer than ``max_len`` characters."""
    return _plan(terms, "+", max_len)


def plan_prod(factors, max_len: int = MAX_EXPRESSION_LENGTH):
    """Chunk ``a*x*y*...`` into expressions no longer than ``max_len`` characters."""
    return _plan(factors, "*", max_len)
