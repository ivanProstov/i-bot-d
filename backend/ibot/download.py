import json
import threading
import time

from ibot.binance import fetch_klines_page, fetch_symbol_rules, interval_ms
from ibot.db import connect, now_iso
from ibot.series_file import empty_series, find_gaps, load_series, merge_series, save_series

JOBS = set()
LOCK = threading.Lock()


def download_series(series_id, symbol, interval, start_ms, end_ms):
    with LOCK:
        if series_id in JOBS:
            return
        JOBS.add(series_id)
    threading.Thread(target=_run, args=(series_id, symbol, interval, start_ms, end_ms), daemon=True).start()


def _run(series_id, symbol, interval, start_ms, end_ms):
    db = connect()
    try:
        step = interval_ms(interval)
        current = db.execute('SELECT * FROM series WHERE id = ?', (series_id,)).fetchone()
        existing = empty_series()
        have_file = False
        if current and current['bars']:
            existing = load_series(series_id)
            have_file = True
        stored_start = existing['openTime'][0] if have_file else None
        stored_end = existing['openTime'][-1] if have_file else None
        covered = stored_start is not None and stored_end is not None and stored_start <= start_ms and stored_end >= end_ms - step
        incoming = empty_series()
        if not covered:
            ranges = []
            if not have_file:
                ranges.append((start_ms, end_ms))
            else:
                if start_ms < stored_start:
                    ranges.append((start_ms, stored_start - 1))
                if end_ms > stored_end + step:
                    ranges.append((stored_end + step, end_ms))
            candles = []
            for start, end in ranges:
                candles.extend(_fetch_range(db, series_id, symbol, interval, start, end, len(candles)))
            incoming = _candles_to_series(candles)
        rules = {
            'minQty': current['min_qty'] if current else None,
            'stepSize': current['step_size'] if current else None,
            'tickSize': current['tick_size'] if current else None,
            'minNotional': current['min_notional'] if current else None,
        }
        try:
            rules = fetch_symbol_rules(symbol)
        except Exception:
            pass
        merged = merge_series(existing, incoming) if have_file else incoming
        if not merged['close']:
            raise ValueError('биржа не вернула свечи за этот диапазон')
        save_series(series_id, merged)
        gaps = find_gaps(merged['openTime'], step)
        db.execute(
            '''UPDATE series SET start_ms = ?, end_ms = ?, bars = ?, gaps_json = ?, min_qty = ?, step_size = ?,
               tick_size = ?, min_notional = ?, status = ?, progress_bars = ?, error = NULL, updated_at = ? WHERE id = ?''',
            (merged['openTime'][0], merged['openTime'][-1], len(merged['close']), json.dumps(gaps),
             rules['minQty'], rules['stepSize'], rules['tickSize'], rules['minNotional'], 'ready', len(merged['close']), now_iso(), series_id),
        )
        db.commit()
    except Exception as error:
        db.execute('UPDATE series SET status = ?, error = ?, updated_at = ? WHERE id = ?', ('error', str(error), now_iso(), series_id))
        db.commit()
    finally:
        db.close()
        with LOCK:
            JOBS.discard(series_id)


def _fetch_range(db, series_id, symbol, interval, start_ms, end_ms, already):
    step = interval_ms(interval)
    out = []
    cursor = start_ms
    while cursor <= end_ms:
        page = fetch_klines_page(symbol, interval, cursor, end_ms)
        if not page:
            break
        out.extend(page)
        db.execute('UPDATE series SET status = ?, progress_bars = ?, updated_at = ? WHERE id = ?', ('downloading', already + len(out), now_iso(), series_id))
        db.commit()
        last = page[-1]['openTime']
        nxt = last + step
        if nxt <= cursor:
            break
        cursor = nxt
        time.sleep(0.15)
    return out


def _candles_to_series(rows):
    data = empty_series()
    for row in rows:
        for key in data:
            data[key].append(row[key])
    return data
