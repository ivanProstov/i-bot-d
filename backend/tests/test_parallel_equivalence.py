"""Один и тот же ряд: однопоточный проход и параллельный совпадают до цента.

Ряд синтетический, сеть не нужна. Очередь интерфейса зовёт только параллельный проход.
"""

import json
import logging
import math
import uuid
from datetime import datetime, timezone

import pytest

from ibot.db import connect, now_iso
from ibot.engine import claim_next_run, estimate_run, execute_run, resume_interrupted
from ibot.parallel import (
    DB_BATCH,
    MaCache,
    available_cores,
    default_worker_count,
    field_worker_max,
    job_size,
    lower_priority,
    worker_count,
)
from ibot.series_file import save_series
from ibot.server import create_run
from ibot.validate import parse_run_input, to_settings
from ibotd.averages import moving_average

BARS = 20_000
STEP_MS = 300_000

AXES = [
    {'key': 'fastType', 'kind': 'enum', 'values': ['SMA', 'EMA']},
    {'key': 'fastPeriod', 'kind': 'number', 'from': 8, 'to': 12, 'step': 4},
    {'key': 'slowType', 'kind': 'enum', 'values': ['SMA', 'EMA']},
    {'key': 'slowPeriod', 'kind': 'number', 'from': 21, 'to': 21, 'step': 1},
    {'key': 'offsetPct', 'kind': 'number', 'from': 0, 'to': 0, 'step': 0.1},
    {'key': 'lifetimeBars', 'kind': 'number', 'from': 4, 'to': 4, 'step': 1},
    {'key': 'takeProfitPct', 'kind': 'number', 'from': 3, 'to': 3, 'step': 0.5},
    {'key': 'stopLossPct', 'kind': 'number', 'from': 2, 'to': 50, 'step': 48},
    {'key': 'minSignalGapBars', 'kind': 'number', 'from': 0, 'to': 0, 'step': 1},
    {'key': 'direction', 'kind': 'enum', 'values': ['long', 'short', 'both']},
    {'key': 'crossMode', 'kind': 'enum', 'values': ['direct']},
    {'key': 'exitMode', 'kind': 'enum', 'values': ['tp_sl', 'flip_on_cross']},
]

FLOAT_FIELDS = (
    'profit', 'profit_fact', 'winrate', 'max_draw', 'max_draw_pct',
    'worst_trade', 'worst_open', 'positive_month_share', 'best_month_share',
)
EXACT_FIELDS = (
    'status', 'reason', 'trades', 'max_draw_at', 'worst_trade_at', 'worst_open_at',
)


def build_series(bars=BARS):
    start = int(datetime(2020, 1, 15, tzinfo=timezone.utc).timestamp() * 1000)
    close = []
    crash_at = int(bars * 0.72)
    for index in range(bars):
        wave = math.sin(index / 18.0) * 3.0
        trend = 0.008 * index
        price = 100.0 + trend + wave
        if index >= crash_at:
            price = price * 0.55
        close.append(price)
    open_ = [close[0]] + close[:-1]
    high = [max(left, right) * 1.002 for left, right in zip(open_, close)]
    low = [max(0.5, min(left, right) * 0.998) for left, right in zip(open_, close)]
    return {
        'openTime': [start + index * STEP_MS for index in range(bars)],
        'open': open_,
        'high': high,
        'low': low,
        'close': close,
        'volume': [1000.0 + (index % 5) for index in range(bars)],
    }


def run_body(series_id):
    return {
        'seriesId': series_id,
        'from': '2020-01-01',
        'to': '2020-04-30',
        'strategyId': 'ma-cross',
        'axes': AXES,
        'deposit': 1000,
        'earlyStopPct': 25,
        'orderNotional': 1000,
        'leverage': 1,
        'constraintEnabled': True,
    }


def rows_of(db, run_id):
    return db.execute(
        'SELECT * FROM result_rows WHERE run_id = ? ORDER BY ordinal',
        (run_id,),
    ).fetchall()


def assert_cents(left, right, label):
    if left is None or right is None:
        assert left is None and right is None, label
        return
    assert abs(float(left) - float(right)) < 0.01, (label, left, right)


