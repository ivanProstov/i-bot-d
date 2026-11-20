import math

import pytest

from ibotd.averages import moving_average
from ibotd.plugins.ma_cross import MaCross


def params(**overrides):
    base = {
        'fastType': 'SMA',
        'fastPeriod': 2,
        'slowType': 'SMA',
        'slowPeriod': 3,
        'offsetPct': 0,
        'lifetimeBars': 5,
        'takeProfitPct': 1,
        'stopLossPct': 3.3,
        'minSignalGapBars': 0,
        'direction': 'both',
        'crossMode': 'direct',
        'exitMode': 'tp_sl',
        'leverage': 1,
        'orderNotional': 1000,
        'entryOnClose': True,
    }
    base.update(overrides)
    return base


def ctx(index, close=100, position=None):
    return {
        'index': index,
        'openTime': 0,
        'open': close,
        'high': close,
        'low': close,
        'close': close,
        'volume': 1,
        'positionSide': position,
        'positionEntry': close if position else 0,
        'pending': False,
    }


def test_direct_and_reverse_cross_choose_side_and_limit():
    plugin = MaCross()
    prepared = {'cross': [0, 1, -1]}
    memory = plugin.create_memory()
    up = plugin.on_bar(prepared, ctx(1, 100), params(), memory)
    assert up['type'] == 'limit_entry'
    assert up['side'] == 'long'
    assert up['price'] == 100
    assert up['takePrice'] == pytest.approx(101)
    assert up['stopPrice'] == pytest.approx(96.7)
    assert memory['lastSignal'] == 1

    memory = plugin.create_memory()
    down = plugin.on_bar(prepared, ctx(2, 100), params(), memory)
    assert down['side'] == 'short'
    assert down['price'] == 100

    memory = plugin.create_memory()
    reverse = plugin.on_bar(prepared, ctx(1, 100), params(crossMode='reverse'), memory)
    assert reverse['side'] == 'short'

    offset = plugin.on_bar(prepared, ctx(1, 100), params(offsetPct=0.9), plugin.create_memory())
    assert offset['price'] == pytest.approx(99.1)
    assert offset['lifetimeBars'] == 5


def test_direction_filter_does_not_spend_the_gap():
    plugin = MaCross()
    prepared = {'cross': [0, 1, -1]}
    memory = plugin.create_memory()
    assert plugin.on_bar(prepared, ctx(1), params(direction='short', minSignalGapBars=5), memory) is None
    assert memory['lastSignal'] == -1_000_000_000
    taken = plugin.on_bar(prepared, ctx(2), params(direction='short', minSignalGapBars=5), memory)
    assert taken['side'] == 'short'


def test_gap_blocks_the_next_taken_signals():
    plugin = MaCross()
    prepared = {'cross': [0, 1, 1, 1, 1]}
    memory = plugin.create_memory()
    rule = params(minSignalGapBars=2)
    assert plugin.on_bar(prepared, ctx(1), rule, memory)['side'] == 'long'
    assert plugin.on_bar(prepared, ctx(2), rule, memory) is None
    assert plugin.on_bar(prepared, ctx(3), rule, memory) is None
    assert plugin.on_bar(prepared, ctx(4), rule, memory)['side'] == 'long'


def test_flip_and_open_position_block():
    plugin = MaCross()
    prepared = {'cross': [0, -1]}
    held = params(exitMode='tp_sl')
    assert plugin.on_bar(prepared, ctx(1, position='long'), held, plugin.create_memory()) is None
    flipped = plugin.on_bar(prepared, ctx(1, 110, position='long'), params(exitMode='flip_on_cross'), plugin.create_memory())
    assert flipped['type'] == 'flip'
    assert flipped['side'] == 'short'
    assert flipped['price'] == 110
    assert flipped['takePrice'] is None
    assert flipped['stopPrice'] == pytest.approx(110 * 1.033)


def test_prepare_marks_cross_on_close_and_rejects_unknown_average():
    plugin = MaCross()
    series = {
        'close': [10, 10, 10, 11, 12],
        'volume': [1, 1, 1, 1, 1],
    }
    prepared = plugin.prepare(series, params())
    assert prepared['cross'] == [0, 0, 0, 1, 0]
    with pytest.raises(ValueError, match='тип средней'):
        plugin.prepare(series, params(fastType='RMA'))


def test_constant_prices_match_for_every_average():
    close = [5, 5, 5, 5]
    volume = [2, 2, 2, 2]
    for kind in ('SMA', 'EMA', 'SMMA', 'WMA', 'VWMA'):
        values = moving_average(kind, close, volume, 3)
        assert values[2] == 5
        assert math.isnan(values[0])
    with pytest.raises(ValueError):
        moving_average('RMA', close, volume, 3)
