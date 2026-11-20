import pytest

from ibotd.contract import build_bot_config, metrics_snapshot, normalize_params
from ibotd.registry import get_plugin


def ma_params(**overrides):
    params = {
        'fastType': 'SMA',
        'fastPeriod': 10,
        'slowType': 'EMA',
        'slowPeriod': 30,
        'offsetPct': 0,
        'lifetimeBars': 5,
        'takeProfitPct': 9.9,
        'stopLossPct': 3.3,
        'minSignalGapBars': 0,
        'leverage': 1,
        'orderNotional': 1000,
        'entryOnClose': True,
        'direction': 'both',
        'crossMode': 'direct',
        'exitMode': 'tp_sl',
    }
    params.update(overrides)
    return params


def test_config_carries_strategy_and_ma_cross_params():
    config = build_bot_config(
        strategy_id='ma-cross',
        params=ma_params(),
        run_id='run-1',
        symbol='btcusdt',
        interval='5m',
        lot_step=0.001,
    )
    assert config['strategyId'] == 'ma-cross'
    assert config['runId'] == 'run-1'
    assert config['symbol'] == 'BTCUSDT'
    assert config['market'] == 'binance-usd-m'
    assert config['interval'] == '5m'
    assert config['lotStep'] == 0.001
    assert list(config['params']) == [item['key'] for item in get_plugin('ma-cross').params]
    assert config['params']['entryOnClose'] is True
    assert config['params']['fastPeriod'] == 10
    assert config['params']['takeProfitPct'] == 9.9
    assert 'fastType' not in config
    assert 'use_geoswing' not in config['params']


def test_config_rejects_unknown_strategy_param_and_market():
    with pytest.raises(ValueError, match='не принадлежит'):
        build_bot_config(
            strategy_id='ma-cross',
            params=ma_params(use_geoswing=True),
            run_id='run-1',
            symbol='BTCUSDT',
            interval='1m',
            lot_step=None,
        )
    with pytest.raises(ValueError, match='в реестре нет'):
        build_bot_config(
            strategy_id='bollinger',
            params=ma_params(),
            run_id='run-1',
            symbol='BTCUSDT',
            interval='1m',
            lot_step=None,
        )
    with pytest.raises(ValueError, match='таймфрейм'):
        build_bot_config(
            strategy_id='ma-cross',
            params=ma_params(),
            run_id='run-1',
            symbol='BTCUSDT',
            interval='2m',
            lot_step=None,
        )
    with pytest.raises(ValueError, match='символ'):
        build_bot_config(
            strategy_id='ma-cross',
            params=ma_params(),
            run_id='run-1',
            symbol='BTC-USDT',
            interval='1m',
            lot_step=None,
        )


def test_entry_on_close_stays_on():
    plugin = get_plugin('ma-cross')
    with pytest.raises(ValueError, match='entryOnClose'):
        normalize_params(plugin, ma_params(entryOnClose=False))
    with pytest.raises(ValueError, match='orderNotional'):
        normalize_params(plugin, ma_params(orderNotional=0))


def test_metrics_snapshot_keeps_empty_profit_fact():
    snapshot = metrics_snapshot(
        profit=10,
        profit_fact=None,
        winrate=None,
        trades=0,
        max_draw=0,
        history_from='2020-01-01',
        history_to='2024-01-01',
        early_stop_pct=25,
        run_id='run-1',
    )
    assert snapshot == {
        'Profit': 10,
        'ProfitFact': None,
        'Winrate': None,
        'Trades': 0,
        'MaxDraw': 0,
        'historyFrom': '2020-01-01',
        'historyTo': '2024-01-01',
        'earlyStopPct': 25,
        'runId': 'run-1',
    }
    with pytest.raises(ValueError):
        metrics_snapshot(
            profit=None,
            profit_fact=None,
            winrate=None,
            trades=0,
            max_draw=0,
            history_from='2020-01-01',
            history_to='2024-01-01',
            early_stop_pct=25,
            run_id='run-1',
        )
