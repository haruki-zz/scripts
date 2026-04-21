#!/usr/bin/env python3

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    HRFlowable,
    KeepTogether,
    Paragraph,
    Preformatted,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


FONT_DIR = Path("/usr/share/fonts/truetype/dejavu")
SERIF = "DejaVuSerif"
SANS = "DejaVuSans"
MONO = "DejaVuSansMono"
TABLE_SEPARATOR_RE = re.compile(r"\|?[\s:|\-]+\|?")


@dataclass
class Block:
    kind: str
    data: dict


def register_fonts() -> None:
    pdfmetrics.registerFont(TTFont(SERIF, str(FONT_DIR / "DejaVuSerif.ttf")))
    pdfmetrics.registerFont(TTFont(f"{SERIF}-Bold", str(FONT_DIR / "DejaVuSerif-Bold.ttf")))
    pdfmetrics.registerFont(TTFont(SANS, str(FONT_DIR / "DejaVuSans.ttf")))
    pdfmetrics.registerFont(TTFont(f"{SANS}-Bold", str(FONT_DIR / "DejaVuSans-Bold.ttf")))
    pdfmetrics.registerFont(TTFont(MONO, str(FONT_DIR / "DejaVuSansMono.ttf")))
    pdfmetrics.registerFont(TTFont(f"{MONO}-Bold", str(FONT_DIR / "DejaVuSansMono-Bold.ttf")))


def make_styles():
    stylesheet = getSampleStyleSheet()

    body = ParagraphStyle(
        "Body",
        parent=stylesheet["BodyText"],
        fontName=SERIF,
        fontSize=10.5,
        leading=14,
        textColor=colors.HexColor("#1f2933"),
        spaceAfter=6,
        splitLongWords=0,
    )
    body_first = ParagraphStyle("BodyFirst", parent=body, spaceBefore=0)
    bullet = ParagraphStyle(
        "Bullet",
        parent=body,
        leftIndent=16,
        firstLineIndent=-10,
        bulletIndent=4,
        bulletFontName=SANS,
        bulletFontSize=10.5,
        spaceAfter=4,
    )
    ordered = ParagraphStyle(
        "Ordered",
        parent=body,
        leftIndent=20,
        firstLineIndent=-14,
        bulletIndent=2,
        bulletFontName=SANS,
        bulletFontSize=10.5,
        spaceAfter=4,
    )
    quote = ParagraphStyle(
        "Quote",
        parent=body,
        leftIndent=10,
        rightIndent=6,
        textColor=colors.HexColor("#243b53"),
        spaceAfter=0,
        splitLongWords=0,
    )
    table_cell = ParagraphStyle(
        "TableCell",
        parent=body,
        fontSize=9.3,
        leading=12,
        spaceAfter=0,
    )
    table_header = ParagraphStyle(
        "TableHeader",
        parent=table_cell,
        fontName=f"{SANS}-Bold",
        alignment=1,
        textColor=colors.HexColor("#102a43"),
    )
    code_label = ParagraphStyle(
        "CodeLabel",
        parent=body,
        fontName=SANS,
        fontSize=8,
        textColor=colors.HexColor("#486581"),
        spaceAfter=3,
    )

    headings = {}
    heading_specs = {
        1: (18, 22, 16, 10, f"{SANS}-Bold", colors.HexColor("#102a43"), TA_CENTER),
        2: (14.5, 18, 14, 8, f"{SANS}-Bold", colors.HexColor("#102a43"), TA_LEFT),
        3: (12.5, 16, 12, 6, f"{SANS}-Bold", colors.HexColor("#243b53"), TA_LEFT),
        4: (11.2, 14, 10, 4, f"{SANS}-Bold", colors.HexColor("#334e68"), TA_LEFT),
    }
    for level, spec in heading_specs.items():
        font_size, leading, before, after, font_name, color, alignment = spec
        headings[level] = ParagraphStyle(
            f"H{level}",
            parent=stylesheet["Heading1"],
            fontName=font_name,
            fontSize=font_size,
            leading=leading,
            alignment=alignment,
            textColor=color,
            spaceBefore=before,
            spaceAfter=after,
            keepWithNext=True,
            splitLongWords=0,
        )

    return {
        "body": body,
        "body_first": body_first,
        "bullet": bullet,
        "ordered": ordered,
        "quote": quote,
        "table_cell": table_cell,
        "table_header": table_header,
        "code_label": code_label,
        "headings": headings,
    }


