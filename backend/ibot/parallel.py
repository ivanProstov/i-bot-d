"""Параллельный счёт прогона.

Процессы стартуют через spawn: так же код поднимается на macOS, где fork после
потоков сервера небезопасен. Каждый процесс один раз читает ряд и держит кэш
средних по всем парам (тип, период), которые уже посчитал, а не по одной
последней четвёрке. Родитель пишет строки сам и в порядке номеров сетки.
"""

import multiprocessing
import os
import queue
import threading
import time
import traceback
from pathlib import Path

from ibot.grid import enumerate_grid
from ibotd.averages import moving_average

# Сколько строк копим в одну транзакцию. Между 200 и 500.
DB_BATCH = 400
# Как часто процесс отдаёт уже посчитанные строки, чтобы скорость на экране не стояла.
PROGRESS_SECONDS = 1.0


def available_cores():
    affinity = getattr(os, 'sched_getaffinity', None)
    if affinity is not None:
        try:
            count = len(affinity(0))
            if count > 0:
                return count
        except OSError:
            pass
    return os.cpu_count() or 1


def worker_count():
    """Сколько процессов считают сетку. Одно ядро остаётся интерфейсу и серверу."""
    return max(1, available_cores() - 1)


def job_size(remaining, workers):
    """Пачка, которую забирает один процесс.

    Верх — размер транзакции. Низ такой, чтобы на короткой сетке работу
    получили все процессы, а не один.
    """
    remaining = int(remaining)
    workers = max(1, int(workers))
    if remaining <= 0:
        return 1
    pieces = workers * 4
    size = (remaining + pieces - 1) // pieces
    return max(1, min(DB_BATCH, size))


def iter_jobs(axes, constraint, already, size):
    """Пачки комбинаций начиная с номера already. Номер — порядок enumerate_grid."""
    size = max(1, int(size))
    ordinal = 0
    chunk = []
    start = None
    for combo in enumerate_grid(axes, constraint):
        if ordinal >= already:
            if start is None:
                start = ordinal
            chunk.append(combo)
            if len(chunk) >= size:
                yield start, chunk
                chunk = []
                start = None
        ordinal += 1
    if chunk:
        yield start, chunk


def _period_key(period):
    if isinstance(period, bool) or not isinstance(period, (int, float)):
        return period
    if float(period).is_integer():
        return int(period)
    return period


class MaCache:
    """Кэш средних одного процесса: все пары (тип, период) ряда, не только последняя."""

    def __init__(self):
        self._store = {}
        self._original = moving_average

    def __call__(self, kind, close, volume, period):
        key = (kind, _period_key(period), id(close))
        found = self._store.get(key)
        if found is not None:
            return found
        found = self._original(kind, close, volume, period)
        self._store[key] = found
        return found


def activate_ma_cache():
    import ibotd.plugins.ma_cross as ma

    if isinstance(ma.moving_average, MaCache):
        return ma.moving_average
    cache = MaCache()
    ma.moving_average = cache
    return cache


def _load_series(spec):
    import ibot.db as database
    from ibot.series_file import load_series, slice_series

    database.DATA = Path(spec['data_dir'])
    return slice_series(load_series(spec['series_id']), spec['from_ms'], spec['to_ms'])


def _pack_result(ordinal, params, result):
    return {
        'ordinal': ordinal,
        'params': params,
        'status': result['status'],
        'reason': result['reason'],
        'profit': result['profit'],
        'profitFact': result['profitFact'],
        'winrate': result['winrate'],
        'trades': result['trades'],
        'maxDraw': result['maxDraw'],
        'maxDrawPct': result['maxDrawPct'],
        'maxDrawAt': result['maxDrawAt'],
        'worstTrade': result['worstTrade'],
        'worstTradeAt': result['worstTradeAt'],
        'worstOpen': result['worstOpen'],
        'worstOpenAt': result['worstOpenAt'],
        'positiveMonthShare': result['positiveMonthShare'],
        'bestMonthShare': result['bestMonthShare'],
        'months': [item['profit'] for item in result['months']],
    }


