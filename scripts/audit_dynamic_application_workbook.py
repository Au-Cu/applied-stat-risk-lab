"""Verify exported formula caches and produce XML/style-based layout QA views.

The native artifact PNG renderer crashes on this Windows host. Saved XML to
Chromium is a layout fallback, not a claim of Excel/WPS application testing.
"""
import html
import json
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from zipfile import ZipFile
from audit_quota_workbook import col_name, col_number, NS

ROOT=Path(__file__).resolve().parents[1]
QA=ROOT/'work/dynamic-applications-workbook-20261024'
SOURCE=ROOT/'outputs/01a16d0a-2259-7f81-83bd-386bf6febbfb/应用统计_985211动态样本报录比_20261024_1630.xlsx'
sys.stdout.reconfigure(encoding='utf-8')


def main():
    expected=json.loads((ROOT/'output/research/dynamic_applications_20261024/dynamic_application_ratios.json').read_text(encoding='utf-8'))
    with ZipFile(SOURCE) as archive:
        styles=ET.fromstring(archive.read('xl/styles.xml'))
        fonts=styles.find('s:fonts',NS);fills=styles.find('s:fills',NS);xfs=styles.find('s:cellXfs',NS)
        formats={int(n.attrib['numFmtId']):n.attrib['formatCode'] for n in styles.findall('s:numFmts/s:numFmt',NS)}
        shared=[''.join(n.itertext()) for n in ET.fromstring(archive.read('xl/sharedStrings.xml'))]
        sheets={i:ET.fromstring(archive.read(f'xl/worksheets/sheet{i}.xml')) for i in range(1,5)}
        def value(c):
            if c is None:return ''
            v=c.findtext('s:v','',NS)
            if c.attrib.get('t')=='s':return shared[int(v)]
            if c.attrib.get('t')=='inlineStr':return ''.join(c.find('s:is',NS).itertext())
            return v
        cell_maps={i:{c.attrib['r']:c for c in sheet.findall('.//s:c',NS)} for i,sheet in sheets.items()}
        errors=[(i,c.attrib['r'],value(c)) for i,cells in cell_maps.items() for c in cells.values() if c.attrib.get('t')=='e']
        assert not errors,errors
        for i,r in enumerate(expected['records'],8):
            assert value(cell_maps[1][f'A{i}'])==r['school']
            assert float(value(cell_maps[1][f'D{i}']))==r['observed_applicants']
            actual=value(cell_maps[1].get(f'G{i}'))
            assert (actual=='' if r['sample_dynamic_ratio'] is None else abs(float(actual)-r['sample_dynamic_ratio'])<1e-9),(i,actual)
            assert cell_maps[1][f'G{i}'].find('s:f',NS) is not None
        tables=[ET.fromstring(archive.read(p)) for p in archive.namelist() if re.fullmatch(r'xl/tables/table\d+.xml',p)]
        assert len(tables)==4
        assert all(t.find('s:autoFilter',NS) is not None for t in tables)
        for sheet in sheets.values():assert sheet.find('s:sheetViews/s:sheetView/s:pane',NS) is not None
        views=[(1,'A1:I15','ratios'),(1,'A23:I35','ratio-details'),(3,'B1:J13','quota-sources'),
               (3,'K4:P12','quota-dates'),(4,'A1:G13','raw'),(2,'A1:H17','coverage')]
        for index,address,filename in views:
            sheet=sheets[index]
            ca,ra,cb,rb=re.fullmatch(r'([A-Z]+)(\d+):([A-Z]+)(\d+)',address).groups()
            c1,c2,r1,r2=col_number(ca),col_number(cb),int(ra),int(rb)
            widths={}
            for c in sheet.findall('s:cols/s:col',NS):
                for n in range(int(c.attrib['min']),int(c.attrib['max'])+1):widths[n]=float(c.attrib.get('width',13))*7+5
            rows={int(r.attrib['r']):r for r in sheet.findall('s:sheetData/s:row',NS)}
            out=['<!doctype html><meta charset="utf-8"><style>body{margin:14px;background:white;font-family:Arial,"Microsoft YaHei",sans-serif}table{border-collapse:collapse;table-layout:fixed}td{padding:3px 6px;box-sizing:border-box;position:relative;border-bottom:1px solid #edf0f3;vertical-align:middle}.wrap{white-space:normal;overflow-wrap:break-word;overflow:hidden}.nowrap{white-space:nowrap;overflow:hidden}.overflow{position:absolute;top:50%;transform:translateY(-50%);width:max-content;z-index:2}</style><table>']
            out.append('<colgroup>'+''.join(f'<col style="width:{widths.get(c,96):.1f}px">' for c in range(c1,c2+1))+'</colgroup>')
            for r in range(r1,r2+1):
                row=rows.get(r);height=float(row.attrib.get('ht',15))*4/3 if row is not None else 20
                out.append(f'<tr style="height:{height:.1f}px">')
                for c in range(c1,c2+1):
                    cell=cell_maps[index].get(f'{col_name(c)}{r}');text=value(cell);css=[];wrap=False
                    if cell is not None:
                        xf=xfs[int(cell.attrib.get('s',0))];font=fonts[int(xf.attrib.get('fontId',0))]
                        size=font.find('s:sz',NS)
                        if size is not None:css.append(f'font-size:{float(size.attrib["val"])*4/3}px')
                        if font.find('s:b',NS) is not None:css.append('font-weight:bold')
                        color=font.find('s:color',NS)
                        if color is not None and color.attrib.get('rgb'):css.append('color:#'+color.attrib['rgb'][-6:])
                        fill=fills[int(xf.attrib.get('fillId',0))].find('s:patternFill/s:fgColor',NS)
                        if fill is not None and fill.attrib.get('rgb'):css.append('background:#'+fill.attrib['rgb'][-6:])
                        align=xf.find('s:alignment',NS)
                        if align is not None:
                            wrap=align.attrib.get('wrapText')=='1'
                            if align.attrib.get('horizontal'):css.append('text-align:'+align.attrib['horizontal'])
                        fmt=formats.get(int(xf.attrib.get('numFmtId',0)),'')
                        if cell.attrib.get('t')=='d' and text:
                            text=datetime.fromisoformat(text.replace('Z','+00:00')).strftime('%Y-%m-%d %H:%M' if 'hh' in fmt else '%Y-%m-%d')
                        elif cell.attrib.get('t') not in {'str','inlineStr','s'} and text:
                            css.append('text-align:right')
                            if fmt=='0.00':text=f'{float(text):.2f}'
                    if index==1 and c==8 and '回退' in text:css.append('background:#FFF2D5;color:#865F20')
                    if index==1 and c==8 and '缺少' in text:css.append('background:#F8E8E5;color:#925044')
                    if index==1 and c==9 and '预计' in text:css.append('background:#FFF2D5')
                    klass='wrap' if wrap else 'nowrap'
                    if index in [1,2,3] and r in [2,3,5] and c==1:klass='overflow'
                    out.append(f'<td style="{";".join(css)}"><div class="{klass}">{html.escape(text)}</div></td>')
                out.append('</tr>')
            out.append('</table>')
            (QA/f'{filename}.html').write_text(''.join(out),encoding='utf-8')
        report=dict(status='passed',saved_target_rows=108,saved_ratio_caches=expected['summary']['ratio_records'],
                    filter_tables=4,sheets_with_frozen_panes=4,formula_errors=errors,
                    layout_backend='Saved XLSX XML/styles to Chromium; native artifact PNG renderer failed on this host',
                    native_excel_application_checked=False)
        (QA/'saved-workbook-audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
