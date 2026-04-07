from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Optional

from .registry import Registry

TEXT_LINE_GAP = 8
FAMILY_TEXT_X_PADDING = 18
FAMILY_TEXT_TOP_PADDING = 28
FAMILY_TEXT_BOTTOM_PADDING = 18
NODE_TEXT_X_PADDING = 18
NODE_TEXT_TOP_PADDING = 28
NODE_TEXT_BOTTOM_PADDING = 18


def render_family_tree_mermaid(
    registry: Registry,
    family_id: str,
    *,
    annotations: Optional[Dict[str, Dict[str, Any]]] = None,
) -> str:
    family = registry.get_family(family_id)
    versions = registry.list_versions(family_id)
    annotations = annotations or {}

    lines = ["flowchart LR"]
    family_node_id = _node_id(family.id)
    family_label = _escape_label(f"{family.name}<br/>current: {family.current_version}")
    lines.append(f'    {family_node_id}(["{family_label}"])')

    depth_map = _depth_map(versions)
    grouped_by_depth: Dict[int, List[Any]] = defaultdict(list)
    for version in versions:
        grouped_by_depth[depth_map.get(version.id, 0)].append(version)

    for depth in sorted(grouped_by_depth):
        if depth > 0:
            lines.append(f'    subgraph generation_{depth}["Generation {depth}"]')
            lines.append("        direction TB")
        for version in sorted(grouped_by_depth[depth], key=lambda item: item.id):
            extra = annotations.get(version.id, {})
            label = _escape_label(version.id)
            indent = "        " if depth > 0 else "    "
            lines.append(f'{indent}{_node_id(version.id)}["{label}"]')
            classes = _version_classes(version.id, family.current_version, extra)
            if classes:
                lines.append(f"{indent}class {_node_id(version.id)} {','.join(classes)}")
        if depth > 0:
            lines.append("    end")

    root_ids: List[str] = []
    for version in versions:
        if version.parent_id:
            lines.append(f"    {_node_id(version.parent_id)} --> {_node_id(version.id)}")
        else:
            root_ids.append(version.id)
    for version_id in root_ids:
        lines.append(f"    {family_node_id} --> {_node_id(version_id)}")
    return "\n".join(lines)


