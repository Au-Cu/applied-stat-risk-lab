"""Read the saved XLSX, verify its XML, and create faithful table QA views.

The bundled Windows native PNG renderer crashes on this host. These views read
the exported workbook (not the research JSON), retain its cell dimensions and
explicit styles, and are rendered with Chromium. They are a layout aid, not a
claim of native Excel/WPS application verification.
"""
from __future__ import annotations
import html
import json
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
QA = ROOT / "work/quota-deadline-workbook-20261023"
NS = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
sys.stdout.reconfigure(encoding="utf-8")


def col_number(name):
    result = 0
    for letter in name:
        result = result * 26 + ord(letter) - 64
    return result


def col_name(number):
    result = ""
    while number:
        number, digit = divmod(number - 1, 26)
        result = chr(65 + digit) + result
    return result


def main():
    source = ROOT / "outputs/01a0fff7-637c-7f00-84ac-e158b4fb55ac/应用统计_历年推免后统考名额与报名截止时间_20261023.xlsx"
    archive = ZipFile(source)
    styles = ET.fromstring(archive.read("xl/styles.xml"))
    fonts = styles.find("s:fonts", NS)
    fills = styles.find("s:fills", NS)
    xfs = styles.find("s:cellXfs", NS)
    num_fmts = {int(node.attrib["numFmtId"]): node.attrib["formatCode"] for node in styles.findall("s:numFmts/s:numFmt", NS)}
    strings = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    string_values = ["".join(node.itertext()) for node in strings]
    sheets = {index: ET.fromstring(archive.read(f"xl/worksheets/sheet{index}.xml")) for index in range(1, 4)}
    formula_errors = []
    for index, sheet in sheets.items():
        for cell in sheet.findall(".//s:c", NS):
            if cell.attrib.get("t") == "e":
                formula_errors.append([index, cell.attrib["r"], cell.findtext("s:v", "", NS)])
    if formula_errors:
        raise ValueError(formula_errors)
    pane = sheets[1].find("s:sheetViews/s:sheetView/s:pane", NS)
    assert pane.attrib.get("xSplit") == "2" and pane.attrib.get("ySplit") == "7"
    assert sheets[1].find("s:tableParts", NS) is not None
    table = ET.fromstring(archive.read("xl/tables/table1.xml"))
    assert table.attrib["ref"] == "A7:X49"
    assert table.find("s:autoFilter", NS) is not None
    row_count = len([row for row in sheets[1].findall("s:sheetData/s:row", NS) if 8 <= int(row.attrib["r"]) <= 49])
    assert row_count == 42
    expected = json.loads((ROOT / "output/research/quota_deadline_20261023/quota_deadline_dataset.json").read_text(encoding="utf-8"))
    cells = {cell.attrib["r"]: cell for cell in sheets[1].findall(".//s:c", NS)}

    def value(cell):
        if cell is None:
            return ""
        raw = cell.findtext("s:v", "", NS)
        if cell.attrib.get("t") == "s":
            return string_values[int(raw)]
        if cell.attrib.get("t") == "inlineStr":
            return "".join(cell.find("s:is", NS).itertext())
        return raw

    for index, record in enumerate(expected["records"], start=8):
        assert value(cells[f"A{index}"]) == record["school"]
        assert value(cells[f"Q{index}"]) == record["deadline_timing"]
        assert value(cells[f"J{index}"]) == record["special_scope"]
        assert value(cells[f"T{index}"]) == record["primary_source_url"]
        assert cells[f"P{index}"].attrib.get("t") == "d"
    views = [(1, "A1:J15", "quota-main"), (1, "K7:R17", "quota-dates"),
             (1, "J16:R22", "quota-scope"),
             (2, "A1:E7", "quota-calendar"), (3, "A1:F15", "quota-gaps")]
    for sheet_index, address, filename in views:
        sheet = sheets[sheet_index]
        start_col, start_row, end_col, end_row = re.fullmatch(r"([A-Z]+)(\d+):([A-Z]+)(\d+)", address).groups()
        c1, c2, r1, r2 = col_number(start_col), col_number(end_col), int(start_row), int(end_row)
        widths = {}
        for column in sheet.findall("s:cols/s:col", NS):
            for number in range(int(column.attrib["min"]), int(column.attrib["max"])+1):
                widths[number] = float(column.attrib.get("width", 13)) * 7 + 5
        rows = {int(row.attrib["r"]): row for row in sheet.findall("s:sheetData/s:row", NS)}
        page = ['<!doctype html><meta charset="utf-8"><style>body{margin:14px;background:white;font-family:Arial,"Microsoft YaHei",sans-serif}table{border-collapse:collapse;table-layout:fixed}td{padding:3px 6px;box-sizing:border-box;position:relative;font-size:13.333px;border-bottom:1px solid #edf0f3;vertical-align:middle}.wrap{white-space:normal;overflow-wrap:break-word;overflow:hidden;max-height:100%}.nowrap{white-space:nowrap;overflow:visible}.overflow{position:absolute;top:50%;transform:translateY(-50%);width:max-content;z-index:2} </style><table>']
        page.append('<colgroup>'+''.join(f'<col style="width:{widths.get(number,96):.1f}px">' for number in range(c1,c2+1))+'</colgroup>')
        for row_number in range(r1,r2+1):
            row = rows.get(row_number)
            height = float(row.attrib.get("ht", 15)) * 4 / 3 if row is not None else 20
            row_cells = {cell.attrib["r"]: cell for cell in row} if row is not None else {}
            page.append(f'<tr style="height:{height:.1f}px">')
            for column in range(c1,c2+1):
                cell = row_cells.get(f'{col_name(column)}{row_number}')
                text = value(cell)
                css = []
                wrap = False
                if cell is not None:
                    xf = xfs[int(cell.attrib.get("s", 0))]
                    font = fonts[int(xf.attrib.get("fontId", 0))]
                    size = font.find("s:sz", NS)
                    if size is not None:
                        css.append(f"font-size:{float(size.attrib['val'])*4/3}px")
                    if font.find("s:b", NS) is not None:
                        css.append("font-weight:bold")
                    color = font.find("s:color", NS)
                    if color is not None and color.attrib.get("rgb"):
                        css.append("color:#"+color.attrib["rgb"][-6:])
                    fill = fills[int(xf.attrib.get("fillId", 0))].find("s:patternFill/s:fgColor", NS)
                    if fill is not None and fill.attrib.get("rgb"):
                        css.append("background:#"+fill.attrib["rgb"][-6:])
                    align = xf.find("s:alignment", NS)
                    if align is not None:
                        wrap = align.attrib.get("wrapText") == "1"
                        if align.attrib.get("horizontal"):
                            css.append("text-align:"+align.attrib["horizontal"])
                    if cell.attrib.get("t") == "d" and text:
                        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
                        fmt = num_fmts.get(int(xf.attrib.get("numFmtId", 0)), "")
                        text = dt.strftime("%Y-%m-%d %H:%M" if "hh" in fmt else "%Y-%m-%d")
                    if cell.attrib.get("t") not in {"str", "inlineStr", "s"}:
                        css.append("text-align:right")
                if text == "截止后":
                    css.append("background:#FCE9E6;color:#9B2C2C")
                if "待核" in text and column == 17:
                    css.append("background:#FFF2D5;color:#845B15")
                content_class = "wrap" if wrap else "nowrap"
                if sheet_index == 1 and row_number in (2,3,5) and column == 1:
                    content_class = "overflow"
                page.append(f'<td style="{";".join(css)}"><div class="{content_class}">{html.escape(text)}</div></td>')
            page.append('</tr>')
        page.append('</table>')
        (QA / f'{filename}.html').write_text(''.join(page), encoding='utf-8')
    report = {"saved_workbook_records": row_count, "saved_cached_timing_values": "42/42 matched",
              "date_cells": "native ISO date cells", "filter_range": table.attrib["ref"],
              "frozen_pane": pane.attrib, "formula_errors": formula_errors,
              "preview_backend": "saved XLSX XML/styles to Chromium; native renderer access violation on this host",
              "native_excel_application_checked": False}
    (QA / 'saved_workbook_audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
