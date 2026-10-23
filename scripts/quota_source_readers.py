"""Read official aggregate tables without guessing missing rows or columns.

The functions return transcriptions, not accepted statistical observations.
Original bytes and hashes are retained by the collector. No workbook is written.
"""
from __future__ import annotations

import io
import re
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree as ET

TARGET = re.compile(r'应\s*用\s*统\s*计|(?<!\d)025200(?!\d)')
NS = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}


class SpanTableParser(HTMLParser):
    """Expand rowspan/colspan while keeping tables independent.

    Nested tables are kept as separate grids; their text is not injected into a
    parent cell. The original unexpanded tables remain in capture metadata too.
    """
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.tables = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'table':
            self.stack.append({'rows': [], 'pending': {}, 'row': None, 'cell': None})
        elif self.stack and tag == 'tr':
            self.stack[-1]['row'] = []
        elif self.stack and tag in ('td', 'th'):
            try:
                span = (max(1, min(500, int(attrs.get('rowspan', 1)))),
                        max(1, min(200, int(attrs.get('colspan', 1)))))
            except ValueError:
                span = (1, 1)
            self.stack[-1]['cell'] = {'text': '', 'span': span}
        elif self.stack and tag in ('br', 'p', 'div') and self.stack[-1]['cell']:
            self.stack[-1]['cell']['text'] += ' '

    def handle_data(self, data):
        if self.stack and self.stack[-1]['cell'] is not None:
            self.stack[-1]['cell']['text'] += data

    def handle_endtag(self, tag):
        if not self.stack:
            return
        state = self.stack[-1]
        if tag in ('td', 'th') and state['cell'] is not None:
            if state['row'] is not None:
                state['row'].append(state['cell'])
            state['cell'] = None
        elif tag == 'tr' and state['row'] is not None:
            grid = {}
            for col, (text, remaining) in list(state['pending'].items()):
                grid[col] = text
                if remaining <= 1:
                    del state['pending'][col]
                else:
                    state['pending'][col] = (text, remaining - 1)
            col = 0
            for cell in state['row']:
                while col in grid:
                    col += 1
                text = re.sub(r'\s+', ' ', cell['text']).strip()
                rowspan, colspan = cell['span']
                for offset in range(colspan):
                    grid[col + offset] = text
                    if rowspan > 1:
                        state['pending'][col + offset] = (text, rowspan - 1)
                col += colspan
            if grid:
                state['rows'].append([grid.get(i, '') for i in range(max(grid) + 1)])
            state['row'] = None
        elif tag == 'table':
            self.tables.append(self.stack.pop()['rows'])


def html_grids(document):
    parser = SpanTableParser()
    parser.feed(document)
    return parser.tables


def _column_index(reference):
    result = 0
    for letter in re.match(r'[A-Z]+', reference)[0]:
        result = result * 26 + ord(letter) - 64
    return result - 1


def read_xlsx_bytes(raw):
    """Read cached cells only; do not execute external links or formulas."""
    tables = []
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        strings = []
        if 'xl/sharedStrings.xml' in archive.namelist():
            strings = [''.join(n.itertext()) for n in ET.fromstring(archive.read('xl/sharedStrings.xml')).findall('s:si', NS)]
        for name in sorted(archive.namelist()):
            if not re.fullmatch(r'xl/worksheets/sheet\d+\.xml', name):
                continue
            root = ET.fromstring(archive.read(name))
            rows = []
            for node in root.findall('s:sheetData/s:row', NS):
                row = {}
                for cell in node.findall('s:c', NS):
                    reference = cell.get('r', '')
                    if not re.match(r'[A-Z]+', reference):
                        continue
                    value_node = cell.find('s:v', NS)
                    value = value_node.text if value_node is not None else ''
                    if cell.get('t') == 's' and value:
                        value = strings[int(value)]
                    elif cell.get('t') == 'inlineStr':
                        value = ''.join(cell.find('s:is', NS).itertext())
                    row[_column_index(reference)] = value or ''
                if row:
                    rows.append([row.get(i, '') for i in range(max(row) + 1)])
            tables.append({'sheet': name, 'rows': rows})
    return tables


def read_xls_bytes(raw):
    """Optional xlrd reader; imported only for legacy binary workbooks."""
    import xlrd
    workbook = xlrd.open_workbook(file_contents=raw, on_demand=True)
    result = []
    try:
        for sheet in workbook.sheets():
            rows = []
            for idx in range(sheet.nrows):
                values = sheet.row_values(idx)
                rows.append([str(int(v)) if isinstance(v, float) and v.is_integer() else str(v) for v in values])
            result.append({'sheet': sheet.name, 'rows': rows})
    finally:
        workbook.release_resources()
    return result


def position_rows(page, tolerance=2.0):
    """Rebuild visible PDF lines from character coordinates, without OCR.

    The caller owns the PDFium lock and page lifetime. This recovers split PDF
    table rows but does not infer the meaning of any numerical column.
    """
    text_page = page.get_textpage()
    chars = []
    try:
        for idx in range(text_page.count_chars()):
            text = text_page.get_text_range(index=idx, count=1)
            if not text or text.isspace() or text in ('\x00', '\ufffe'):
                continue
            left, bottom, right, top = text_page.get_charbox(idx)
            chars.append((-(bottom + top) / 2, left, right, text, bottom, top))
    finally:
        text_page.close()
    lines = []
    for char in sorted(chars):
        if not lines or abs(lines[-1]['y'] - char[0]) > tolerance:
            lines.append({'y': char[0], 'chars': [char]})
        else:
            lines[-1]['chars'].append(char)
    result = []
    for line in lines:
        ordered = sorted(line['chars'], key=lambda x: x[1])
        parts = []
        previous_right = None
        for _, left, right, text, _, _ in ordered:
            if previous_right is not None and left - previous_right > 7:
                parts.append(' | ')
            elif previous_right is not None and left - previous_right > 2.5:
                parts.append(' ')
            parts.append(text)
            previous_right = max(previous_right or right, right)
        result.append({'y': round(-line['y'], 2), 'text': ''.join(parts)})
    return result
