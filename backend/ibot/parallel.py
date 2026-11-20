"""Параллельный счёт прогона.

Процессы стартуют через spawn: так же код поднимается на macOS, где fork после
потоков сервера небезопасен. Каждый процесс один раз читает ряд и держит кэш
средних по всем парам (тип, период), которые уже посчитал, а не по одной
последней четвёрке. Родитель пишет строки сам и в порядке номеров сетки.
"""

import logging
import math
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
_log = logging.getLogger('ibot.parallel')


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


def default_worker_count():
    """Половина доступных ядер. На одном ядре остаётся один процесс."""
    return max(1, available_cores() // 2)


def field_worker_max():
    """Верх поля «Потоки»: одно ядро остаётся системе. На одном ядре верх равен 1."""
    return max(1, available_cores() - 1)


def _positive_int(value):
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value if value >= 1 else None
    if isinstance(value, float):
        if math.isfinite(value) and value.is_integer() and value >= 1:
            return int(value)
        return None
    if isinstance(value, str):
        text = value.strip()
        if text.isdigit():
            parsed = int(text)
            return parsed if parsed >= 1 else None
    return None


def worker_count(requested=None):
    """Сколько процессов считают сетку.

    Число прогона, если оно задано целым от 1, важнее переменной IBOT_WORKERS
    и обрезается до поля: ядра минус одно. Переменная обрезается до числа ядер.
    Пустая переменная — это не число. Кривое значение даёт половину ядер и одну строку в журнал.
    """
    chosen = _positive_int(requested)
    if chosen is not None:
        return min(chosen, field_worker_max())
    return _count_from_env()


def cap_explicit_workers(count):
    """Явный аргумент прогона: не ниже 1 и не выше числа ядер."""
    count = int(count)
    if count < 1:
        raise ValueError('число процессов меньше 1')
    return min(count, available_cores())


def _count_from_env():
    raw = os.environ.get('IBOT_WORKERS')
    if raw is None or raw.strip() == '':
        return default_worker_count()
    chosen = _positive_int(raw)
    if chosen is None:
        shown = ' '.join(raw.split())
        _log.warning('IBOT_WORKERS=%s не целое число от 1, беру половину ядер', shown)
        return default_worker_count()
    return min(chosen, available_cores())


def lower_priority():
    """Снижает приоритет процесса счёта, чтобы ноутбук оставался отзывчивым.

    Вызов внутри уже запущенного процесса: и на Linux, и на macOS это os.nice.
    Нет вызова или система отказала — прогон не останавливается.
    """
    nice = getattr(os, 'nice', None)
    if not callable(nice):
        return
    try:
        nice(10)
    except (OSError, AttributeError):
        return


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


def _swallow_queue_error(_error, _obj):
    """Ошибка слива в трубу при закрытии пула. Прогон из-за неё не останавливается."""
    return


def _arm_queue(pipe_queue):
    """Труба без читателя не должна держать фоновый поток до конца процесса.

    Флаг читается в момент старта потока очереди, поэтому его ставят
    до первой записи и до запуска процессов.
    """
    pipe_queue._ignore_epipe = True
    pipe_queue._on_queue_feeder_error = _swallow_queue_error


def _release_queue(pipe_queue):
    """Закрывает очередь и не ждёт бесконечного слива буфера в трубу.

    join_thread ждёт поток Queue._feed. После отмены процессы job_queue
    уже не читают: непрочитанная пачка заполняет трубу, и поток стоит
    в send_bytes. Тогда воркер не возвращается к следующему прогону.
    """
    try:
        pipe_queue.cancel_join_thread()
    except Exception:
        pass
    try:
        pipe_queue.close()
    except Exception:
        pass
    thread = getattr(pipe_queue, '_thread', None)
    if thread is None:
        return
    thread.join(timeout=0.5)
    if not thread.is_alive():
        return
    # Читателей уже нет, а в трубе нет места. Закрытие концов будит send_bytes.
    try:
        pipe_queue._reader.close()
    except Exception:
        pass
    try:
        pipe_queue._writer.close()
    except Exception:
        pass
    thread.join(timeout=2)


def chunk_worker(spec, jobs, results, cancel_event):
    """Считает пачки одного процесса. Ряд и кэш средних живут до выхода процесса."""
    try:
        lower_priority()
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
    worker_n = max(1, min(int(worker_n), available_cores()))
    ctx = multiprocessing.get_context('spawn')
    job_queue = ctx.Queue(maxsize=worker_n)
    result_queue = ctx.Queue()
    _arm_queue(job_queue)
    _arm_queue(result_queue)
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
            # После отмены процессы сами выходят по событию и очередь больше
            # не читают. Метку конца в неё не кладём: put встал бы без потребителя.
            for _ in range(worker_n):
                if cancel_event.is_set() or not any(proc.is_alive() for proc in procs):
                    break
                if not put(None, False):
                    break
        except Exception:
            try:
                result_queue.put(('error', traceback.format_exc()))
            except Exception:
                pass
            cancel_event.set()

    feeder = threading.Thread(target=feed, name='ibot-feed', daemon=True)
    feeder.start()
    exited = 0
    error = None
    cancelled = False

    def take(message):
        nonlocal exited, error
        if message is None:
            return
        kind = message[0]
        if kind == 'rows':
            on_rows(message[1])
        elif kind == 'exit':
            exited += 1
        elif kind == 'error':
            error = message[1]
            cancel_event.set()

    try:
        while exited < worker_n:
            try:
                message = result_queue.get(timeout=0.4)
            except queue.Empty:
                message = None
            take(message)
            if should_cancel():
                cancel_event.set()
                cancelled = True
            on_tick()
            if message is None and not any(proc.is_alive() for proc in procs):
                while True:
                    try:
                        take(result_queue.get_nowait())
                    except queue.Empty:
                        break
                    except (OSError, EOFError, ValueError):
                        break
                break
    finally:
        try:
            # Отмена могла прийти в тот же заход, где процессы уже вышли.
            if should_cancel():
                cancelled = True
            if exited < worker_n:
                cancel_event.set()
            feeder.join(timeout=5)
            forced = False
            for proc in procs:
                proc.join(timeout=30)
                if proc.is_alive():
                    forced = True
                    proc.terminate()
                    proc.join(timeout=5)
            feeder.join(timeout=2)
            if not forced:
                while True:
                    try:
                        take(result_queue.get_nowait())
                    except queue.Empty:
                        break
                    except (OSError, EOFError, ValueError):
                        break
        finally:
            _release_queue(job_queue)
            _release_queue(result_queue)
    if error and not cancelled:
        raise RuntimeError(error.strip())
    if exited < worker_n and not cancelled:
        codes = ', '.join(str(proc.exitcode) for proc in procs)
        raise RuntimeError(f'процесс счёта завершился без ответа ({codes})')