def parse_markdown(text: str) -> List[Block]:
    lines = text.splitlines()
    blocks: List[Block] = []
    i = 0

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            i += 1
            continue

        if stripped.startswith("```"):
            lang = stripped[3:].strip()
            i += 1
            code_lines = []
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code_lines.append(lines[i].rstrip("\n"))
                i += 1
            if i < len(lines):
                i += 1
            blocks.append(Block("code", {"lang": lang, "text": "\n".join(code_lines).rstrip()}))
            continue

        if re.fullmatch(r"[-*_]{3,}", stripped):
            blocks.append(Block("hr", {}))
            i += 1
            continue

        heading_match = re.match(r"^(#{1,4})\s+(.*)$", stripped)
        if heading_match:
            blocks.append(
                Block(
                    "heading",
                    {"level": len(heading_match.group(1)), "text": heading_match.group(2).strip()},
                )
            )
            i += 1
            continue

        if stripped.startswith(">"):
            quote_lines = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                content = re.sub(r"^\s*>\s?", "", lines[i].rstrip())
                quote_lines.append(content)
                i += 1
            blocks.append(Block("quote", {"lines": quote_lines}))
            continue

        if is_table_start(lines, i):
            raw_lines = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                raw_lines.append(lines[i].strip())
                i += 1
            blocks.append(Block("table", {"rows": parse_table(raw_lines)}))
            continue

        list_match = re.match(r"^(\s*)([-*]|\d+\.)\s+(.*)$", line)
        if list_match:
            ordered = list_match.group(2).endswith(".") and list_match.group(2)[0].isdigit()
            items = []
            while i < len(lines):
                m = re.match(r"^(\s*)([-*]|\d+\.)\s+(.*)$", lines[i])
                if not m:
                    break
                marker = m.group(2)
                item_lines = [m.group(3).rstrip()]
                i += 1
                while i < len(lines):
                    next_line = lines[i]
                    if not next_line.strip():
                        i += 1
                        break
                    if re.match(r"^(\s*)([-*]|\d+\.)\s+", next_line):
                        break
                    if is_block_start(next_line):
                        break
                    item_lines.append(next_line.strip())
                    i += 1
                items.append({"marker": marker, "lines": item_lines})
            blocks.append(Block("list", {"ordered": ordered, "items": items}))
            continue

        paragraph_lines = [stripped]
        i += 1
        while i < len(lines):
            candidate = lines[i]
            if not candidate.strip() or is_block_start(candidate) or is_table_start(lines, i):
                break
            paragraph_lines.append(candidate.strip())
            i += 1
        blocks.append(Block("paragraph", {"text": " ".join(paragraph_lines).strip()}))

    return blocks


