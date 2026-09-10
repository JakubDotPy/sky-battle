"""Zensical macro module: everything class-stat-shaped on the site reads `classes.toml` live.

Loaded once per build via `load_classes()` -- the same function the engine itself uses -- so a
balance pass changes the site on the next `zensical build` with no doc edit required. Charts are
hand-rolled inline SVG rather than Mermaid: Zensical only themes five Mermaid diagram types
(flowchart, sequence, class, state, ER) and its own docs warn that others "may not render well",
which a bar/radar comparison would be.
"""

import math

from skybattle.classes import load_classes

CLASSES = load_classes()
ORDER = ["scout", "fighter", "bomber"]
COLOR = {"scout": "#2563eb", "fighter": "#d97706", "bomber": "#7c3aed"}


def define_env(env):
    env.variables["classes"] = CLASSES
    env.variables["order"] = ORDER
    env.variables["color"] = COLOR

    env.macro(stat)
    env.macro(gun_stat)
    env.macro(sustained_dps)
    env.macro(radar_chart)
    env.macro(turn_curve_chart)
    env.macro(bubble_cone_chart)
    env.macro(airframe_table)
    env.macro(gun_table)
    env.macro(cone_table)


# ---------------------------------------------------------------- scalar lookups


def stat(kind: str, field: str):
    """One class's stat, straight from the table -- for a number quoted in prose."""
    return getattr(CLASSES[kind], field)


def gun_stat(kind: str, gun_name: str, field: str):
    for g in CLASSES[kind].guns:
        if g.name == gun_name:
            return getattr(g, field)
    raise KeyError(f"{kind!r} has no gun named {gun_name!r}")


def sustained_dps(kind: str, gun_name: str = "forward") -> float:
    g = next(g for g in CLASSES[kind].guns if g.name == gun_name)
    return round(g.damage / g.cooldown_ticks, 2)


# ---------------------------------------------------------------- markdown tables


def airframe_table() -> str:
    header = "| Class | HP | Radius | Stall | Corner | Max | Turn @ stall/corner/max | Bubble |"
    sep = "|---|---|---|---|---|---|---|---|"
    rows = [header, sep]
    for k in ORDER:
        c = CLASSES[k]
        rows.append(
            f"| {k} | {c.hp} | {c.radius:g} u | {c.stall_speed:g} | {c.corner_speed:g} | "
            f"{c.max_speed:g} u/tick | {c.turn_at_stall:g} / {c.turn_at_corner:g} / "
            f"{c.turn_at_max:g} deg | {c.bubble_range:g} u |"
        )
    return "\n".join(rows)


def gun_table() -> str:
    header = "| Class | Mount | Bearing | Dispersion | Cooldown | Damage | Ammo | Lifetime | Muzzle | Sustained DPS |"
    sep = "|---|---|---|---|---|---|---|---|---|---|"
    rows = [header, sep]
    for k in ORDER:
        for g in CLASSES[k].guns:
            dps = round(g.damage / g.cooldown_ticks, 2)
            rows.append(
                f"| {k} | {g.name} | {g.bearing_deg:g} deg | {g.dispersion_deg:g} deg | "
                f"{g.cooldown_ticks} ticks | {g.damage} | {g.ammo} | {g.lifetime_ticks} ticks | "
                f"{g.muzzle_speed:g} u/tick | {dps} |"
            )
    return "\n".join(rows)


def cone_table() -> str:
    header = "| Class | Forward cone | Rear cone | Bubble |"
    sep = "|---|---|---|---|"
    rows = [header, sep]
    for k in ORDER:
        c = CLASSES[k]
        rear = f"{c.rear_cone_deg:g} deg / {c.rear_cone_range:g} u" if c.rear_cone_deg > 0 else "none"
        rows.append(f"| {k} | {c.cone_deg:g} deg / {c.cone_range:g} u | {rear} | {c.bubble_range:g} u |")
    return "\n".join(rows)