def assert_same_rows(left_rows, right_rows):
    assert len(left_rows) == len(right_rows)
    assert left_rows
    for index, (left, right) in enumerate(zip(left_rows, right_rows)):
        assert left['ordinal'] == index
        assert right['ordinal'] == index
        for field in EXACT_FIELDS:
            assert left[field] == right[field], (index, field, left[field], right[field])
        for field in FLOAT_FIELDS:
            assert_cents(left[field], right[field], f'{index} {field}')
        assert json.loads(left['params_json']) == json.loads(right['params_json'])
        left_months = json.loads(left['months_json'])
        right_months = json.loads(right['months_json'])
        assert len(left_months) == len(right_months)
        for month_index, (left_month, right_month) in enumerate(zip(left_months, right_months)):
            assert_cents(left_month, right_month, f'{index} month {month_index}')


def assert_grid_covered(rows):
    params = [json.loads(row['params_json']) for row in rows]
    assert {item['fastType'] for item in params} == {'SMA', 'EMA'}
    assert {item['slowType'] for item in params} == {'SMA', 'EMA'}
    assert {item['direction'] for item in params} == {'long', 'short', 'both'}
    assert {item['exitMode'] for item in params} == {'tp_sl', 'flip_on_cross'}
    assert {row['status'] for row in rows} == {'done', 'stopped'}
    stopped = [row for row in rows if row['status'] == 'stopped']
    assert stopped
    assert all(row['reason'] and row['reason'].startswith('просадка от стартового депозита') for row in stopped)
    assert any(None in json.loads(row['months_json']) for row in stopped)
    assert any(row['status'] == 'done' and row['trades'] > 0 for row in rows)


def test_ma_cache_keeps_every_pair_not_only_the_last():
    close = [float(index) for index in range(40)]
    volume = [1.0] * len(close)
    cache = MaCache()
    sma = cache('SMA', close, volume, 4)
    ema = cache('EMA', close, volume, 8)
    assert cache('SMA', close, volume, 4) is sma
    assert cache('EMA', close, volume, 8) is ema
    assert sma == moving_average('SMA', close, volume, 4)
    assert ema == moving_average('EMA', close, volume, 8)


def test_worker_count_resolution(monkeypatch, caplog):
    monkeypatch.setattr('ibot.parallel.available_cores', lambda: 8)
    monkeypatch.delenv('IBOT_WORKERS', raising=False)
    assert default_worker_count() == 4
    assert field_worker_max() == 7
    assert worker_count() == 4

    monkeypatch.setenv('IBOT_WORKERS', '3')
    assert worker_count() == 3
    assert worker_count(None) == 3
    assert worker_count('') == 3
    assert worker_count(2) == 2
    assert worker_count('6') == 6
    assert worker_count(7) == 7
    assert worker_count(8) == 7
    assert worker_count(100) == 7

    monkeypatch.setenv('IBOT_WORKERS', '100')
    assert worker_count() == 8

    caplog.clear()
    with caplog.at_level(logging.WARNING, logger='ibot.parallel'):
        monkeypatch.setenv('IBOT_WORKERS', '0')
        assert worker_count() == 4
        monkeypatch.setenv('IBOT_WORKERS', 'нет')
        assert worker_count() == 4
        monkeypatch.setenv('IBOT_WORKERS', '-2')
        assert worker_count() == 4
        monkeypatch.setenv('IBOT_WORKERS', '2.5')
        assert worker_count() == 4
        assert worker_count(5) == 5
    messages = [record.message for record in caplog.records]
    assert messages == [
        'IBOT_WORKERS=0 не целое число от 1, беру половину ядер',
        'IBOT_WORKERS=нет не целое число от 1, беру половину ядер',
        'IBOT_WORKERS=-2 не целое число от 1, беру половину ядер',
        'IBOT_WORKERS=2.5 не целое число от 1, беру половину ядер',
    ]
    assert all('\n' not in message for message in messages)

    caplog.clear()
    monkeypatch.setenv('IBOT_WORKERS', '   ')
    assert worker_count() == 4
    assert caplog.records == []

    monkeypatch.setattr('ibot.parallel.available_cores', lambda: 1)
    monkeypatch.delenv('IBOT_WORKERS', raising=False)
    assert worker_count() == 1
    assert field_worker_max() == 1
    monkeypatch.setenv('IBOT_WORKERS', '4')
    assert worker_count() == 1
    assert worker_count(3) == 1
    assert available_cores() >= 1


