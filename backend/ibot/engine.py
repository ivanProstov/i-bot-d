import json
import time
import uuid

import ibot.db as database
from ibot.codec import dumps
from ibot.db import now_iso
from ibot.grid import enumerate_grid, grid_summary
from ibot.parallel import DB_BATCH, PROGRESS_SECONDS, cap_explicit_workers, iter_jobs, job_size, run_pool, worker_count
from ibot.series_file import load_series, slice_series
from ibotd.accounting import month_keys_of, simulate
from ibotd.contract import normalize_params
from ibotd.registry import get_plugin, param_labels

# Однопоточный проход для сверки. Очередь его не вызывает. Пачка как раньше.
_SINGLE_BATCH = 20
_INSERT = '''INSERT INTO result_rows (
    id, run_id, ordinal, status, reason, params_json, profit, profit_fact, winrate, trades,
    max_draw, max_draw_pct, max_draw_at, worst_trade, worst_trade_at, worst_open, worst_open_at,
    positive_month_share, best_month_share, months_json
  ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)'''


def claim_next_run(db):
    row = db.execute("SELECT id FROM runs WHERE status = 'queued' ORDER BY created_at LIMIT 1").fetchone()
    if not row:
        return None
    result = db.execute(
        "UPDATE runs SET status = 'running', started_at = COALESCE(started_at, ?) WHERE id = ? AND status = 'queued'",
        (now_iso(), row['id']),
    )
    db.commit()
    return row['id'] if result.rowcount == 1 else None


def resume_interrupted(db):
    db.execute("UPDATE runs SET status = 'queued' WHERE status = 'running'")
    db.commit()


def execute_run(db, run_id, *, parallel=True, workers=None):
    """Считает прогон. parallel=False — прежний один поток, очередь его не зовёт."""
    try:
        _execute(db, run_id, parallel=parallel, workers=workers)
    except Exception as error:
        _fail(db, run_id, str(error))


def estimate_run(series_id, from_ms, to_ms, strategy_id, axes, settings):
    plugin = get_plugin(strategy_id)
    summary = grid_summary(
        param_labels(plugin),
        plugin.constraint,
        axes,
        settings['constraintEnabled'],
    )
    if summary['overflow'] or summary['total'] is None:
        raise ValueError('комбинаций слишком много, сузьте сетку')
    series = slice_series(load_series(series_id), from_ms, to_ms)
    if not series['close']:
        raise ValueError('в выбранных датах нет свечей')
    constraint = plugin.constraint if settings['constraintEnabled'] else None
    first = next(enumerate_grid(axes, constraint), None)
    if not first:
        raise ValueError('в сетке нет ни одной комбинации')
    params = normalize_params(plugin, {**first, 'leverage': settings['leverage'], 'orderNotional': settings['orderNotional'], 'entryOnClose': True})
    started = time.perf_counter()
    simulate(plugin, series, params, settings)
    elapsed_ms = max(1, round((time.perf_counter() - started) * 1000))
    requested = settings.get('workers') if isinstance(settings, dict) else None
    workers = worker_count() if requested is None or requested == '' else worker_count(requested)
    # Одна комбинация измерена в одном процессе. Оценка полного перебора — как у очереди.
    per_minute = (60_000 / elapsed_ms) * workers
    return {
        'total': summary['total'],
        'bars': len(series['close']),
        'elapsedMs': elapsed_ms,
        'workers': workers,
        'perMinute': per_minute,
        'minutes': summary['total'] / per_minute,
    }