def render_family_tree_svg(
    registry: Registry,
    family_id: str,
    *,
    annotations: Optional[Dict[str, Dict[str, Any]]] = None,
) -> str:
    family = registry.get_family(family_id)
    versions = registry.list_versions(family_id)
    annotations = annotations or {}
    depth_map = _depth_map(versions)
    grouped_by_depth: Dict[int, List[Any]] = defaultdict(list)
    for version in versions:
        grouped_by_depth[depth_map.get(version.id, 0)].append(version)

    node_layouts: Dict[str, Dict[str, float]] = {}
    generation_layouts: Dict[int, Dict[str, float]] = {}

    margin_x = 40
    margin_y = 40
    family_width = 220
    generation_gap = 56
    group_width = 388
    node_width = 336
    node_gap = 24
    group_padding_x = 24
    family_text_width = family_width - FAMILY_TEXT_X_PADDING * 2
    node_text_width = node_width - NODE_TEXT_X_PADDING * 2

    family_style = {"fill": "#dbeafe", "stroke": "#1d4ed8", "text": "#172554"}
    family_lines = _family_text_lines(family, family_style["text"], family_text_width)
    family_height = _text_block_height(family_lines, FAMILY_TEXT_TOP_PADDING, FAMILY_TEXT_BOTTOM_PADDING)

    max_stack_height = family_height
    generation_heights: Dict[int, float] = {}
    for depth, nodes in grouped_by_depth.items():
        stack_height = 0.0
        for index, version in enumerate(sorted(nodes, key=lambda item: item.id)):
            extra = annotations.get(version.id, {})
            node_height = _node_height(version, extra, node_text_width)
            stack_height += node_height
            if index < len(nodes) - 1:
                stack_height += node_gap
        total_height = _group_padding_top(depth) + stack_height + _group_padding_bottom(depth)
        generation_heights[depth] = total_height
        max_stack_height = max(max_stack_height, total_height)

    canvas_height = max_stack_height + margin_y * 2
    family_x = margin_x
    family_y = (canvas_height - family_height) / 2

    for depth in sorted(grouped_by_depth):
        group_x = margin_x + family_width + generation_gap + depth * (group_width + generation_gap)
        group_y = (canvas_height - generation_heights[depth]) / 2
        generation_layouts[depth] = {"x": group_x, "y": group_y, "width": group_width, "height": generation_heights[depth]}

        cursor_y = group_y + _group_padding_top(depth)
        for version in sorted(grouped_by_depth[depth], key=lambda item: item.id):
            extra = annotations.get(version.id, {})
            height = _node_height(version, extra, node_text_width)
            node_layouts[version.id] = {
                "x": group_x + group_padding_x,
                "y": cursor_y,
                "width": node_width,
                "height": height,
            }
            cursor_y += height + node_gap

    canvas_width = (
        margin_x
        + family_width
        + generation_gap
        + (max(grouped_by_depth.keys(), default=0) + 1) * group_width
        + max(grouped_by_depth.keys(), default=0) * generation_gap
        + margin_x
    )

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{int(canvas_width)}" height="{int(canvas_height)}" viewBox="0 0 {int(canvas_width)} {int(canvas_height)}">',
        "<defs>",
        '<filter id="shadow" x="-20%" y="-20%" width="140%" height="140%">',
        '<feDropShadow dx="0" dy="3" stdDeviation="6" flood-color="#0f172a" flood-opacity="0.08"/>',
        "</filter>",
        "</defs>",
        '<rect width="100%" height="100%" fill="#f8fafc"/>',
    ]

    for depth, layout in generation_layouts.items():
        if depth == 0:
            continue
        parts.append(
            f'<rect x="{layout["x"]:.1f}" y="{layout["y"]:.1f}" width="{layout["width"]:.1f}" height="{layout["height"]:.1f}" '
            'rx="16" fill="#ffffff" stroke="#e2e8f0" stroke-width="1.5"/>'
        )

    parts.append(
        f'<rect x="{family_x:.1f}" y="{family_y:.1f}" width="{family_width:.1f}" height="{family_height:.1f}" rx="18" '
        f'fill="{family_style["fill"]}" stroke="{family_style["stroke"]}" stroke-width="2.5" filter="url(#shadow)"/>'
    )
    parts.extend(
        _svg_text_block(x=family_x + FAMILY_TEXT_X_PADDING, y=family_y + FAMILY_TEXT_TOP_PADDING, lines=family_lines)
    )

    root_ids = [version.id for version in versions if not version.parent_id]
    for version in versions:
        source = family if not version.parent_id else next(v for v in versions if v.id == version.parent_id)
        source_layout = (
            {"x": family_x, "y": family_y, "width": family_width, "height": family_height}
            if not version.parent_id
            else node_layouts[source.id]
        )
        target_layout = node_layouts[version.id]
        parts.append(_svg_connector(source_layout, target_layout))

    for version in versions:
        extra = annotations.get(version.id, {})
        classes = _version_classes(version.id, family.current_version, extra)
        style = _node_style(classes)
        layout = node_layouts[version.id]
        parts.append(
            f'<rect x="{layout["x"]:.1f}" y="{layout["y"]:.1f}" width="{layout["width"]:.1f}" height="{layout["height"]:.1f}" '
            f'rx="14" fill="{style["fill"]}" stroke="{style["stroke"]}" stroke-width="{style["stroke_width"]}" filter="url(#shadow)"/>'
        )
        parts.extend(
            _svg_node_text(version, extra, layout["x"] + NODE_TEXT_X_PADDING, layout["y"] + NODE_TEXT_TOP_PADDING, style["text"], node_text_width)
        )

    parts.append("</svg>")
    return "\n".join(parts)


def _svg_node_text(version: Any, extra: Dict[str, Any], x: float, y: float, color: str, max_width: float) -> List[str]:
    return _svg_text_block(x=x, y=y, lines=_version_text_lines(version, extra, color, max_width))


def _svg_text_block(x: float, y: float, lines: List[Dict[str, Any]]) -> List[str]:
    parts: List[str] = []
    current_y = y
    for line in lines:
        size = line["size"]
        fill = line.get("fill", "#0f172a")
        if line.get("segments"):
            parts.append(
                f'<text x="{x:.1f}" y="{current_y:.1f}" text-anchor="start" font-family="Helvetica, Arial, sans-serif" '
                f'font-size="{size}" fill="{fill}">'
            )
            for segment in line["segments"]:
                segment_attrs = []
                if "weight" in segment:
                    segment_attrs.append(f'font-weight="{segment["weight"]}"')
                if segment.get("fill") and segment["fill"] != fill:
                    segment_attrs.append(f'fill="{segment["fill"]}"')
                attrs = f" {' '.join(segment_attrs)}" if segment_attrs else ""
                parts.append(f"<tspan{attrs}>{_escape_xml(str(segment['text']))}</tspan>")
            parts.append("</text>")
        else:
            text = _escape_xml(str(line["text"]))
            weight = line["weight"]
            parts.append(
                f'<text x="{x:.1f}" y="{current_y:.1f}" text-anchor="start" font-family="Helvetica, Arial, sans-serif" '
                f'font-size="{size}" font-weight="{weight}" fill="{fill}">{text}</text>'
            )
        current_y += size + TEXT_LINE_GAP
    return parts


