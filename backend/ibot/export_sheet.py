from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

PARAM_COLUMNS = [
    ('fastType', 'fastType'), ('fastPeriod', 'fastPeriod'), ('slowType', 'slowType'), ('slowPeriod', 'slowPeriod'),
    ('offsetPct', 'offsetPct'), ('lifetimeBars', 'orderLife'), ('takeProfitPct', 'takeProfitPct'), ('stopLossPct', 'stopLossPct'),
    ('minSignalGapBars', 'minSignalGapBars'), ('direction', 'direction'), ('crossMode', 'crossMode'), ('exitMode', 'exitMode'),
]
METRIC_COLUMNS = [
    ('Profit', 'Profit'), ('ProfitFact', 'ProfitFact'), ('Winrate', 'Winrate'), ('Trades', 'Trades'),
    ('MaxDraw', 'MaxDraw'), ('MaxDrawPct', 'MaxDrawPct'), ('MaxDrawAt', 'MaxDrawAt'),
    ('WorstTrade', 'WorstTrade'), ('WorstTradeAt', 'WorstTradeAt'), ('WorstOpen', 'WorstOpen'), ('WorstOpenAt', 'WorstOpenAt'),
    ('positiveMonthShare', 'plusMonthsPct'), ('bestMonthShare', 'bestMonthPct'),
]


def build_workbook(rows, month_keys, colors):
    book = Workbook()
    sheet = book.active
    sheet.title = 'прогон'
    headers = ['status', 'reason', *[title for _key, title in PARAM_COLUMNS], *[title for _key, title in METRIC_COLUMNS], *month_keys]
    sheet.append(headers)
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    for row in rows:
        values = [row['status'], row['reason']]
        params = row['params']
        for key, _title in PARAM_COLUMNS:
            value = params.get(key)
            values.append(value if isinstance(value, (int, float, str)) or value is None else str(value))
        for key, _title in METRIC_COLUMNS:
            values.append(row.get(key))
        values.extend(row['months'])
        sheet.append(values)
        added = sheet.max_row
        _paint(sheet.cell(added, len(PARAM_COLUMNS) + 3), row.get('Profit'), colors.get('profit33'), colors.get('profit66'))
        _paint(sheet.cell(added, len(PARAM_COLUMNS) + 4), row.get('ProfitFact'), colors.get('pf33'), colors.get('pf66'))
    sheet.freeze_panes = 'A2'
    buffer = BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def _paint(cell, value, low, high):
    if value is None or low is None or high is None:
        return
    color = 'C6EFCE' if value >= high else 'F4C7C3' if value <= low else 'FFF2CC'
    cell.fill = PatternFill('solid', fgColor=color)
