from datetime import datetime, timezone

import pytest

from ibotd.accounting import simulate
from ibotd.lot import floor_to_step
from ibotd.plugins.ma_cross import MaCross


def ms(year, month, day):
    return int(datetime(year, month, day, tzinfo=timezone.utc).timestamp() * 1000)


def candles(rows):
    data = {key: [] for key in ('openTime', 'open', 'high', 'low', 'close', 'volume')}
    for open_time, close, high, low in rows:
        data['openTime'].append(open_time)
        data['open'].append(close)
        data['high'].append(high)
        data['low'].append(low)
        data['close'].append(close)
        data['volume'].append(1)
    return data


def settings(**overrides):
    base = {
        'deposit': 1000,
        'earlyStopPct': 25,
        'orderNotional': 1000,
        'leverage': 1,
        'lotStep': None,
        'minQty': None,
    }
    base.update(overrides)
    return base


class Scripted:
    series_params = ()

    def __init__(self, actions):
        self.actions = actions

    def create_memory(self):
        return {}

    def prepare(self, series, params):
        return None

    def on_bar(self, prepared, ctx, params, memory):
        return self.actions.get(ctx['index'])


def test_floor_to_step_and_blocked_min_qty():
    assert floor_to_step(10, None) == 10
    assert floor_to_step(10, 3) == 9
    enter = {'type': 'limit_entry', 'side': 'long', 'price': 100, 'lifetimeBars': 1, 'stopPrice': 1, 'takePrice': 110}
    series = candles([(ms(2020, 1, 1), 100, 100, 100), (ms(2020, 1, 2), 100, 110, 100)])
    sized = simulate(Scripted({0: enter}), series, {}, settings(lotStep=3))
    assert sized['trades'] == 1
    assert sized['profit'] == pytest.approx(90)
    blocked = simulate(Scripted({0: enter}), series, {}, settings(minQty=11))
    assert blocked['trades'] == 0
    assert blocked['profit'] == 0


def test_stop_wins_when_stop_and_take_share_a_bar_and_profit_fact():
    entry = {'type': 'limit_entry', 'side': 'long', 'price': 100, 'lifetimeBars': 1, 'stopPrice': 95, 'takePrice': 110}
    again = {'type': 'limit_entry', 'side': 'long', 'price': 100, 'lifetimeBars': 1, 'stopPrice': 95, 'takePrice': 110}
    series = candles([
        (ms(2020, 1, 1), 100, 100, 100),
        (ms(2020, 1, 2), 100, 120, 90),
        (ms(2020, 1, 3), 100, 100, 100),
        (ms(2020, 1, 4), 100, 110, 100),
    ])
    result = simulate(Scripted({0: entry, 2: again}), series, {}, settings(earlyStopPct=90))
    assert result['trades'] == 2
    assert result['profit'] == pytest.approx(50)
    assert result['profitFact'] == pytest.approx(2)
    assert result['winrate'] == pytest.approx(50)


def test_early_stop_keeps_the_row_and_blanks_later_months():
    entry = {'type': 'limit_entry', 'side': 'long', 'price': 100, 'lifetimeBars': 1, 'stopPrice': 1, 'takePrice': 1000}
    series = candles([
        (ms(2020, 1, 15), 100, 100, 100),
        (ms(2020, 1, 16), 80, 100, 75),
        (ms(2020, 2, 15), 80, 80, 80),
    ])
    result = simulate(Scripted({0: entry}), series, {}, settings())
    assert result['status'] == 'stopped'
    assert result['reason'].startswith('просадка от стартового депозита')
    assert result['months'][0]['month'] == '2020-01'
    assert result['months'][1]['month'] == '2020-02'
    assert result['months'][1]['profit'] is None


def test_cancel_entry_and_flip_use_plugin_actions():
    pending = {'type': 'limit_entry', 'side': 'long', 'price': 90, 'lifetimeBars': 5, 'stopPrice': 1, 'takePrice': 1000}
    series = candles([
        (ms(2020, 1, 1), 100, 100, 100),
        (ms(2020, 1, 2), 100, 100, 95),
        (ms(2020, 1, 3), 100, 100, 90),
    ])
    cancelled = simulate(Scripted({0: pending, 1: {'type': 'cancel_entry'}}), series, {}, settings())
    assert cancelled['trades'] == 0

    entry = {'type': 'limit_entry', 'side': 'long', 'price': 100, 'lifetimeBars': 1, 'stopPrice': 1, 'takePrice': 1000}
    flip = {'type': 'flip', 'side': 'short', 'price': 110, 'stopPrice': 1000, 'takePrice': None}
    flipped = candles([
        (ms(2020, 1, 1), 100, 100, 100),
        (ms(2020, 1, 2), 100, 100, 100),
        (ms(2020, 1, 3), 110, 110, 110),
    ])
    result = simulate(Scripted({0: entry, 2: flip}), flipped, {}, settings(earlyStopPct=90))
    assert result['trades'] == 1
    assert result['profit'] == pytest.approx(100)
    assert result['profitFact'] is None


def test_ma_cross_run_takes_profit_without_naming_the_strategy_inside_accounting():
    plugin = MaCross()
    series = candles([
        (ms(2020, 1, 1), 10, 10, 10),
        (ms(2020, 1, 2), 10, 10, 10),
        (ms(2020, 1, 3), 10, 10, 10),
        (ms(2020, 1, 4), 11, 11, 11),
        (ms(2020, 1, 5), 11.5, 12, 11),
    ])
    params = {
        'fastType': 'SMA',
        'fastPeriod': 2,
        'slowType': 'SMA',
        'slowPeriod': 3,
        'offsetPct': 0,
        'lifetimeBars': 1,
        'takeProfitPct': 1,
        'stopLossPct': 1,
        'minSignalGapBars': 0,
        'direction': 'both',
        'crossMode': 'direct',
        'exitMode': 'tp_sl',
        'leverage': 1,
        'orderNotional': 1000,
        'entryOnClose': True,
    }
    result = simulate(plugin, series, params, settings(earlyStopPct=90))
    assert result['status'] == 'done'
    assert result['trades'] == 1
    assert result['profit'] == pytest.approx(10)
    assert result['winrate'] == pytest.approx(100)
    assert result['profitFact'] is None

    missed = dict(params, offsetPct=10)
    waiting = simulate(plugin, series, missed, settings(earlyStopPct=90))
    assert waiting['trades'] == 0