# ---------------------------------------------------------------- SVG charts

_SVG_STYLE = 'style="max-width:100%;height:auto" font-family="ui-monospace, SFMono-Regular, Menlo, monospace"'


def _legend(y: int) -> str:
    parts = []
    for i, k in enumerate(ORDER):
        x = 20 + i * 120
        parts.append(
            f'<rect x="{x}" y="{y}" width="10" height="10" fill="{COLOR[k]}" />'
            f'<text x="{x + 16}" y="{y + 9}" font-size="12" fill="currentColor">{k}</text>'
        )
    return "".join(parts)


def radar_chart() -> str:
    """One polygon per class over seven normalised axes -- the class's overall SHAPE.

    Each axis is scaled independently to its own max across the three classes (plus 15%
    headroom), never to a shared unit, since HP and degrees have nothing in common. The point
    is silhouette, not absolute value -- the reference tables carry the exact numbers.
    """
    axes = [
        ("HP", {k: CLASSES[k].hp for k in ORDER}),
        ("Max speed", {k: CLASSES[k].max_speed for k in ORDER}),
        ("Turn @ corner", {k: CLASSES[k].turn_at_corner for k in ORDER}),
        ("Cone range", {k: CLASSES[k].cone_range for k in ORDER}),
        ("Cone width", {k: CLASSES[k].cone_deg for k in ORDER}),
        ("Bubble range", {k: CLASSES[k].bubble_range for k in ORDER}),
        ("Forward DPS", {k: sustained_dps(k) for k in ORDER}),
    ]
    n = len(axes)
    cx, cy, r_max = 260, 220, 160

    # Step 1 - one ring + label per axis, laid out clockwise starting at 12 o'clock.
    rings = []
    for i, (label, values) in enumerate(axes):
        angle = -math.pi / 2 + i * 2 * math.pi / n
        ax, ay = cx + r_max * math.cos(angle), cy + r_max * math.sin(angle)
        rings.append(
            f'<line x1="{cx}" y1="{cy}" x2="{ax:.1f}" y2="{ay:.1f}" '
            f'stroke="currentColor" stroke-opacity="0.25" />'
        )
        lx, ly = cx + (r_max + 14) * math.cos(angle), cy + (r_max + 14) * math.sin(angle)
        anchor = "middle" if abs(math.cos(angle)) < 0.3 else ("start" if math.cos(angle) > 0 else "end")
        rings.append(
            f'<text x="{lx:.1f}" y="{ly:.1f}" font-size="11" fill="currentColor" '
            f'text-anchor="{anchor}" dominant-baseline="middle">{label}</text>'
        )
    grid = "".join(
        f'<circle cx="{cx}" cy="{cy}" r="{r_max * frac:.1f}" fill="none" '
        f'stroke="currentColor" stroke-opacity="0.12" />'
        for frac in (0.25, 0.5, 0.75, 1.0)
    )

    # Step 2 - one polygon per class, each axis scaled to that axis's own headroom.
    polygons = []
    for k in ORDER:
        pts = []
        for i, (_, values) in enumerate(axes):
            headroom = max(values.values()) * 1.15 or 1.0
            frac = values[k] / headroom
            angle = -math.pi / 2 + i * 2 * math.pi / n
            pts.append(f"{cx + r_max * frac * math.cos(angle):.1f},{cy + r_max * frac * math.sin(angle):.1f}")
        polygons.append(
            f'<polygon points="{" ".join(pts)}" fill="{COLOR[k]}" fill-opacity="0.15" '
            f'stroke="{COLOR[k]}" stroke-width="2" />'
        )

    return (
        f'<svg viewBox="0 0 520 440" {_SVG_STYLE}>'
        f"{grid}{''.join(rings)}{''.join(polygons)}{_legend(410)}"
        f"</svg>"
    )