def is_block_start(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return True
    if stripped.startswith(("```", ">", "|")):
        return True
    if re.match(r"^(#{1,4})\s+", stripped):
        return True
    if re.fullmatch(r"[-*_]{3,}", stripped):
        return True
    if re.match(r"^(\s*)([-*]|\d+\.)\s+", line):
        return True
    return False


def is_table_start(lines: List[str], index: int) -> bool:
    if index + 1 >= len(lines):
        return False
    current = lines[index].strip()
    nxt = lines[index + 1].strip()
    if not current.startswith("|") or not nxt.startswith("|"):
        return False
    if TABLE_SEPARATOR_RE.fullmatch(nxt):
        return True
    return False


def parse_table(lines: List[str]) -> List[List[str]]:
    rows = []
    for idx, line in enumerate(lines):
        if idx == 1 and TABLE_SEPARATOR_RE.fullmatch(line):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        rows.append(cells)
    return rows


def inline_markup(text: str) -> str:
    token_re = re.compile(r"(`[^`]+`|\*\*[^*]+\*\*|\*[^*]+\*)")
    pieces = []
    pos = 0
    for match in token_re.finditer(text):
        if match.start() > pos:
            pieces.append(escape(text[pos:match.start()]))
        token = match.group(0)
        if token.startswith("`"):
            code = escape(token[1:-1])
            pieces.append(
                f'<font face="{MONO}" color="#102a43">{code}</font>'
            )
        elif token.startswith("**"):
            pieces.append(f"<b>{escape(token[2:-2])}</b>")
        else:
            pieces.append(f"<i>{escape(token[1:-1])}</i>")
        pos = match.end()
    if pos < len(text):
        pieces.append(escape(text[pos:]))

    markup = "".join(pieces)
    markup = markup.replace("  ", "&nbsp; ")
    return markup


def make_table(rows: List[List[str]], styles, available_width: float):
    col_count = max(len(row) for row in rows)
    normalized = [row + [""] * (col_count - len(row)) for row in rows]

    if col_count == 2:
        estimated = [available_width * 0.32, available_width * 0.68]
        column_styles = [styles["table_cell"]] * col_count
    elif col_count == 3:
        estimated = [available_width * 0.16, available_width * 0.50, available_width * 0.34]
        category_style = ParagraphStyle(
            "TableCellCategory",
            parent=styles["table_cell"],
            fontSize=8.4,
            leading=10.6,
        )
        content_style = ParagraphStyle(
            "TableCellContent",
            parent=styles["table_cell"],
            fontSize=7.8,
            leading=9.8,
        )
        description_style = ParagraphStyle(
            "TableCellDescription",
            parent=styles["table_cell"],
            fontSize=8.4,
            leading=10.6,
        )
        column_styles = [category_style, content_style, description_style]
    else:
        estimated = [available_width / col_count] * col_count
        column_styles = [styles["table_cell"]] * col_count

    table_data = []
    for row_idx, row in enumerate(normalized):
        table_row = []
        for col_idx, cell in enumerate(row):
            markup = inline_markup(cell).replace("</font>, <font", "</font>,<br/><font")
            style = styles["table_header"] if row_idx == 0 else column_styles[col_idx]
            para = Paragraph(markup, style)
            table_row.append(para)
        table_data.append(table_row)

    table = Table(table_data, colWidths=estimated, repeatRows=1, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e9f2f9")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#102a43")),
                ("FONTNAME", (0, 0), (-1, 0), f"{SANS}-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 9.3),
                ("ALIGN", (0, 0), (-1, 0), "CENTER"),
                ("LEADING", (0, 0), (-1, -1), 12),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LINEABOVE", (0, 0), (-1, 0), 0.8, colors.HexColor("#9fb3c8")),
                ("LINEBELOW", (0, 0), (-1, 0), 0.8, colors.HexColor("#9fb3c8")),
                ("INNERGRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#cbd2d9")),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#9fb3c8")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fbfd")]),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    return KeepTogether([table, Spacer(1, 6)])


def strip_md(text: str) -> str:
    return re.sub(r"[*`]", "", text)


def code_font_size(code: str, width: float) -> float:
    lines = code.splitlines() or [""]
    longest = max(lines, key=len)
    for size in (9.0, 8.6, 8.2, 7.8, 7.4):
        if pdfmetrics.stringWidth(longest, MONO, size) <= width - 24:
            return size
    return 7.2