def _svg_connector(source: Dict[str, float], target: Dict[str, float]) -> str:
    x1 = source["x"] + source["width"]
    y1 = source["y"] + source["height"] / 2
    x2 = target["x"]
    y2 = target["y"] + target["height"] / 2
    c1 = x1 + 28
    c2 = x2 - 28
    return (
        f'<path d="M {x1:.1f} {y1:.1f} C {c1:.1f} {y1:.1f}, {c2:.1f} {y2:.1f}, {x2:.1f} {y2:.1f}" '
        'fill="none" stroke="#94a3b8" stroke-width="2.5" stroke-linecap="round"/>'
    )


def _node_height(version: Any, extra: Dict[str, Any], max_width: float) -> float:
    lines = _version_text_lines(version, extra, "#0f172a", max_width)
    return _text_block_height(lines, NODE_TEXT_TOP_PADDING, NODE_TEXT_BOTTOM_PADDING)


def _node_style(classes: List[str]) -> Dict[str, Any]:
    style = {"fill": "#f8fafc", "stroke": "#475569", "text": "#0f172a", "stroke_width": 2.0}
    if "loser" in classes:
        style.update({"fill": "#fee2e2", "stroke": "#dc2626", "text": "#7f1d1d"})
    if "lineage" in classes:
        style.update({"fill": "#ecfdf5", "stroke": "#16a34a", "text": "#166534", "stroke_width": 2.5})
    if "winner" in classes:
        style.update({"fill": "#dcfce7", "stroke": "#15803d", "text": "#14532d", "stroke_width": 3.0})
    if "current" in classes:
        style.update({"fill": "#bbf7d0", "stroke": "#166534", "text": "#14532d", "stroke_width": 3.0})
    return style


def _version_classes(version_id: str, current_version_id: str, extra: Dict[str, Any]) -> List[str]:
    classes: List[str] = ["candidate"]
    if version_id == current_version_id:
        classes.append("current")
    annotation_classes = extra.get("_class")
    if isinstance(annotation_classes, str):
        classes.append(annotation_classes)
    elif isinstance(annotation_classes, Iterable):
        classes.extend(str(item) for item in annotation_classes)
    return list(dict.fromkeys(classes))


def _depth_map(versions: List[Any]) -> Dict[str, int]:
    versions_by_id = {version.id: version for version in versions}
    depth_cache: Dict[str, int] = {}

    def depth_for(version_id: str) -> int:
        if version_id in depth_cache:
            return depth_cache[version_id]
        version = versions_by_id[version_id]
        if not version.parent_id or version.parent_id not in versions_by_id:
            depth_cache[version_id] = 0
        else:
            depth_cache[version_id] = depth_for(version.parent_id) + 1
        return depth_cache[version_id]

    for version in versions:
        depth_for(version.id)
    return depth_cache


def _node_id(value: str) -> str:
    sanitized = re.sub(r"[^a-zA-Z0-9_]", "_", value)
    if not sanitized or sanitized[0].isdigit():
        sanitized = f"node_{sanitized}"
    return sanitized


def _escape_label(value: str) -> str:
    return value.replace('"', "&quot;")


