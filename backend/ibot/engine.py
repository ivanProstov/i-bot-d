import json
import time
import uuid

from ibot.codec import dumps
from ibot.db import now_iso
from ibot.grid import enumerate_grid, grid_summary
from ibot.series_file import load_series, slice_series
from ibotd.accounting import month_keys_of, simulate
from ibotd.contract import normalize_params
from ibotd.registry import get_plugin, param_labels


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


def execute_run(db, run_id):
    try:
        _execute(db, run_id)
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
    per_minute = 60_000 / elapsed_ms
    return {
        'total': summary['total'],
        'bars': len(series['close']),
        'elapsedMs': elapsed_ms,
        'perMinute': per_minute,
        'minutes': summary['total'] / per_minute,
    }


def _execute(db, run_id):
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
    cache = {'key': '', 'prepared': None}
    already = run['processed'] or 0
    processed = already
    finished = run['finished'] or 0
    stopped = run['stopped'] or 0
    index = 0
    started = _parse_time(run['started_at']) or time.time()
    batch = []
    sql = '''INSERT INTO result_rows (
        id, run_id, ordinal, status, reason, params_json, profit, profit_fact, winrate, trades,
        max_draw, max_draw_pct, max_draw_at, worst_trade, worst_trade_at, worst_open, worst_open_at,
        positive_month_share, best_month_share, months_json
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)'''

    def flush():
        nonlocal batch
        try:
            db.executemany(sql, batch)
            elapsed = max(0.001, time.time() - started)
            per_minute = processed / (elapsed / 60)
            db.execute(
                'UPDATE runs SET processed = ?, finished = ?, stopped = ?, per_minute = ? WHERE id = ?',
                (processed, finished, stopped, per_minute, run_id),
            )
            db.commit()
            batch = []
        except Exception:
            db.rollback()
            raise

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
        batch.append((
            str(uuid.uuid4()), run_id, index, result['status'], result['reason'], dumps(params),
            result['profit'], result['profitFact'], result['winrate'], result['trades'], result['maxDraw'], result['maxDrawPct'],
            result['maxDrawAt'], result['worstTrade'], result['worstTradeAt'], result['worstOpen'], result['worstOpenAt'],
            result['positiveMonthShare'], result['bestMonthShare'], dumps([item['profit'] for item in result['months']]),
        ))
        processed += 1
        index += 1
        if len(batch) >= 20:
            flush()
            status = db.execute('SELECT status FROM runs WHERE id = ?', (run_id,)).fetchone()
            if status and status['status'] == 'cancelled':
                return
    if batch:
        flush()
    status = db.execute('SELECT status FROM runs WHERE id = ?', (run_id,)).fetchone()
    if status and status['status'] == 'cancelled':
        return
    db.execute("UPDATE runs SET status = 'done', finished_at = ? WHERE id = ?", (now_iso(), run_id))
    _write_terciles(db, run_id)
    db.commit()


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
