#!/usr/bin/env python3
"""Wrap X-Tracer DOT node labels with cell-type icons.

The X-Tracer CLI emits plain Graphviz DOT. This helper preserves the graph
structure and replaces known typed node labels with an HTML table containing an
icon and the original label text. Unknown cell types remain text-only.
"""

from __future__ import annotations

import argparse
import re
from html import escape
from pathlib import Path


ICON_BY_TYPE = {
    "assign": "buf.png",
    "buf": "buf.png",
    "dff_r": "dff_r.png",
    "and": "and.png",
    "or": "or.png",
    "xor": "xor.png",
}

HTML_NODE_RE = re.compile(r'^(\s*n\d+) \[label=<(.+)>\];\s*$')
TEXT_NODE_RE = re.compile(r'^(\s*n\d+) \[label="((?:[^"\\]|\\.)*)"\];\s*$')


def _decode_dot_text(value: str) -> str:
    return value.replace(r"\n", "\n").replace(r"\"", '"').replace(r"\\", "\\")


def _text_label_to_html(value: str) -> str:
    parts = _decode_dot_text(value).split("\n")
    return '<BR ALIGN="CENTER"/>'.join(escape(part, quote=False) for part in parts)


def _cell_type_from_label(label_html: str) -> str | None:
    match = re.search(r'type=([^<\s]+)', label_html)
    return match.group(1) if match else None


def _wrap_with_icon(node_name: str, label_html: str, icon_path: Path) -> str:
    return (
        f'{node_name} [shape=plain, margin=0, label=<\n'
        f'    <TABLE BORDER="1" CELLBORDER="0" CELLPADDING="4" CELLSPACING="0" COLOR="#334155">\n'
        f'      <TR><TD><IMG SRC="{escape(str(icon_path))}"/></TD></TR>\n'
        f'      <TR><TD><FONT POINT-SIZE="10">{label_html}</FONT></TD></TR>\n'
        f'    </TABLE>\n'
        f'  >];'
    )


def iconize_dot(input_path: Path, output_path: Path, icon_dir: Path) -> int:
    rewritten: list[str] = []
    changed = 0

    for line in input_path.read_text().splitlines():
        label_html: str | None = None
        node_name: str | None = None

        html_match = HTML_NODE_RE.match(line)
        if html_match:
            node_name = html_match.group(1)
            label_html = html_match.group(2)
        else:
            text_match = TEXT_NODE_RE.match(line)
            if text_match:
                node_name = text_match.group(1)
                label_html = _text_label_to_html(text_match.group(2))

        if node_name is None or label_html is None:
            rewritten.append(line)
            continue

        cell_type = _cell_type_from_label(label_html)
        icon_name = ICON_BY_TYPE.get(cell_type or "")
        if icon_name is None:
            rewritten.append(line)
            continue

        rewritten.append(_wrap_with_icon(node_name, label_html, icon_dir / icon_name))
        changed += 1

    output_path.write_text("\n".join(rewritten) + "\n")
    return changed


def main() -> None:
    parser = argparse.ArgumentParser(description="Embed cell icons into X-Tracer DOT output")
    parser.add_argument("input", type=Path, help="Input DOT file from x_tracer.py -f dot")
    parser.add_argument("output", type=Path, help="Output iconized DOT file")
    parser.add_argument("--icon-dir", type=Path, default=Path("x-tracer-icons"),
                        help="Directory containing icon PNGs, written into DOT IMG paths")
    args = parser.parse_args()

    changed = iconize_dot(args.input, args.output, args.icon_dir)
    print(f"iconized {changed} nodes")


if __name__ == "__main__":
    main()