def _escape_xml(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _family_text_lines(family: Any, color: str, max_width: float) -> List[Dict[str, Any]]:
    lines: List[Dict[str, Any]] = []
    lines.extend(_plain_text_lines(family.name, size=22, weight=800, fill=color, max_width=max_width))
    lines.extend(
        _plain_text_lines(
            f"current: {family.current_version}",
            size=14,
            weight=700,
            fill=color,
            max_width=max_width,
        )
    )
    return lines


def _version_text_lines(version: Any, extra: Dict[str, Any], color: str, max_width: float) -> List[Dict[str, Any]]:
    subtitle = version.label if version.label != version.id else ""
    lines: List[Dict[str, Any]] = []
    lines.extend(_plain_text_lines(version.id, size=22, weight=800, fill=color, max_width=max_width))
    if subtitle:
        lines.extend(_plain_text_lines(subtitle, size=13, weight=500, fill="#475569", max_width=max_width))
    for key in sorted((item for item in extra if not item.startswith("_")), key=_annotation_sort_key):
        if key.startswith("_"):
            continue
        lines.extend(_key_value_lines(_display_key_label(key), extra[key], fill=color, max_width=max_width))
    return lines


def _annotation_sort_key(key: str) -> tuple[int, str]:
    normalized = re.sub(r"_\d+$", "", key)
    priority = {
        "avg_score": 0,
        "score": 0,
        "score_delta": 1,
        "prompt_change": 2,
        "rounds": 3,
        "time_ms": 4,
        "peak_kb": 5,
        "failures": 6,
    }
    return priority.get(normalized, 50), key


def _display_key_label(key: str) -> str:
    normalized = re.sub(r"_\d+$", "", key)
    aliases = {
        "avg_score": "score",
        "score": "score",
        "score_delta": "vs parent",
        "prompt_change": "prompt change",
        "rounds": "rounds",
        "time_ms": "time ms",
        "peak_kb": "peak kb",
        "failures": "failures",
    }
    return aliases.get(normalized, normalized.replace("_", " "))


def _plain_text_lines(text: Any, *, size: int, weight: int, fill: str, max_width: float) -> List[Dict[str, Any]]:
    return [
        {"text": chunk, "size": size, "weight": weight, "fill": fill}
        for chunk in _wrap_text(str(text), size=size, weight=weight, max_width=max_width)
    ]


def _key_value_lines(key: str, value: Any, *, fill: str, max_width: float) -> List[Dict[str, Any]]:
    key_text = f"{key}:"
    first_line_width = max(40.0, max_width - _estimate_text_width(f"{key_text} ", size=12, weight=800))
    wrapped_values = _wrap_text(str(value), size=12, weight=500, max_width=max_width, first_line_max_width=first_line_width)
    if not wrapped_values:
        return [{"text": key_text, "size": 12, "weight": 800, "fill": fill}]

    lines = [
        {
            "size": 12,
            "fill": fill,
            "segments": [
                {"text": key_text, "weight": 800, "fill": fill},
                {"text": f" {wrapped_values[0]}", "weight": 500, "fill": fill},
            ],
        }
    ]
    for chunk in wrapped_values[1:]:
        lines.append(
            {
                "size": 12,
                "fill": fill,
                "segments": [
                    {"text": chunk, "weight": 500, "fill": fill},
                ],
            }
        )
    return lines


def _wrap_text(text: str, *, size: int, weight: int, max_width: float, first_line_max_width: Optional[float] = None) -> List[str]:
    normalized = " ".join(text.split())
    if not normalized:
        return []

    words = normalized.split(" ")
    lines: List[str] = []
    current = ""
    current_limit = first_line_max_width or max_width
    index = 0

    while index < len(words):
        word = words[index]
        candidate = word if not current else f"{current} {word}"
        if _estimate_text_width(candidate, size=size, weight=weight) <= current_limit:
            current = candidate
            index += 1
            continue

        if current:
            lines.append(current)
            current = ""
            current_limit = max_width
            continue

        fragments = _split_long_token(word, size=size, weight=weight, max_width=current_limit)
        if len(fragments) == 1:
            current = fragments[0]
            index += 1
            continue

        lines.extend(fragments[:-1])
        current = fragments[-1]
        current_limit = max_width
        index += 1

    if current:
        lines.append(current)
    return lines


def _split_long_token(token: str, *, size: int, weight: int, max_width: float) -> List[str]:
    fragments: List[str] = []
    current = ""
    for char in token:
        candidate = f"{current}{char}"
        if current and _estimate_text_width(candidate, size=size, weight=weight) > max_width:
            fragments.append(current)
            current = char
        else:
            current = candidate
    if current:
        fragments.append(current)
    return fragments


def _estimate_text_width(text: str, *, size: int, weight: int) -> float:
    total = 0.0
    for char in text:
        if char.isspace():
            total += size * 0.32
        elif ord(char) > 127:
            total += size * 0.95
        elif char.isupper():
            total += size * (0.67 if weight >= 700 else 0.62)
        elif char.isdigit():
            total += size * 0.58
        elif char in "-_/.:,":
            total += size * 0.38
        else:
            total += size * (0.60 if weight >= 700 else 0.54)
    return total


def _text_block_height(lines: List[Dict[str, Any]], top_padding: float, bottom_padding: float) -> float:
    if not lines:
        return top_padding + bottom_padding
    text_height = sum(line["size"] for line in lines) + TEXT_LINE_GAP * (len(lines) - 1)
    return top_padding + text_height + bottom_padding


def _group_padding_top(depth: int) -> float:
    return 40.0 if depth > 0 else 0.0


def _group_padding_bottom(depth: int) -> float:
    return 24.0 if depth > 0 else 0.0