def test_lower_priority_does_not_stop_the_run(monkeypatch):
    import ibot.parallel as parallel

    calls = []

    def refuse(amount):
        calls.append(amount)
        raise OSError('refused')

    monkeypatch.setattr(parallel.os, 'nice', refuse)
    lower_priority()
    assert calls == [10]

    def missing(amount):
        raise AttributeError('nice')

    monkeypatch.setattr(parallel.os, 'nice', missing)
    lower_priority()

    class WithoutNice:
        pass

    monkeypatch.setattr(parallel, 'os', WithoutNice())
    lower_priority()


def _worker_axes():
    return [
        {'key': 'fastType', 'kind': 'enum', 'values': ['SMA']},
        {'key': 'fastPeriod', 'kind': 'number', 'from': 2, 'to': 2, 'step': 1},
        {'key': 'slowType', 'kind': 'enum', 'values': ['EMA']},
        {'key': 'slowPeriod', 'kind': 'number', 'from': 4, 'to': 4, 'step': 1},
        {'key': 'offsetPct', 'kind': 'number', 'from': 0, 'to': 0, 'step': 0.1},
        {'key': 'lifetimeBars', 'kind': 'number', 'from': 1, 'to': 1, 'step': 1},
        {'key': 'takeProfitPct', 'kind': 'number', 'from': 1, 'to': 1, 'step': 0.5},
        {'key': 'stopLossPct', 'kind': 'number', 'from': 1, 'to': 1, 'step': 1},
        {'key': 'minSignalGapBars', 'kind': 'number', 'from': 0, 'to': 0, 'step': 1},
        {'key': 'direction', 'kind': 'enum', 'values': ['long']},
        {'key': 'crossMode', 'kind': 'enum', 'values': ['direct']},
        {'key': 'exitMode', 'kind': 'enum', 'values': ['tp_sl']},
    ]


def test_run_field_workers_are_stored_and_capped(monkeypatch):
    monkeypatch.setattr('ibot.parallel.available_cores', lambda: 8)
    body = {
        'strategyId': 'ma-cross',
        'axes': _worker_axes(),
        'deposit': 1000,
        'earlyStopPct': 25,
        'orderNotional': 1000,
        'leverage': 1,
    }
    omitted = parse_run_input(body, None, None)
    assert omitted['workers'] is None
    assert 'workers' not in to_settings(omitted)
    body['workers'] = 3
    parsed = parse_run_input(body, None, None)
    assert parsed['workers'] == 3
    assert to_settings(parsed)['workers'] == 3
    body['workers'] = 7
    assert parse_run_input(body, None, None)['workers'] == 7
    body['workers'] = 8
    with pytest.raises(ValueError, match='потоки: не больше 7'):
        parse_run_input(body, None, None)
    body['workers'] = 'нет'
    with pytest.raises(ValueError, match='потоки: нужно целое число от 1'):
        parse_run_input(body, None, None)


def test_job_size_fits_the_write_batch_and_shares_short_grids():
    assert job_size(96, 2) < 96
    assert 1 <= job_size(96, 2) <= DB_BATCH
    assert job_size(10_000, 3) == DB_BATCH
    assert job_size(2, 2) == 1


def test_estimate_scales_per_minute_by_worker_count(tmp_path, monkeypatch):
    import ibot.db as database
    import ibot.engine as engine

    monkeypatch.setattr(database, 'DATA', tmp_path)
    monkeypatch.setattr(engine, 'worker_count', lambda: 3)
    monkeypatch.setattr(engine, 'simulate', lambda *_args, **_kwargs: None)
    series = build_series(30)
    save_series('estimate-series', series)
    axes = [
        {'key': 'fastType', 'kind': 'enum', 'values': ['SMA']},
        {'key': 'fastPeriod', 'kind': 'number', 'from': 2, 'to': 2, 'step': 1},
        {'key': 'slowType', 'kind': 'enum', 'values': ['EMA']},
        {'key': 'slowPeriod', 'kind': 'number', 'from': 4, 'to': 4, 'step': 1},
        {'key': 'offsetPct', 'kind': 'number', 'from': 0, 'to': 0, 'step': 0.1},
        {'key': 'lifetimeBars', 'kind': 'number', 'from': 1, 'to': 1, 'step': 1},
        {'key': 'takeProfitPct', 'kind': 'number', 'from': 1, 'to': 1, 'step': 0.5},
        {'key': 'stopLossPct', 'kind': 'number', 'from': 1, 'to': 1, 'step': 1},
        {'key': 'minSignalGapBars', 'kind': 'number', 'from': 0, 'to': 0, 'step': 1},
        {'key': 'direction', 'kind': 'enum', 'values': ['long']},
        {'key': 'crossMode', 'kind': 'enum', 'values': ['direct']},
        {'key': 'exitMode', 'kind': 'enum', 'values': ['tp_sl']},
    ]
    settings = {
        'deposit': 1000,
        'earlyStopPct': 25,
        'orderNotional': 1000,
        'leverage': 1,
        'constraintEnabled': True,
    }
    body = estimate_run('estimate-series', series['openTime'][0], series['openTime'][-1], 'ma-cross', axes, settings)
    single = 60_000 / body['elapsedMs']
    assert body['workers'] == 3
    assert body['perMinute'] == pytest.approx(single * 3)
    assert body['minutes'] == pytest.approx(body['total'] / body['perMinute'])
    assert body['bars'] == 30


