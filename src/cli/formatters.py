"""Output formatters for X-Tracer cause trees: text, json, dot."""

from __future__ import annotations

import json
from html import escape
from typing import Any

from src.tracer.core import XCause


def format_text(node: XCause, indent: int = 0) -> str:
    """Format cause tree as human-readable indented text."""
    lines: list[str] = []
    _format_text_recursive(node, indent, lines)
    return "\n".join(lines)


def _format_text_recursive(node: XCause, indent: int, lines: list[str]) -> None:
    prefix = " " * indent
    gate_info = ""
    if node.gate is not None:
        gate_info = f" (gate={node.gate.cell_type}, inst={node.gate.instance_path})"
    port_info = ""
    if node.top_level_port is not None:
        port_info = f" -> top-level port: {node.top_level_port}"
    lines.append(f"{prefix}[{node.cause_type}] {node.signal} @ t={node.time}{gate_info}{port_info}")
    for child in node.children:
        _format_text_recursive(child, indent + 2, lines)


def _node_to_dict(node: XCause) -> dict[str, Any]:
    """Convert XCause node to a JSON-serializable dict."""
    d: dict[str, Any] = {
        "signal": node.signal,
        "time": node.time,
        "cause_type": node.cause_type,
    }
    if node.gate is not None:
        d["gate"] = {
            "cell_type": node.gate.cell_type,
            "instance_path": node.gate.instance_path,
        }
    if node.top_level_port is not None:
        d["top_level_port"] = node.top_level_port
    if node.children:
        d["children"] = [_node_to_dict(c) for c in node.children]
    else:
        d["children"] = []
    return d


def format_json(node: XCause) -> str:
    """Format cause tree as JSON."""
    return json.dumps(_node_to_dict(node), indent=2)


def format_dot(node: XCause, direction: str = "forward") -> str:
    """Format cause tree as Graphviz DOT.

    direction="forward" renders causes/inputs on the left flowing toward the
    queried X output. direction="backward" preserves the raw cause-tree order.
    """
    rankdir = "LR" if direction == "forward" else "TB"
    lines: list[str] = [
        "digraph xcause {",
        f"  rankdir={rankdir};",
        '  bgcolor="#f3ead7";',
    ]
    node_ids: dict[int, str] = {}
    counter = [0]

    def format_signal(value: str) -> str:
        parts = value.split(".")
        if len(parts) < 2:
            return f"<B>{escape(value, quote=False)}</B>"
        prefix = ".".join(parts[:-2])
        suffix = ".".join(parts[-2:])
        if prefix:
            return f"{escape(prefix + '.', quote=False)}<B>{escape(suffix, quote=False)}</B>"
        return f"<B>{escape(suffix, quote=False)}</B>"

    def get_id(n: XCause) -> str:
        oid = id(n)
        if oid not in node_ids:
            node_ids[oid] = f"n{counter[0]}"
            counter[0] += 1
        return node_ids[oid]

    def visit(n: XCause) -> None:
        nid = get_id(n)
        label_parts = [
            escape(n.cause_type, quote=False),
            format_signal(n.signal),
            escape(f"t={n.time}", quote=False),
        ]
        if n.gate is not None:
            label_parts.append(escape(f"type={n.gate.cell_type}", quote=False))
        label = '<BR ALIGN="CENTER"/>'.join(label_parts)
        lines.append(f"  {nid} [label=<{label}>];")
        for child in n.children:
            cid = get_id(child)
            if direction == "forward":
                lines.append(f"  {cid} -> {nid};")
            else:
                lines.append(f"  {nid} -> {cid};")
            visit(child)

    visit(node)
    lines.append("}")
    return "\n".join(lines)