def _execute(db, run_id, *, parallel, workers):
    run = db.execute('SELECT * FROM runs WHERE id = ?', (run_id,)).fetchone()
    if not run:
        return
    try:
        plugin = get_plugin(run['strategy_id'])
    except ValueError as error:
        _fail(db, run_id, str(error))
        return
    axes = json.loads(run['axes_json'])
    settings = json.loads(run['settings_json'])
    try:
        series = slice_series(load_series(run['series_id']), run['from_ms'], run['to_ms'])
    except Exception as error:
        _fail(db, run_id, str(error))
        return
    if not series['close']:
        _fail(db, run_id, 'в выбранных датах нет свечей')
        return
    stored_keys = json.loads(run['month_keys_json']) if run['month_keys_json'] else None
    keys = stored_keys if isinstance(stored_keys, list) else month_keys_of(series['openTime'])
    if not isinstance(stored_keys, list):
        db.execute('UPDATE runs SET month_keys_json = ? WHERE id = ?', (dumps(keys), run_id))
        db.commit()
    constraint = plugin.constraint if settings.get('constraintEnabled') else None
    if parallel:
        _execute_parallel(db, run, run_id, axes, constraint, settings, workers)
        return
    _execute_single(db, run, run_id, plugin, axes, constraint, settings, series)


def _flush_rows(db, run_id, batch, processed, finished, stopped, started):
    try:
        db.executemany(_INSERT, batch)
        elapsed = max(0.001, time.time() - started)
        per_minute = processed / (elapsed / 60)
        db.execute(
            'UPDATE runs SET processed = ?, finished = ?, stopped = ?, per_minute = ? WHERE id = ?',
            (processed, finished, stopped, per_minute, run_id),
        )
        db.commit()
    except Exception:
        db.rollback()
        raise


def _finish(db, run_id):
    status = db.execute('SELECT status FROM runs WHERE id = ?', (run_id,)).fetchone()
    if not status or status['status'] == 'cancelled':
        return
    db.execute("UPDATE runs SET status = 'done', finished_at = ? WHERE id = ?", (now_iso(), run_id))
    _write_terciles(db, run_id)
    db.commit()


def _pack_row(run_id, ordinal, params, result, months):
    return (
        str(uuid.uuid4()), run_id, ordinal, result['status'], result['reason'], dumps(params),
        result['profit'], result['profitFact'], result['winrate'], result['trades'], result['maxDraw'], result['maxDrawPct'],
        result['maxDrawAt'], result['worstTrade'], result['worstTradeAt'], result['worstOpen'], result['worstOpenAt'],
        result['positiveMonthShare'], result['bestMonthShare'], dumps(months),
    )


def _execute_single(db, run, run_id, plugin, axes, constraint, settings, series):
    cache = {'key': '', 'prepared': None}
    already = run['processed'] or 0
    processed = already
    finished = run['finished'] or 0
    stopped = run['stopped'] or 0
    index = 0
    started = _parse_time(run['started_at']) or time.time()
    batch = []

    def flush():
        nonlocal batch
        _flush_rows(db, run_id, batch, processed, finished, stopped, started)
        batch = []

    for combo in enumerate_grid(axes, constraint):
        if index < already:
            index += 1
            continue
        params = normalize_params(plugin, {**combo, 'leverage': settings['leverage'], 'orderNotional': settings['orderNotional'], 'entryOnClose': True})
        result = simulate(plugin, series, params, settings, cache)
        if result['status'] == 'done':
            finished += 1
        else:
            stopped += 1
        batch.append(_pack_row(run_id, index, params, result, [item['profit'] for item in result['months']]))
        processed += 1
        index += 1
        if len(batch) >= _SINGLE_BATCH:
            flush()
            status = db.execute('SELECT status FROM runs WHERE id = ?', (run_id,)).fetchone()
            if status and status['status'] == 'cancelled':
                return
    if batch:
        flush()
    _finish(db, run_id)


