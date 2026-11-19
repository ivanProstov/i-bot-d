import re
from io import BytesIO
from pathlib import Path

import pytest
from openpyxl import load_workbook

from ibot.engine import get_plugin as engine_get_plugin
from ibot.engine import simulate as engine_simulate
from ibot.export_sheet import build_workbook
from ibotd.accounting import simulate
from ibotd.registry import get_plugin
from ibotd.result import PARAM_COLUMNS, public_result


def test_engine_uses_shared_registry_and_accounting():
    assert engine_simulate is simulate
    assert engine_get_plugin is get_plugin
    source = Path('backend/ibot/engine.py').read_text()
    assert 'ma-cross' not in source
    assert 'if strategy' not in source
    package = Path('backend/ibotd')
    for path in package.rglob('*.py'):
        text = path.read_text()
        assert re.search(r'(?:import|from) ibot(?:\.|\s)', text) is None


def test_run_input_rejects_plugin_that_is_only_in_the_catalog():
    from ibot.validate import parse_run_input, summary_for

    axes = [
        {'key': 'fastType', 'kind': 'enum', 'values': ['SMA']},
        {'key': 'fastPeriod', 'kind': 'number', 'from': 10, 'to': 12, 'step': 2},
        {'key': 'slowType', 'kind': 'enum', 'values': ['EMA']},
        {'key': 'slowPeriod', 'kind': 'number', 'from': 30, 'to': 30, 'step': 5},
        {'key': 'offsetPct', 'kind': 'number', 'from': 0, 'to': 0, 'step': 0.1},
        {'key': 'lifetimeBars', 'kind': 'number', 'from': 1, 'to': 1, 'step': 1},
        {'key': 'takeProfitPct', 'kind': 'number', 'from': 1, 'to': 1, 'step': 0.5},
        {'key': 'stopLossPct', 'kind': 'number', 'from': 1, 'to': 1, 'step': 0.5},
        {'key': 'minSignalGapBars', 'kind': 'number', 'from': 0, 'to': 0, 'step': 1},
        {'key': 'direction', 'kind': 'enum', 'values': ['both']},
        {'key': 'crossMode', 'kind': 'enum', 'values': ['direct']},
        {'key': 'exitMode', 'kind': 'enum', 'values': ['tp_sl']},
    ]
    body = {
        'strategyId': 'ma-cross',
        'axes': axes,
        'deposit': 1000,
        'earlyStopPct': 25,
        'orderNotional': 1000,
        'leverage': 1,
    }
    parsed = parse_run_input(body, 0.001, 0.001)
    assert parsed['strategyId'] == 'ma-cross'
    assert summary_for(body)['total'] == 2
    body['strategyId'] = 'bollinger'
    with pytest.raises(ValueError, match='в реестре нет'):
        parse_run_input(body, None, None)
    body['strategyId'] = 'ma-cross'
    body['axes'] = [*axes, {'key': 'leverage', 'kind': 'number', 'from': 1, 'to': 1, 'step': 1}]
    with pytest.raises(ValueError, match='нельзя перебирать'):
        parse_run_input(body, None, None)


def test_result_row_names_order_life_after_lifetime():
    row = public_result(
        'row-1',
        'done',
        None,
        {'lifetimeBars': 5, 'fastType': 'SMA'},
        {
            'profit': 10,
            'profit_fact': None,
            'winrate': 33,
            'trades': 2,
            'max_draw': 4,
            'max_draw_pct': 1,
            'max_draw_at': '2020-03-01',
            'worst_trade': -2,
            'worst_trade_at': '2020-04-01',
            'worst_open': -3,
            'worst_open_at': '2020-05-01',
            'positive_month_share': 50,
            'best_month_share': 80,
        },
        ['2020-01', '2020-02'],
        [1.5],
    )
    assert row['Profit'] == 10
    assert row['ProfitFact'] is None
    assert row['MaxDraw'] == 4
    assert row['months'] == [{'month': '2020-01', 'profit': 1.5}, {'month': '2020-02', 'profit': None}]
    assert ('lifetimeBars', 'orderLife') in PARAM_COLUMNS
    sheet = load_workbook(BytesIO(build_workbook([
        {
            'status': 'done',
            'reason': None,
            'params': {'lifetimeBars': 5},
            'Profit': 10,
            'ProfitFact': None,
            'Winrate': None,
            'Trades': 1,
            'MaxDraw': 0,
            'MaxDrawPct': 0,
            'MaxDrawAt': None,
            'WorstTrade': None,
            'WorstTradeAt': None,
            'WorstOpen': None,
            'WorstOpenAt': None,
            'positiveMonthShare': None,
            'bestMonthShare': None,
            'months': [1],
        },
    ], ['2020-01'], {'profit33': None, 'profit66': None, 'pf33': None, 'pf66': None})))
    headers = [cell.value for cell in next(sheet.active.iter_rows(max_row=1))]
    assert 'orderLife' in headers
    assert 'lifetimeBars' not in headers