def turn_curve_chart() -> str:
    """Turn rate versus speed, one line per class, three points each.

    This is the chart that makes the corner-speed design fact visible: every line's peak sits
    at its MIDDLE point (corner speed), not its left end (stall speed) -- a monotonically
    falling line would instead make stall-speed pirouetting the dominant strategy.
    """
    left, top, w, h = 60, 20, 420, 260
    max_turn = max(max(c.turn_at_stall, c.turn_at_corner, c.turn_at_max) for c in CLASSES.values())
    max_turn *= 1.1

    def coords(k: str):
        c = CLASSES[k]
        turns = [c.turn_at_stall, c.turn_at_corner, c.turn_at_max]
        # x is positional (stall / corner / max), not speed-scaled: the three classes have
        # different speed ranges entirely, so a shared speed axis would misrepresent the shape
        # this chart exists to show.
        xs = [left, left + w / 2, left + w]
        ys = [top + h - (t / max_turn) * h for t in turns]
        return xs, ys

    axis = (
        f'<line x1="{left}" y1="{top + h}" x2="{left + w}" y2="{top + h}" stroke="currentColor" />'
        f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top + h}" stroke="currentColor" />'
        f'<text x="{left}" y="{top + h + 20}" font-size="11" fill="currentColor" text-anchor="middle">stall</text>'
        f'<text x="{left + w / 2}" y="{top + h + 20}" font-size="11" fill="currentColor" text-anchor="middle">corner</text>'
        f'<text x="{left + w}" y="{top + h + 20}" font-size="11" fill="currentColor" text-anchor="middle">max</text>'
        f'<text x="{left - 10}" y="{top}" font-size="11" fill="currentColor" text-anchor="end">'
        f"{max_turn / 1.1:.0f} deg/tick</text>"
    )

    lines = []
    for k in ORDER:
        xs, ys = coords(k)
        pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys, strict=True))
        dots = "".join(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" fill="{COLOR[k]}" />'
            for x, y in zip(xs, ys, strict=True)
        )
        lines.append(f'<polyline points="{pts}" fill="none" stroke="{COLOR[k]}" stroke-width="2.5" />{dots}')

    return f'<svg viewBox="0 0 500 350" {_SVG_STYLE}>{axis}{"".join(lines)}{_legend(325)}</svg>'


def bubble_cone_chart() -> str:
    """Grouped bars: cone width, cone range and bubble range, one group per class.

    Makes the bomber's trade legible without a table: shortest cone-width bar, longest
    bubble-range bar -- narrowest search cone, biggest already-know-it's-there radius.
    """
    metrics = [
        ("Cone width (deg)", {k: CLASSES[k].cone_deg for k in ORDER}),
        ("Cone range (u)", {k: CLASSES[k].cone_range for k in ORDER}),
        ("Bubble range (u)", {k: CLASSES[k].bubble_range for k in ORDER}),
    ]
    left, top, row_h, bar_h, gap = 130, 20, 70, 16, 4
    w = 300

    rows = []
    for i, (label, values) in enumerate(metrics):
        y0 = top + i * row_h
        headroom = max(values.values()) * 1.1
        rows.append(
            f'<text x="{left - 10}" y="{y0 + row_h / 2}" font-size="12" '
            f'fill="currentColor" text-anchor="end" dominant-baseline="middle">{label}</text>'
        )
        for j, k in enumerate(ORDER):
            by = y0 + j * (bar_h + gap)
            bw = (values[k] / headroom) * w
            rows.append(f'<rect x="{left}" y="{by}" width="{bw:.1f}" height="{bar_h}" fill="{COLOR[k]}" />')
            rows.append(
                f'<text x="{left + bw + 6}" y="{by + bar_h - 4}" font-size="11" '
                f'fill="currentColor">{values[k]:g}</text>'
            )

    total_h = top + len(metrics) * row_h + 30
    return f'<svg viewBox="0 0 520 {total_h}" {_SVG_STYLE}>{"".join(rows)}{_legend(total_h - 20)}</svg>'