def test_estimate_uses_the_effective_worker_count(tmp_path, monkeypatch, caplog):
    import ibot.db as database
    import ibot.engine as engine

    monkeypatch.setattr(database, 'DATA', tmp_path)
    monkeypatch.setattr('ibot.parallel.available_cores', lambda: 8)
    monkeypatch.setattr(engine, 'simulate', lambda *_args, **_kwargs: None)
    monkeypatch.delenv('IBOT_WORKERS', raising=False)
    series = build_series(30)
    save_series('estimate-workers', series)
    axes = _worker_axes()
    settings = {
        'deposit': 1000,
        'earlyStopPct': 25,
        'orderNotional': 1000,
        'leverage': 1,
        'constraintEnabled': True,
    }

    def measure(extra=None):
        body = estimate_run(
            'estimate-workers',
            series['openTime'][0],
            series['openTime'][-1],
            'ma-cross',
            axes,
            {**settings, **(extra or {})},
        )
        single = 60_000 / body['elapsedMs']
        assert body['perMinute'] == pytest.approx(single * body['workers'])
        assert body['minutes'] == pytest.approx(body['total'] / body['perMinute'])
        return body

    assert measure()['workers'] == 4
    monkeypatch.setenv('IBOT_WORKERS', '6')
    assert measure()['workers'] == 6
    monkeypatch.setenv('IBOT_WORKERS', '100')
    assert measure()['workers'] == 8
    assert measure({'workers': 2})['workers'] == 2
    assert measure({'workers': 100})['workers'] == 7
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger='ibot.parallel'):
        monkeypatch.setenv('IBOT_WORKERS', 'много')
        assert measure()['workers'] == 4
    assert len(caplog.records) == 1
    assert 'IBOT_WORKERS=много' in caplog.records[0].message


def test_execute_prefers_the_run_field_over_the_env(tmp_path, monkeypatch):
    import ibot.db as database
    import ibot.engine as engine

    monkeypatch.setattr(database, 'DATA', tmp_path)
    monkeypatch.setattr('ibot.parallel.available_cores', lambda: 8)
    monkeypatch.setenv('IBOT_WORKERS', '6')
    seen = []

    def fake_pool(_spec, _jobs, worker_n, _on_rows, _on_tick, _should_cancel):
        seen.append(worker_n)

    monkeypatch.setattr(engine, 'run_pool', fake_pool)
    series = build_series(8)
    series_id = 'workers-field'
    save_series(series_id, series)
    db = connect()
    try:
        db.execute(
            '''INSERT INTO series (
                id, symbol, interval, start_ms, end_ms, bars, gaps_json,
                min_qty, step_size, tick_size, min_notional, status, progress_bars, updated_at
            ) VALUES (?, 'BTCUSDT', '5m', ?, ?, ?, '{"count":0,"items":[]}', 0.001, 0.001, 0.1, 5, 'ready', ?, ?)''',
            (series_id, series['openTime'][0], series['openTime'][-1], len(series['close']), len(series['close']), now_iso()),
        )
        db.commit()
        body = run_body(series_id)
        body['workers'] = 3
        pinned = create_run(db, body, None)
        assert json.loads(pinned['settings_json'])['workers'] == 3
        execute_run(db, pinned['id'])
        plain = create_run(db, run_body(series_id), None)
        execute_run(db, plain['id'])
        execute_run(db, pinned['id'], workers=2)
    finally:
        db.close()
    assert seen == [3, 6, 2]