def make_code_block(lang: str, code: str, styles, width: float):
    size = code_font_size(code, width)
    label = lang.upper() if lang else "TEXT"
    code_style = ParagraphStyle(
        "CodeBlock",
        parent=styles["body"],
        fontName=MONO,
        fontSize=size,
        leading=size + 3.4,
        leftIndent=0,
        rightIndent=0,
        spaceAfter=0,
        splitLongWords=0,
    )
    pre = Preformatted(code or " ", code_style)
    box = Table(
        [
            [Paragraph(f"<b>{escape(label)}</b>", styles["code_label"])],
            [pre],
        ],
        colWidths=[width],
        style=TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f7f9fb")),
                ("LINEBEFORE", (0, 0), (0, -1), 2.2, colors.HexColor("#9fb3c8")),
                ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#d9e2ec")),
                ("LEFTPADDING", (0, 0), (-1, -1), 9),
                ("RIGHTPADDING", (0, 0), (-1, -1), 9),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        ),
    )
    return KeepTogether([box, Spacer(1, 8)])


def make_quote(lines: List[str], styles, width: float):
    content = "<br/>".join(inline_markup(line) for line in lines if line)
    para = Paragraph(content, styles["quote"])
    box = Table(
        [[para]],
        colWidths=[width],
        style=TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f4f7fb")),
                ("LINEBEFORE", (0, 0), (0, -1), 2.5, colors.HexColor("#7b8794")),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#d9e2ec")),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        ),
    )
    return KeepTogether([box, Spacer(1, 6)])


def build_story(blocks: List[Block], styles, doc_width: float):
    story = []
    first_paragraph = True

    for block in blocks:
        if block.kind == "heading":
            level = block.data["level"]
            story.append(Paragraph(inline_markup(block.data["text"]), styles["headings"][level]))
            continue

        if block.kind == "paragraph":
            style = styles["body_first"] if first_paragraph else styles["body"]
            story.append(Paragraph(inline_markup(block.data["text"]), style))
            first_paragraph = False
            continue

        if block.kind == "list":
            list_style = styles["ordered"] if block.data["ordered"] else styles["bullet"]
            for idx, item in enumerate(block.data["items"], start=1):
                bullet = f"{idx}." if block.data["ordered"] else "\u2022"
                item_markup = "<br/>".join(inline_markup(line) for line in item["lines"])
                story.append(Paragraph(item_markup, list_style, bulletText=bullet))
            story.append(Spacer(1, 2))
            first_paragraph = False
            continue

        if block.kind == "quote":
            story.append(make_quote(block.data["lines"], styles, doc_width))
            first_paragraph = False
            continue

        if block.kind == "table":
            story.append(make_table(block.data["rows"], styles, doc_width))
            first_paragraph = False
            continue

        if block.kind == "code":
            story.append(make_code_block(block.data["lang"], block.data["text"], styles, doc_width))
            first_paragraph = False
            continue

        if block.kind == "hr":
            story.append(Spacer(1, 3))
            story.append(
                HRFlowable(
                    width="100%",
                    thickness=0.7,
                    color=colors.HexColor("#bcccdc"),
                    spaceAfter=10,
                    spaceBefore=3,
                )
            )
            continue

    return story


def draw_page_footer(canvas, doc) -> None:
    canvas.saveState()
    canvas.setFont(SANS, 9)
    canvas.setFillColor(colors.HexColor("#52667a"))
    footer_y = 8 * mm
    canvas.drawRightString(doc.pagesize[0] - doc.rightMargin, footer_y, f"Page {canvas.getPageNumber()}")
    canvas.restoreState()


def render(input_path: Path, output_path: Path) -> None:
    register_fonts()
    styles = make_styles()
    blocks = parse_markdown(input_path.read_text(encoding="utf-8"))

    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title=input_path.stem,
        author="OpenAI Codex",
    )

    story = build_story(blocks, styles, doc.width)
    doc.build(story, onFirstPage=draw_page_footer, onLaterPages=draw_page_footer)


def main(argv: List[str]) -> int:
    input_path = Path(argv[1]) if len(argv) > 1 else Path("README.md")
    output_path = Path(argv[2]) if len(argv) > 2 else input_path.with_suffix(".pdf")

    if not input_path.exists():
        print(f"Input file not found: {input_path}", file=sys.stderr)
        return 1

    render(input_path, output_path)
    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