def _execute_parallel(db, run, run_id, axes, constraint, settings, workers):
    already = run['processed'] or 0
    status = db.execute('SELECT status FROM runs WHERE id = ?', (run_id,)).fetchone()
    initial_cancel = bool(status and status['status'] == 'cancelled')
    remaining = max(0, (run['total'] or 0) - already)
    if workers is None:
        requested = settings.get('workers') if isinstance(settings, dict) else None
        count = worker_count() if requested is None or requested == '' else worker_count(requested)
    else:
        count = cap_explicit_workers(workers)
    if initial_cancel:
        count = 1
        size = DB_BATCH
    else:
        if remaining > 0:
            count = min(count, remaining)
        size = job_size(max(remaining, 1), count)
    jobs = iter_jobs(axes, constraint, already, size)
    try:
        first = next(jobs)
    except StopIteration:
        _finish(db, run_id)
        return

    def ordered_jobs():
        yield first
        if initial_cancel:
            return
        yield from jobs

    processed = already
    finished = run['finished'] or 0
    stopped = run['stopped'] or 0
    started = _parse_time(run['started_at']) or time.time()
    held = {}
    batch = []
    next_ord = already
    last_commit = time.monotonic()

    def commit():
        nonlocal batch, last_commit
        if not batch:
            return
        _flush_rows(db, run_id, batch, processed, finished, stopped, started)
        batch = []
        last_commit = time.monotonic()

    def drain():
        nonlocal next_ord, processed, finished, stopped
        while next_ord in held:
            item = held.pop(next_ord)
            if item['status'] == 'done':
                finished += 1
            else:
                stopped += 1
            batch.append(_pack_row(run_id, item['ordinal'], item['params'], item, item['months']))
            processed += 1
            next_ord += 1
            if len(batch) >= DB_BATCH:
                commit()

    def on_rows(items):
        for item in items:
            ordinal = item['ordinal']
            if ordinal < next_ord or ordinal in held:
                raise RuntimeError(f'повтор порядкового номера {ordinal}')
            held[ordinal] = item
        drain()
        if batch and time.monotonic() - last_commit >= PROGRESS_SECONDS:
            commit()

    def on_tick():
        if batch and time.monotonic() - last_commit >= PROGRESS_SECONDS:
            commit()

    def should_cancel():
        # Первая пачка уже остановленного прогона должна дописаться: событие не ставим.
        if initial_cancel:
            return False
        row = db.execute('SELECT status FROM runs WHERE id = ?', (run_id,)).fetchone()
        return bool(row and row['status'] == 'cancelled')

    spec = {
        'data_dir': str(database.DATA),
        'series_id': run['series_id'],
        'from_ms': int(run['from_ms']),
        'to_ms': int(run['to_ms']),
        'strategy_id': run['strategy_id'],
        'settings': settings,
    }
    run_pool(spec, ordered_jobs(), count, on_rows, on_tick, should_cancel)
    drain()
    commit()
    fresh = db.execute('SELECT status FROM runs WHERE id = ?', (run_id,)).fetchone()
    cancelled = bool(fresh and fresh['status'] == 'cancelled')
    if held and not cancelled:
        raise RuntimeError('в прогоне пропущены комбинации')
    _finish(db, run_id)


def _write_terciles(db, run_id):
    def cuts(column):
        count = db.execute(
            f"SELECT COUNT(*) AS n FROM result_rows WHERE run_id = ? AND status = 'done' AND {column} IS NOT NULL",
            (run_id,),
        ).fetchone()['n']
        if count < 3:
            return None, None

        def pick(offset):
            row = db.execute(
                f"SELECT {column} AS v FROM result_rows WHERE run_id = ? AND status = 'done' AND {column} IS NOT NULL ORDER BY {column} LIMIT 1 OFFSET ?",
                (run_id, offset),
            ).fetchone()
            return row['v'] if row else None

        return pick(count // 3), pick((count * 2) // 3)

    profit33, profit66 = cuts('profit')
    pf33, pf66 = cuts('profit_fact')
    db.execute(
        'UPDATE runs SET profit_p33 = ?, profit_p66 = ?, pf_p33 = ?, pf_p66 = ? WHERE id = ?',
        (profit33, profit66, pf33, pf66, run_id),
    )


def _fail(db, run_id, message):
    db.execute(
        "UPDATE runs SET status = 'error', error = ?, finished_at = ? WHERE id = ? AND status != 'cancelled'",
        (message, now_iso(), run_id),
    )
    db.commit()


def _parse_time(value):
    if not value:
        return None
    try:
        return datetime_from_iso(value)
    except ValueError:
        return None


def datetime_from_iso(value):
    text = value.replace('Z', '+00:00')
    from datetime import datetime
    return datetime.fromisoformat(text).timestamp()