def test_parallel_matches_single_thread_to_the_cent_and_resume_keeps_rows(tmp_path, monkeypatch):
    import ibot.db as database

    monkeypatch.setattr(database, 'DATA', tmp_path)
    series = build_series()
    series_id = 'fixture-btcusdt-5m'
    save_series(series_id, series)
    db = connect()
    try:
        db.execute(
            '''INSERT INTO series (
                id, symbol, interval, start_ms, end_ms, bars, gaps_json,
                min_qty, step_size, tick_size, min_notional, status, progress_bars, updated_at
            ) VALUES (?, 'BTCUSDT', '5m', ?, ?, ?, '{"count":0,"items":[]}', 0.001, 0.001, 0.1, 5, 'ready', ?, ?)''',
            (series_id, series['openTime'][0], series['openTime'][-1], len(series['close']), len(series['close']), now_iso()),
        )
        db.commit()
        single = create_run(db, run_body(series_id), None)
        parallel = create_run(db, run_body(series_id), None)
        assert single['total'] == 96
        execute_run(db, single['id'], parallel=False)
        execute_run(db, parallel['id'], parallel=True, workers=2)
        single_rows = rows_of(db, single['id'])
        parallel_rows = rows_of(db, parallel['id'])
        assert_same_rows(single_rows, parallel_rows)
        assert_grid_covered(parallel_rows)
        single_run = db.execute('SELECT * FROM runs WHERE id = ?', (single['id'],)).fetchone()
        parallel_run = db.execute('SELECT * FROM runs WHERE id = ?', (parallel['id'],)).fetchone()
        assert single_run['status'] == 'done'
        assert parallel_run['status'] == 'done'
        assert parallel_run['finished'] == single_run['finished']
        assert parallel_run['stopped'] == single_run['stopped']
        assert parallel_run['processed'] == single_run['processed'] == 96

        kept = single_rows[:48]
        finished = sum(1 for row in kept if row['status'] == 'done')
        stopped = len(kept) - finished
        resumed = create_run(db, run_body(series_id), None)
        kept_ids = []
        for row in kept:
            row_id = str(uuid.uuid4())
            kept_ids.append((row_id, row['ordinal'], row['profit'], row['status']))
            db.execute(
                '''INSERT INTO result_rows (
                    id, run_id, ordinal, status, reason, params_json, profit, profit_fact, winrate, trades,
                    max_draw, max_draw_pct, max_draw_at, worst_trade, worst_trade_at, worst_open, worst_open_at,
                    positive_month_share, best_month_share, months_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (
                    row_id, resumed['id'], row['ordinal'], row['status'], row['reason'], row['params_json'],
                    row['profit'], row['profit_fact'], row['winrate'], row['trades'], row['max_draw'], row['max_draw_pct'],
                    row['max_draw_at'], row['worst_trade'], row['worst_trade_at'], row['worst_open'], row['worst_open_at'],
                    row['positive_month_share'], row['best_month_share'], row['months_json'],
                ),
            )
        db.execute(
            '''UPDATE runs SET status = 'running', processed = ?, finished = ?, stopped = ? WHERE id = ?''',
            (len(kept), finished, stopped, resumed['id']),
        )
        db.commit()
        resume_interrupted(db)
        assert claim_next_run(db) == resumed['id']
        execute_run(db, resumed['id'], parallel=True, workers=2)
        resumed_rows = rows_of(db, resumed['id'])
        assert_same_rows(single_rows, resumed_rows)
        for row_id, ordinal, profit, status in kept_ids:
            saved = db.execute('SELECT * FROM result_rows WHERE id = ?', (row_id,)).fetchone()
            assert saved is not None
            assert saved['run_id'] == resumed['id']
            assert saved['ordinal'] == ordinal
            assert saved['status'] == status
            assert_cents(saved['profit'], profit, row_id)
        resumed_run = db.execute('SELECT * FROM runs WHERE id = ?', (resumed['id'],)).fetchone()
        assert resumed_run['status'] == 'done'
        assert resumed_run['processed'] == 96
    finally:
        db.close()
