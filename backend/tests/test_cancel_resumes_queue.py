"""Отмена параллельного прогона не должна оставлять очередь воркера.

Ряд локальный. Сеть и ключ не используются. Труба пачек сужена: на Linux
она иначе вмещает две пачки и зависание join_thread не проявляется, на macOS
пачка и так больше трубы.
"""

import math
import multiprocessing
import threading
import time
from datetime import datetime, timezone

import pytest

from ibot.db import connect, now_iso
from ibot.engine import claim_next_run, execute_run
from ibot.parallel import available_cores
from ibot.series_file import save_series
from ibot.server import create_run

BARS = 8_000
STEP_MS = 60_000


def build_series():
    start = int(datetime(2020, 1, 15, tzinfo=timezone.utc).timestamp() * 1000)
    close = []
    for index in range(BARS):
        close.append(100.0 + 0.002 * index + math.sin(index / 17.0) * 4.0)
    open_ = [close[0]] + close[:-1]
    high = [max(left, right) * 1.002 for left, right in zip(open_, close)]
    low = [max(0.5, min(left, right) * 0.998) for left, right in zip(open_, close)]
    return {
        'openTime': [start + index * STEP_MS for index in range(BARS)],
        'open': open_,
        'high': high,
        'low': low,
        'close': close,
        'volume': [1000.0 + (index % 7) for index in range(BARS)],
    }


def axes(wide):
    return [
        {'key': 'fastType', 'kind': 'enum', 'values': ['SMA', 'EMA'] if wide else ['SMA']},
        {'key': 'fastPeriod', 'kind': 'number', 'from': 8, 'to': 28 if wide else 8, 'step': 2},
        {'key': 'slowType', 'kind': 'enum', 'values': ['SMA', 'EMA'] if wide else ['EMA']},
        {'key': 'slowPeriod', 'kind': 'number', 'from': 40, 'to': 80 if wide else 40, 'step': 2},
        {'key': 'offsetPct', 'kind': 'number', 'from': 0, 'to': 0, 'step': 0.1},
        {'key': 'lifetimeBars', 'kind': 'number', 'from': 1, 'to': 1, 'step': 1},
        {'key': 'takeProfitPct', 'kind': 'number', 'from': 2, 'to': 2, 'step': 0.5},
        {'key': 'stopLossPct', 'kind': 'number', 'from': 1, 'to': 2 if wide else 1, 'step': 1},
        {'key': 'minSignalGapBars', 'kind': 'number', 'from': 0, 'to': 0, 'step': 1},
        {'key': 'direction', 'kind': 'enum', 'values': ['long', 'short', 'both'] if wide else ['long']},
        {'key': 'crossMode', 'kind': 'enum', 'values': ['direct']},
        {'key': 'exitMode', 'kind': 'enum', 'values': ['tp_sl', 'flip_on_cross'] if wide else ['tp_sl']},
    ]


def run_body(series_id, wide):
    return {
        'seriesId': series_id,
        'from': '2020-01-01',
        'to': '2020-02-01',
        'strategyId': 'ma-cross',
        'axes': axes(wide),
        'deposit': 1000,
        'earlyStopPct': 25,
        'orderNotional': 1000,
        'leverage': 1,
        'constraintEnabled': True,
    }


def shrink_job_pipes(monkeypatch):
    """Пачка ~30 КБ. Труба в 4 КБ заполняется, пока процессы её не читают."""
    import fcntl
    from multiprocessing.context import SpawnContext

    original = SpawnContext.Queue
    setter = getattr(fcntl, 'F_SETPIPE_SZ', None)

    def queue(self, maxsize=0):
        pipe = original(self, maxsize)
        if setter is not None and isinstance(maxsize, int) and 0 < maxsize <= 64:
            fcntl.fcntl(pipe._writer.fileno(), setter, 4096)
        return pipe

    monkeypatch.setattr(SpawnContext, 'Queue', queue)


def test_cancel_mid_run_lets_the_next_queued_run_finish(tmp_path, monkeypatch):
    import ibot.db as database

    cores = available_cores()
    if cores < 2:
        pytest.skip('нужны хотя бы два ядра, чтобы пул был параллельным')
    monkeypatch.setattr(database, 'DATA', tmp_path)
    monkeypatch.setenv('IBOT_WORKERS', str(min(4, cores)))
    shrink_job_pipes(monkeypatch)

    series = build_series()
    series_id = 'cancel-queue-btcusdt-1m'
    save_series(series_id, series)
    db = connect()
    db.execute(
        '''INSERT INTO series (
            id, symbol, interval, start_ms, end_ms, bars, gaps_json,
            min_qty, step_size, tick_size, min_notional, status, progress_bars, updated_at
        ) VALUES (?, 'BTCUSDT', '1m', ?, ?, ?, '{"count":0,"items":[]}', 0.001, 0.001, 0.1, 5, 'ready', ?, ?)''',
        (series_id, series['openTime'][0], series['openTime'][-1], BARS, BARS, now_iso()),
    )
    db.commit()
    first = create_run(db, run_body(series_id, wide=True), None)
    first_id = first['id']
    assert first['total'] > 1000
    db.close()

    stop = threading.Event()

    def serve():
        local = connect()
        try:
            while not stop.is_set():
                run_id = claim_next_run(local)
                if not run_id:
                    time.sleep(0.05)
                    continue
                execute_run(local, run_id)
        finally:
            local.close()

    thread = threading.Thread(target=serve, name='ibot-worker-test', daemon=True)
    thread.start()

    def read_run(run_id):
        watch = connect()
        try:
            return watch.execute('SELECT * FROM runs WHERE id = ?', (run_id,)).fetchone()
        finally:
            watch.close()

    deadline = time.monotonic() + 30
    running = None
    while time.monotonic() < deadline:
        running = read_run(first_id)
        if running['processed'] > 0 and running['status'] == 'running':
            break
        time.sleep(0.05)
    assert running is not None
    assert running['status'] == 'running'
    assert 0 < running['processed'] < running['total']
    pool = [proc for proc in multiprocessing.active_children() if proc.name.startswith('ibot-run-')]
    assert len(pool) >= 2

    watch = connect()
    watch.execute(
        "UPDATE runs SET status = 'cancelled', finished_at = ? WHERE id = ? AND status = 'running'",
        (now_iso(), first_id),
    )
    watch.commit()
    watch.close()

    second_holder = connect()
    try:
        second = create_run(second_holder, run_body(series_id, wide=False), None)
        second_id = second['id']
        assert second['total'] >= 1
    finally:
        second_holder.close()

    deadline = time.monotonic() + 40
    finished = None
    while time.monotonic() < deadline:
        finished = read_run(second_id)
        if finished['status'] == 'done':
            break
        time.sleep(0.05)
    stop.set()
    thread.join(timeout=5)

    cancelled = read_run(first_id)
    assert finished['status'] == 'done', (
        f"следующий прогон не досчитан: {finished['status']} processed={finished['processed']}; "
        f"остановленный {cancelled['status']} processed={cancelled['processed']}"
    )
    assert finished['processed'] == finished['total']
    assert finished['processed'] > 0
    assert cancelled['status'] == 'cancelled'
    assert cancelled['processed'] > 0
    saved = connect()
    try:
        kept = saved.execute(
            'SELECT COUNT(*) AS n FROM result_rows WHERE run_id = ?',
            (first_id,),
        ).fetchone()['n']
    finally:
        saved.close()
    assert kept > 0
    assert kept == cancelled['processed']