def chunk_worker(spec, jobs, results, cancel_event):
    """Считает пачки одного процесса. Ряд и кэш средних живут до выхода процесса."""
    try:
        from ibotd.accounting import simulate
        from ibotd.contract import normalize_params
        from ibotd.registry import get_plugin

        series = None
        plugin = None
        cache = None
        settings = spec['settings']
        while True:
            try:
                job = jobs.get(timeout=0.5)
            except queue.Empty:
                if cancel_event.is_set():
                    break
                continue
            if job is None:
                break
            if series is None:
                series = _load_series(spec)
                plugin = get_plugin(spec['strategy_id'])
                activate_ma_cache()
                cache = {'key': '', 'prepared': None}
            start, combos = job
            batch = []
            sent_at = time.monotonic()
            for offset, combo in enumerate(combos):
                if cancel_event.is_set():
                    break
                params = normalize_params(plugin, {
                    **combo,
                    'leverage': settings['leverage'],
                    'orderNotional': settings['orderNotional'],
                    'entryOnClose': True,
                })
                result = simulate(plugin, series, params, settings, cache)
                batch.append(_pack_result(start + offset, params, result))
                now = time.monotonic()
                if len(batch) >= DB_BATCH or now - sent_at >= PROGRESS_SECONDS:
                    results.put(('rows', batch))
                    batch = []
                    sent_at = now
            if batch:
                results.put(('rows', batch))
            if cancel_event.is_set():
                break
        results.put(('exit', None))
    except Exception:
        results.put(('error', traceback.format_exc()))
        results.put(('exit', None))


def run_pool(spec, jobs, worker_n, on_rows, on_tick, should_cancel):
    """Запускает процессы и на этом потоке отдаёт строки в порядке прихода.

    Порядок сетки собирает вызывающий. should_cancel и on_tick тоже на этом потоке.
    """
    worker_n = max(1, int(worker_n))
    ctx = multiprocessing.get_context('spawn')
    job_queue = ctx.Queue(maxsize=worker_n)
    result_queue = ctx.Queue()
    cancel_event = ctx.Event()
    procs = []
    for index in range(worker_n):
        proc = ctx.Process(
            target=chunk_worker,
            name=f'ibot-run-{index}',
            args=(spec, job_queue, result_queue, cancel_event),
            daemon=True,
        )
        proc.start()
        procs.append(proc)

    def put(item, drop_on_cancel):
        while True:
            if drop_on_cancel and cancel_event.is_set():
                return False
            try:
                job_queue.put(item, timeout=0.3)
                return True
            except queue.Full:
                alive = any(proc.is_alive() for proc in procs)
                if not alive:
                    return False
                if drop_on_cancel and cancel_event.is_set():
                    return False

    def feed():
        try:
            for job in jobs:
                if not put(job, True):
                    break
            for _ in range(worker_n):
                if not put(None, False):
                    break
        except Exception:
            result_queue.put(('error', traceback.format_exc()))
            cancel_event.set()

    feeder = threading.Thread(target=feed, name='ibot-feed', daemon=True)
    feeder.start()
    exited = 0
    error = None
    try:
        while exited < worker_n:
            try:
                message = result_queue.get(timeout=0.4)
            except queue.Empty:
                message = None
            if message is not None:
                kind = message[0]
                if kind == 'rows':
                    on_rows(message[1])
                elif kind == 'exit':
                    exited += 1
                elif kind == 'error':
                    error = message[1]
                    cancel_event.set()
            if should_cancel():
                cancel_event.set()
            on_tick()
            if message is None and not any(proc.is_alive() for proc in procs):
                while True:
                    try:
                        message = result_queue.get_nowait()
                    except queue.Empty:
                        break
                    kind = message[0]
                    if kind == 'rows':
                        on_rows(message[1])
                    elif kind == 'exit':
                        exited += 1
                    elif kind == 'error':
                        error = message[1]
                break
    finally:
        if exited < worker_n:
            cancel_event.set()
        feeder.join(timeout=5)
        for proc in procs:
            proc.join(timeout=30)
            if proc.is_alive():
                proc.terminate()
                proc.join(timeout=5)
        result_queue.close()
        job_queue.close()
        result_queue.join_thread()
        job_queue.join_thread()
    if error:
        raise RuntimeError(error.strip())
    if exited < worker_n:
        codes = ', '.join(str(proc.exitcode) for proc in procs)
        raise RuntimeError(f'процесс счёта завершился без ответа ({codes})')
