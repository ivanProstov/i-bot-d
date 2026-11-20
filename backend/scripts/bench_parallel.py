"""Скорость однопоточного прохода и параллельного на длинном синтетическом ряде.

Сеть не используется. Ряд — 316800 баров 5m, это 1100 суток.
Запуск из корня репозитория:

    PYTHONPATH=backend python3 backend/scripts/bench_parallel.py
"""

import json
import math
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import ibot.db as database
from ibot.db import connect, now_iso
from ibot.engine import execute_run
from ibot.parallel import available_cores, worker_count
from ibot.series_file import save_series
from ibot.server import create_run

BARS = 288 * 1100  # 316800 баров 5m

AXES = [
    {'key': 'fastType', 'kind': 'enum', 'values': ['SMA', 'EMA']},
    {'key': 'fastPeriod', 'kind': 'number', 'from': 8, 'to': 12, 'step': 4},
    {'key': 'slowType', 'kind': 'enum', 'values': ['SMA', 'EMA']},
    {'key': 'slowPeriod', 'kind': 'number', 'from': 21, 'to': 34, 'step': 13},
    {'key': 'offsetPct', 'kind': 'number', 'from': 0, 'to': 0, 'step': 0.1},
    {'key': 'lifetimeBars', 'kind': 'number', 'from': 4, 'to': 4, 'step': 1},
    {'key': 'takeProfitPct', 'kind': 'number', 'from': 3, 'to': 3, 'step': 0.5},
    {'key': 'stopLossPct', 'kind': 'number', 'from': 2, 'to': 50, 'step': 48},
    {'key': 'minSignalGapBars', 'kind': 'number', 'from': 0, 'to': 0, 'step': 1},
    {'key': 'direction', 'kind': 'enum', 'values': ['long', 'short', 'both']},
    {'key': 'crossMode', 'kind': 'enum', 'values': ['direct']},
    {'key': 'exitMode', 'kind': 'enum', 'values': ['tp_sl', 'flip_on_cross']},
]


def build_series():
    start = int(datetime(2018, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
    step = 300_000
    close = []
    crash_at = int(BARS * 0.72)
    for index in range(BARS):
        wave = math.sin(index / 18.0) * 3.0
        trend = 0.0004 * index
        price = 100.0 + trend + wave
        if index >= crash_at:
            price = price * 0.55
        close.append(price)
    open_ = [close[0]] + close[:-1]
    high = [max(left, right) * 1.002 for left, right in zip(open_, close)]
    low = [max(0.5, min(left, right) * 0.998) for left, right in zip(open_, close)]
    return {
        'openTime': [start + index * step for index in range(BARS)],
        'open': open_,
        'high': high,
        'low': low,
        'close': close,
        'volume': [1000.0 + (index % 5) for index in range(BARS)],
    }


def body(series_id):
    return {
        'seriesId': series_id,
        'from': '2018-01-01',
        'to': '2021-06-01',
        'strategyId': 'ma-cross',
        'axes': AXES,
        'deposit': 1000,
        'earlyStopPct': 25,
        'orderNotional': 1000,
        'leverage': 1,
        'constraintEnabled': True,
    }


def per_minute(combos, seconds):
    return combos / (seconds / 60)


def _assert_same(left_rows, right_rows):
    if len(left_rows) != len(right_rows):
        raise SystemExit(f'число строк {len(left_rows)} и {len(right_rows)}')
    fields = (
        'profit', 'profit_fact', 'winrate', 'max_draw', 'max_draw_pct',
        'worst_trade', 'worst_open', 'positive_month_share', 'best_month_share',
    )
    for index, (left, right) in enumerate(zip(left_rows, right_rows)):
        if left['status'] != right['status'] or left['reason'] != right['reason'] or left['trades'] != right['trades']:
            raise SystemExit(f'строка {index} разошлась по статусу')
        if json.loads(left['params_json']) != json.loads(right['params_json']):
            raise SystemExit(f'строка {index} разошлась по параметрам')
        for field in fields:
            a, b = left[field], right[field]
            if a is None or b is None:
                if a is not None or b is not None:
                    raise SystemExit(f'строка {index} {field}')
            elif abs(float(a) - float(b)) >= 0.01:
                raise SystemExit(f'строка {index} {field} {a} {b}')
        left_months = json.loads(left['months_json'])
        right_months = json.loads(right['months_json'])
        if len(left_months) != len(right_months):
            raise SystemExit(f'строка {index} месяцы')
        for a, b in zip(left_months, right_months):
            if a is None or b is None:
                if a is not None or b is not None:
                    raise SystemExit(f'строка {index} месяц')
            elif abs(float(a) - float(b)) >= 0.01:
                raise SystemExit(f'строка {index} месяц {a} {b}')


def main():
    with tempfile.TemporaryDirectory() as folder:
        database.DATA = Path(folder)
        series = build_series()
        save_series('bench', series)
        db = connect()
        try:
            db.execute(
                '''INSERT INTO series (
                    id, symbol, interval, start_ms, end_ms, bars, gaps_json,
                    min_qty, step_size, tick_size, min_notional, status, progress_bars, updated_at
                ) VALUES ('bench', 'BTCUSDT', '5m', ?, ?, ?, '{"count":0,"items":[]}', 0.001, 0.001, 0.1, 5, 'ready', ?, ?)''',
                (series['openTime'][0], series['openTime'][-1], BARS, BARS, now_iso()),
            )
            db.commit()
            single = create_run(db, body('bench'), None)
            parallel = create_run(db, body('bench'), None)
            combos = single['total']
            started = time.perf_counter()
            execute_run(db, single['id'], parallel=False)
            single_seconds = time.perf_counter() - started
            started = time.perf_counter()
            execute_run(db, parallel['id'], parallel=True)
            parallel_seconds = time.perf_counter() - started
            left_rows = db.execute(
                'SELECT * FROM result_rows WHERE run_id = ? ORDER BY ordinal',
                (single['id'],),
            ).fetchall()
            right_rows = db.execute(
                'SELECT * FROM result_rows WHERE run_id = ? ORDER BY ordinal',
                (parallel['id'],),
            ).fetchall()
            _assert_same(left_rows, right_rows)
        finally:
            db.close()
    left = len(left_rows)
    right = len(right_rows)
    cores = available_cores()
    workers = worker_count()
    print(f'bars {BARS}')
    print(f'combos {combos}')
    print(f'cores {cores}')
    print(f'workers {workers}')
    print(f'single_seconds {single_seconds:.3f}')
    print(f'parallel_seconds {parallel_seconds:.3f}')
    print(f'single_per_minute {per_minute(combos, single_seconds):.1f}')
    print(f'parallel_per_minute {per_minute(combos, parallel_seconds):.1f}')
    print(f'speedup {single_seconds / parallel_seconds:.2f}')
    print(f'rows {left} {right}')
    if left != right or left != combos:
        raise SystemExit('число строк не совпало')


if __name__ == '__main__':
    main()
