import json
import mimetypes
import os
import re
import signal
import subprocess
import sys
import threading
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from ibot.catalog import PLAN_COLUMNS, plan_cell_meta, video_ma_preset
from ibot.codec import dumps, ready
from ibot.db import ROOT, connect, now_iso
from ibot.download import download_series
from ibot.engine import estimate_run
from ibot.export_sheet import build_workbook
from ibot.grid import grid_summary
from ibot.series_file import load_series, slice_series
from ibot.validate import parse_day_end, parse_day_start, parse_run_input, summary_for, to_settings
from ibotd.contract import build_bot_config, metrics_snapshot
from ibotd.hypothesis import apply_hypothesis, find_hypothesis, hypotheses_for, is_btc_symbol
from ibotd.market import USD_M_INTERVALS, require_interval, require_symbol
from ibotd.registry import CATALOG, get_plugin, param_labels, public_plugins
from ibotd.result import STORAGE_TO_PUBLIC, public_result

PORT = int(os.environ.get('TESTER_PORT') or 8787)
WEB_ROOT = ROOT / 'apps' / 'tester' / 'dist'
SORTS = {
    'Profit': 'profit',
    'ProfitFact': 'profit_fact',
    'Winrate': 'winrate',
    'Trades': 'trades',
    'MaxDraw': 'max_draw',
    'MaxDrawPct': 'max_draw_pct',
    'positiveMonthShare': 'positive_month_share',
    'bestMonthShare': 'best_month_share',
}
CUTOFFS = {
    'Profit': 'profit',
    'ProfitFact': 'profit_fact',
    'Winrate': 'winrate',
    'Trades': 'trades',
    'MaxDraw': 'max_draw',
    'MaxDrawPct': 'max_draw_pct',
}
PLAN_STATUSES = {'not_started', 'queued', 'running', 'has_candidates', 'discarded'}

_worker = None
_shutting_down = False
_restarts = 0


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, fmt, *args):
        return

    def do_OPTIONS(self):
        self._bytes(204, b'', 'text/plain')

    def do_GET(self):
        self._dispatch()

    def do_POST(self):
        self._dispatch()

    def do_PUT(self):
        self._dispatch()

    def _dispatch(self):
        try:
            parsed = urlparse(self.path)
            if parsed.path.startswith('/api/'):
                self._route(parsed)
            else:
                self._static(parsed.path)
        except Exception as error:
            self._json(400, {'error': str(error)})

    def _route(self, parsed):
        path = parsed.path
        method = self.command
        query = parse_qs(parsed.query)
        if method == 'GET' and path == '/api/health':
            return self._json(200, {'ok': True})
        if method == 'GET' and path == '/api/catalog':
            return self._json(200, {'catalog': CATALOG, 'plugins': public_plugins(), 'intervals': USD_M_INTERVALS})
        if method == 'GET' and path == '/api/preset/ma-cross':
            return self._json(200, video_ma_preset())
        if method == 'GET' and path == '/api/hypotheses':
            return self._json(200, {'hypotheses': hypotheses_for('ma-cross')})
        if method == 'GET' and path == '/api/plan-columns':
            return self._json(200, {'columns': PLAN_COLUMNS})
        if method == 'POST' and path == '/api/grid/summary':
            return self._json(200, summary_for(self._body()))

        db = connect()
        try:
            if method == 'GET' and path == '/api/ideas':
                rows = db.execute('SELECT * FROM ideas ORDER BY updated_at DESC').fetchall()
                return self._json(200, {'ideas': [idea_json(row) for row in rows]})
            if method == 'POST' and path == '/api/ideas':
                return self._json(201, idea_json(save_idea(db, self._body(), None)))
            idea = re.fullmatch(r'/api/ideas/([^/]+)', path)
            if idea and method == 'PUT':
                return self._json(200, idea_json(save_idea(db, self._body(), idea.group(1))))

            if method == 'GET' and path == '/api/series':
                rows = db.execute('SELECT * FROM series ORDER BY updated_at DESC').fetchall()
                return self._json(200, {'series': [series_json(row) for row in rows]})
            if method == 'POST' and path == '/api/series/download':
                return self._json(202, start_download(db, self._body()))
            series = re.fullmatch(r'/api/series/([^/]+)', path)
            if series and method == 'GET':
                row = db.execute('SELECT * FROM series WHERE id = ?', (series.group(1),)).fetchone()
                if not row:
                    return self._json(404, {'error': 'ряд не найден'})
                return self._json(200, series_detail(row, _first(query, 'from'), _first(query, 'to')))

            if method == 'POST' and path == '/api/estimate':
                return self._json(200, run_estimate(db, self._body()))
            if method == 'GET' and path == '/api/runs':
                rows = db.execute('SELECT * FROM runs ORDER BY created_at DESC').fetchall()
                return self._json(200, {'runs': [run_json(row) for row in rows]})
            if method == 'POST' and path == '/api/runs':
                return self._json(201, run_json(create_run(db, self._body(), None)))

            run = re.fullmatch(r'/api/runs/([^/]+)(/[^/]+)?', path)
            if run:
                run_id, action = run.group(1), run.group(2) or ''
                if method == 'GET' and action == '':
                    row = db.execute('SELECT * FROM runs WHERE id = ?', (run_id,)).fetchone()
                    if not row:
                        return self._json(404, {'error': 'прогон не найден'})
                    return self._json(200, run_json(row))
                if method == 'POST' and action == '/cancel':
                    db.execute(
                        "UPDATE runs SET status = 'cancelled', finished_at = ? WHERE id = ? AND status IN ('queued', 'running')",
                        (now_iso(), run_id),
                    )
                    db.commit()
                    row = db.execute('SELECT * FROM runs WHERE id = ?', (run_id,)).fetchone()
                    if not row:
                        return self._json(404, {'error': 'прогон не найден'})
                    return self._json(200, run_json(row))
                if method == 'GET' and action == '/rows':
                    return self._json(200, query_rows(db, run_id, query))
                if method == 'POST' and action == '/cutoff':
                    return self._json(200, apply_cutoff(db, run_id, self._body()))
                if method == 'POST' and action == '/restore':
                    return self._json(200, restore_cutoff(db, run_id))
                if method == 'GET' and action == '/export.xlsx':
                    return self._file(export_run(db, run_id, query), 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', f'run-{run_id}.xlsx')

            if method == 'GET' and path == '/api/drafts':
                rows = db.execute('SELECT * FROM drafts ORDER BY created_at DESC').fetchall()
                return self._json(200, {'drafts': [draft_json(row) for row in rows]})
            if method == 'POST' and path == '/api/drafts':
                return self._json(201, create_drafts(db, self._body()))
            if method == 'GET' and path == '/api/books':
                rows = db.execute('SELECT id, name, kind, band, created_at FROM books ORDER BY created_at DESC').fetchall()
                return self._json(200, {'books': [dict(row) for row in rows]})
            if method == 'POST' and path == '/api/books':
                return self._json(201, create_book(db, self._body()))
            book = re.fullmatch(r'/api/books/([^/]+)/export\.xlsx', path)
            if book and method == 'GET':
                payload = export_book(db, book.group(1))
                return self._file(payload, 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', f'book-{book.group(1)}.xlsx')

            if method == 'GET' and path == '/api/plan':
                return self._json(200, read_plan(db, _first(query, 'interval') or '5m'))
            if method == 'PUT' and path == '/api/plan':
                return self._json(200, write_plan(db, self._body()))
            if method == 'POST' and path == '/api/hypotheses/queue':
                return self._json(201, queue_hypothesis(db, self._body()))
            self._json(404, {'error': 'маршрут не найден'})
        finally:
            db.close()

    def _body(self):
        length = int(self.headers.get('content-length') or 0)
        if length > 2_000_000:
            raise ValueError('слишком большое тело запроса')
        raw = self.rfile.read(length) if length else b''
        if not raw:
            return {}
        try:
            parsed = json.loads(raw.decode())
        except json.JSONDecodeError as error:
            raise ValueError('JSON не читается') from error
        if not isinstance(parsed, dict):
            raise ValueError('ожидался объект JSON')
        return parsed

    def _json(self, status, body):
        self._bytes(status, dumps(body).encode(), 'application/json; charset=utf-8')

    def _file(self, payload, content_type, filename):
        self.send_response(200)
        self.send_header('content-type', content_type)
        self.send_header('content-disposition', f'attachment; filename="{filename}"')
        self.send_header('access-control-allow-origin', '*')
        self.send_header('content-length', str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _bytes(self, status, payload, content_type):
        self.send_response(status)
        self.send_header('content-type', content_type)
        self.send_header('access-control-allow-origin', '*')
        self.send_header('access-control-allow-headers', 'content-type')
        self.send_header('access-control-allow-methods', 'GET, POST, PUT, OPTIONS')
        self.send_header('content-length', str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _static(self, pathname):
        index = WEB_ROOT / 'index.html'
        if not index.is_file():
            html = '<p>Интерфейс ещё не собран. В другом терминале из корня репозитория: npm run tester:web и откройте http://127.0.0.1:5173</p>'.encode()
            return self._bytes(200, html, 'text/html; charset=utf-8')
        requested = 'index.html' if pathname == '/' else pathname.lstrip('/')
        target = (WEB_ROOT / requested).resolve()
        root = WEB_ROOT.resolve()
        if target != root and root not in target.parents:
            return self._bytes(403, b'', 'text/plain')
        if not target.is_file():
            target = index
        content_type = mimetypes.types_map.get(target.suffix, 'application/octet-stream')
        if content_type.startswith('text/') or target.suffix == '.js':
            content_type += '; charset=utf-8'
        self._bytes(200, target.read_bytes(), content_type)


def save_idea(db, body, idea_id):
    name = body.get('name').strip() if isinstance(body.get('name'), str) else ''
    rule_text = body.get('ruleText').strip() if isinstance(body.get('ruleText'), str) else ''
    strategy_id = body.get('strategyId') if isinstance(body.get('strategyId'), str) else ''
    if not name:
        raise ValueError('нужно имя идеи')
    if not rule_text:
        raise ValueError('нужен текст правила своими словами')
    try:
        get_plugin(strategy_id)
    except ValueError:
        raise ValueError('плагин стратегии не зарегистрирован') from None
    stamp = now_iso()
    if not idea_id:
        idea_id = str(uuid.uuid4())
        db.execute(
            'INSERT INTO ideas (id, name, rule_text, strategy_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)',
            (idea_id, name, rule_text, strategy_id, stamp, stamp),
        )
    else:
        existing = db.execute('SELECT id FROM ideas WHERE id = ?', (idea_id,)).fetchone()
        if not existing:
            raise ValueError('идея не найдена')
        db.execute(
            'UPDATE ideas SET name = ?, rule_text = ?, strategy_id = ?, updated_at = ? WHERE id = ?',
            (name, rule_text, strategy_id, stamp, idea_id),
        )
    db.commit()
    return db.execute('SELECT * FROM ideas WHERE id = ?', (idea_id,)).fetchone()


def idea_json(row):
    return {
        'id': row['id'],
        'name': row['name'],
        'ruleText': row['rule_text'],
        'strategyId': row['strategy_id'],
        'createdAt': row['created_at'],
        'updatedAt': row['updated_at'],
    }


def start_download(db, body):
    symbol = require_symbol(body.get('symbol'))
    interval = require_interval(body.get('interval'))
    start_ms = parse_day_start(body.get('start'))
    end_ms = parse_day_end(body.get('end'))
    if end_ms < start_ms:
        raise ValueError('конец истории раньше начала')
    row = db.execute('SELECT * FROM series WHERE symbol = ? AND interval = ?', (symbol, interval)).fetchone()
    if not row:
        series_id = str(uuid.uuid4())
        db.execute(
            'INSERT INTO series (id, symbol, interval, bars, status, progress_bars, updated_at) VALUES (?, ?, ?, 0, ?, 0, ?)',
            (series_id, symbol, interval, 'downloading', now_iso()),
        )
        db.commit()
        row = db.execute('SELECT * FROM series WHERE id = ?', (series_id,)).fetchone()
    elif row['status'] == 'downloading':
        return series_json(row)
    else:
        db.execute(
            'UPDATE series SET status = ?, error = NULL, progress_bars = 0, updated_at = ? WHERE id = ?',
            ('downloading', now_iso(), row['id']),
        )
        db.commit()
    download_series(row['id'], symbol, interval, start_ms, end_ms)
    fresh = db.execute('SELECT * FROM series WHERE id = ?', (row['id'],)).fetchone()
    return series_json(fresh)


def series_json(row):
    gaps = json.loads(row['gaps_json'] or '{"count":0,"items":[]}')
    return {
        'id': row['id'],
        'symbol': row['symbol'],
        'interval': row['interval'],
        'start': iso_ms(row['start_ms']),
        'end': iso_ms(row['end_ms']),
        'bars': row['bars'],
        'gapCount': gaps.get('count', 0),
        'gaps': gaps.get('items', []),
        'minQty': row['min_qty'],
        'lotStep': row['step_size'],
        'tickSize': row['tick_size'],
        'minNotional': row['min_notional'],
        'status': row['status'],
        'progressBars': row['progress_bars'],
        'error': row['error'],
        'updatedAt': row['updated_at'],
    }


def series_detail(row, start, end):
    base = series_json(row)
    if not start or not end or row['status'] != 'ready':
        base['sliceBars'] = None
        return base
    sliced = slice_series(load_series(row['id']), parse_day_start(start), parse_day_end(end))
    base['sliceBars'] = len(sliced['close'])
    return base


def run_estimate(db, body):
    series = ready_series(db, body.get('seriesId'))
    parsed = parse_run_input(body, number_or_none(series['step_size']), number_or_none(series['min_qty']))
    return estimate_run(series['id'], parse_day_start(body.get('from')), parse_day_end(body.get('to')), parsed['strategyId'], parsed['axes'], to_settings(parsed))


def create_run(db, body, hypothesis_id):
    series = ready_series(db, body.get('seriesId'))
    parsed = parse_run_input(body, number_or_none(series['step_size']), number_or_none(series['min_qty']))
    plugin = get_plugin(parsed['strategyId'])
    summary = grid_summary(
        param_labels(plugin),
        plugin.constraint,
        parsed['axes'],
        parsed['constraintEnabled'],
    )
    run_id = str(uuid.uuid4())
    parent_ids = [str(item) for item in body.get('parentRowIds')] if isinstance(body.get('parentRowIds'), list) else []
    db.execute(
        '''INSERT INTO runs (
            id, idea_id, hypothesis_id, parent_run_id, parent_row_ids_json, series_id, symbol, interval,
            from_ms, to_ms, strategy_id, axes_json, settings_json, status, total, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?, ?)''',
        (
            run_id,
            body.get('ideaId') if isinstance(body.get('ideaId'), str) else None,
            hypothesis_id,
            body.get('parentRunId') if isinstance(body.get('parentRunId'), str) else None,
            dumps(parent_ids),
            series['id'],
            series['symbol'],
            series['interval'],
            parse_day_start(body.get('from')),
            parse_day_end(body.get('to')),
            parsed['strategyId'],
            dumps(parsed['axes']),
            dumps(to_settings(parsed)),
            summary['total'],
            now_iso(),
        ),
    )
    db.commit()
    return db.execute('SELECT * FROM runs WHERE id = ?', (run_id,)).fetchone()


def ready_series(db, series_id):
    if not isinstance(series_id, str) or not series_id:
        raise ValueError('не выбран ряд')
    series = db.execute('SELECT * FROM series WHERE id = ?', (series_id,)).fetchone()
    if not series:
        raise ValueError('ряд не найден')
    if series['status'] != 'ready':
        raise ValueError('ряд ещё не скачан')
    return series


def run_json(row):
    total = row['total'] or 0
    processed = row['processed'] or 0
    return {
        'id': row['id'],
        'ideaId': row['idea_id'],
        'hypothesisId': row['hypothesis_id'],
        'parentRunId': row['parent_run_id'],
        'parentRowIds': json.loads(row['parent_row_ids_json'] or '[]'),
        'seriesId': row['series_id'],
        'symbol': row['symbol'],
        'interval': row['interval'],
        'from': iso_ms(row['from_ms'])[:10],
        'to': iso_ms(row['to_ms'])[:10],
        'strategyId': row['strategy_id'],
        'axes': json.loads(row['axes_json'] or '[]'),
        'settings': json.loads(row['settings_json'] or '{}'),
        'status': row['status'],
        'total': total,
        'processed': processed,
        'finished': row['finished'],
        'stopped': row['stopped'],
        'remaining': max(0, total - processed),
        'perMinute': row['per_minute'],
        'error': row['error'],
        'colors': colors_of(row),
        'monthKeys': json.loads(row['month_keys_json'] or '[]'),
        'createdAt': row['created_at'],
        'startedAt': row['started_at'],
        'finishedAt': row['finished_at'],
    }


def query_rows(db, run_id, query):
    run = db.execute('SELECT * FROM runs WHERE id = ?', (run_id,)).fetchone()
    if not run:
        raise ValueError('прогон не найден')
    where, args = row_filter(run_id, query)
    sort = SORTS.get(_first(query, 'sort') or 'Profit', 'profit')
    direction = 'ASC' if _first(query, 'dir') == 'asc' else 'DESC'
    requested = _number(_first(query, 'limit'), 30)
    limit = min(500 if _first(query, 'ids') else 200, max(1, int(requested)))
    offset = max(0, int(_number(_first(query, 'offset'), 0)))
    total = db.execute(f'SELECT COUNT(*) AS n FROM result_rows WHERE {where}', args).fetchone()['n']
    rows = db.execute(
        f'SELECT * FROM result_rows WHERE {where} ORDER BY {sort} {direction} LIMIT ? OFFSET ?',
        (*args, limit, offset),
    ).fetchall()
    return {'total': total, 'rows': [public_row(row, run) for row in rows], 'run': run_json(run)}


def row_filter(run_id, query):
    where = ['run_id = ?']
    args = [run_id]
    ids = _first(query, 'ids')
    if ids:
        listed = [item.strip() for item in ids.split(',') if item.strip()]
        if listed:
            where.append(f"id IN ({','.join('?' for _ in listed)})")
            args.extend(listed)
    status = _first(query, 'status') or 'done'
    if status == 'rejected':
        where.append("status IN ('stopped', 'discarded')")
    elif status in ('done', 'stopped', 'discarded'):
        where.append('status = ?')
        args.append(status)
    _push(where, args, 'profit', _first(query, 'minProfit'), '>=')
    _push(where, args, 'profit_fact', _first(query, 'minProfitFact'), '>=')
    _push(where, args, 'max_draw_pct', _first(query, 'maxDrawPct'), '<=')
    _push(where, args, 'winrate', _first(query, 'minWinrate'), '>=')
    _push(where, args, 'winrate', _first(query, 'maxWinrate'), '<=')
    _push(where, args, 'trades', _first(query, 'minTrades'), '>=')
    _push(where, args, 'positive_month_share', _first(query, 'minPositiveMonthShare'), '>=')
    return ' AND '.join(where), args


def _push(where, args, column, value, op):
    if value is None or value == '':
        return
    try:
        parsed = float(value)
    except ValueError:
        return
    if parsed != parsed or parsed in (float('inf'), float('-inf')):
        return
    where.append(f'{column} {op} ?')
    args.append(parsed)


def public_row(row, run):
    keys = json.loads(run['month_keys_json'] or '[]')
    values = json.loads(row['months_json'] or '[]')
    stored = {storage: row[storage] for storage, _public in STORAGE_TO_PUBLIC}
    return public_result(row['id'], row['status'], row['reason'], json.loads(row['params_json']), stored, keys, values)


def apply_cutoff(db, run_id, body):
    metric = body.get('metric')
    op = body.get('op')
    column = CUTOFFS.get(metric) if isinstance(metric, str) else None
    if not column:
        raise ValueError('неизвестная метрика порога')
    if op not in ('>=', '<='):
        raise ValueError('порог сравнивается через >= или <=')
    try:
        value = float(body.get('value'))
    except (TypeError, ValueError):
        raise ValueError('у порога нет числа') from None
    if value != value or value in (float('inf'), float('-inf')):
        raise ValueError('у порога нет числа')
    comparison = '<' if op == '>=' else '>'
    reason = f'порог {metric} {op} {ready(value)}'
    cursor = db.execute(
        f"UPDATE result_rows SET status = 'discarded', reason = ? WHERE run_id = ? AND status = 'done' AND {column} {comparison} ?",
        (reason, run_id, value),
    )
    db.commit()
    return {'moved': cursor.rowcount}


def restore_cutoff(db, run_id):
    cursor = db.execute(
        "UPDATE result_rows SET status = 'done', reason = NULL WHERE run_id = ? AND status = 'discarded'",
        (run_id,),
    )
    db.commit()
    return {'restored': cursor.rowcount}


def export_run(db, run_id, query):
    run = db.execute('SELECT * FROM runs WHERE id = ?', (run_id,)).fetchone()
    if not run:
        raise ValueError('прогон не найден')
    where, args = row_filter(run_id, query)
    count = db.execute(f'SELECT COUNT(*) AS n FROM result_rows WHERE {where}', args).fetchone()['n']
    if count > 50_000:
        raise ValueError('в фильтре больше 50 000 строк, сузьте его перед выгрузкой')
    rows = db.execute(f'SELECT * FROM result_rows WHERE {where} ORDER BY profit DESC', args).fetchall()
    sheet_rows = [sheet_row(public_row(row, run)) for row in rows]
    return build_workbook(sheet_rows, json.loads(run['month_keys_json'] or '[]'), colors_of(run))


def sheet_row(row):
    return {
        'params': row['params'],
        'status': str(row['status']),
        'reason': str(row['reason']) if row['reason'] else None,
        'Profit': number_or_none(row['Profit']),
        'ProfitFact': number_or_none(row['ProfitFact']),
        'Winrate': number_or_none(row['Winrate']),
        'Trades': number_or_none(row['Trades']),
        'MaxDraw': number_or_none(row['MaxDraw']),
        'MaxDrawPct': number_or_none(row['MaxDrawPct']),
        'MaxDrawAt': str(row['MaxDrawAt']) if row['MaxDrawAt'] else None,
        'WorstTrade': number_or_none(row['WorstTrade']),
        'WorstTradeAt': str(row['WorstTradeAt']) if row['WorstTradeAt'] else None,
        'WorstOpen': number_or_none(row['WorstOpen']),
        'WorstOpenAt': str(row['WorstOpenAt']) if row['WorstOpenAt'] else None,
        'positiveMonthShare': number_or_none(row['positiveMonthShare']),
        'bestMonthShare': number_or_none(row['bestMonthShare']),
        'months': [item['profit'] for item in row['months']],
    }


def create_drafts(db, body):
    run_id = body.get('runId') if isinstance(body.get('runId'), str) else ''
    row_ids = [str(item) for item in body.get('rowIds')] if isinstance(body.get('rowIds'), list) else []
    run = db.execute('SELECT * FROM runs WHERE id = ?', (run_id,)).fetchone()
    if not run:
        raise ValueError('прогон не найден')
    if not row_ids:
        raise ValueError('не выбраны строки')
    created = []
    settings = json.loads(run['settings_json'])
    for row_id in row_ids:
        row = db.execute('SELECT * FROM result_rows WHERE id = ? AND run_id = ?', (row_id, run_id)).fetchone()
        if not row:
            raise ValueError('строка прогона не найдена')
        if row['status'] != 'done':
            raise ValueError('в черновик берётся только досчитанная строка')
        config = build_bot_config(
            strategy_id=run['strategy_id'],
            params=json.loads(row['params_json']),
            run_id=run_id,
            symbol=run['symbol'],
            interval=run['interval'],
            lot_step=number_or_none(settings.get('lotStep')),
        )
        metrics = metrics_snapshot(
            profit=number_or_none(row['profit']),
            profit_fact=number_or_none(row['profit_fact']),
            winrate=number_or_none(row['winrate']),
            trades=row['trades'] or 0,
            max_draw=number_or_none(row['max_draw']),
            history_from=iso_ms(run['from_ms'])[:10],
            history_to=iso_ms(run['to_ms'])[:10],
            early_stop_pct=settings.get('earlyStopPct'),
            run_id=run_id,
        )
        draft_id = str(uuid.uuid4())
        db.execute(
            'INSERT INTO drafts (id, run_id, row_id, config_json, metrics_json, created_at) VALUES (?, ?, ?, ?, ?, ?)',
            (draft_id, run_id, row_id, dumps(config), dumps(metrics), now_iso()),
        )
        created.append(draft_json(db.execute('SELECT * FROM drafts WHERE id = ?', (draft_id,)).fetchone()))
    db.commit()
    return {'drafts': created}


def draft_json(row):
    return {
        'id': row['id'],
        'status': 'draft',
        'sourceRowId': row['row_id'],
        'config': json.loads(row['config_json']),
        'metrics': json.loads(row['metrics_json']),
        'createdAt': row['created_at'],
    }


def create_book(db, body):
    name = body.get('name').strip() if isinstance(body.get('name'), str) else ''
    kind = body.get('kind') if body.get('kind') in ('working', 'research') else ''
    band = body.get('band') if body.get('band') in ('higher', 'short') else ''
    run_id = body.get('runId') if isinstance(body.get('runId'), str) else ''
    row_ids = [str(item) for item in body.get('rowIds')] if isinstance(body.get('rowIds'), list) else []
    if not name:
        raise ValueError('нужно имя сводной')
    if not kind or not band:
        raise ValueError('нужны вид сводной и группа таймфреймов')
    run = db.execute('SELECT * FROM runs WHERE id = ?', (run_id,)).fetchone()
    if not run:
        raise ValueError('прогон не найден')
    if not row_ids:
        raise ValueError('не выбраны строки')
    rows = []
    for row_id in row_ids:
        row = db.execute('SELECT * FROM result_rows WHERE id = ? AND run_id = ?', (row_id, run_id)).fetchone()
        if not row:
            raise ValueError('строка прогона не найдена')
        if row['status'] != 'done':
            raise ValueError('в сводную берётся только досчитанная строка')
        rows.append(public_row(row, run))
    book_id = str(uuid.uuid4())
    db.execute(
        'INSERT INTO books (id, name, kind, band, rows_json, created_at) VALUES (?, ?, ?, ?, ?, ?)',
        (book_id, name, kind, band, dumps(rows), now_iso()),
    )
    db.commit()
    return {'id': book_id, 'name': name, 'kind': kind, 'band': band, 'rows': len(rows)}


def export_book(db, book_id):
    book = db.execute('SELECT * FROM books WHERE id = ?', (book_id,)).fetchone()
    if not book:
        raise ValueError('сводная не найдена')
    rows = json.loads(book['rows_json'])
    keys = [item['month'] for item in rows[0]['months']] if rows else []
    return build_workbook(
        [sheet_row(row) for row in rows],
        keys,
        {'profit33': None, 'profit66': None, 'pf33': None, 'pf66': None},
    )


def read_plan(db, interval):
    name = require_interval(interval)
    saved = db.execute('SELECT * FROM plan_cells WHERE interval = ?', (name,)).fetchall()
    by_cell = {row['cell']: row for row in saved}
    cells = []
    for cell in range(1, 64):
        meta = plan_cell_meta(cell) or {'column': '', 'direction': '', 'variant': None}
        row = by_cell.get(cell)
        cells.append({
            'cell': cell,
            'column': meta['column'],
            'direction': meta['direction'],
            'variant': meta['variant'],
            'status': row['status'] if row else 'not_started',
            'note': row['note'] or '' if row else '',
        })
    return {'interval': name, 'columns': PLAN_COLUMNS, 'cells': cells}


def write_plan(db, body):
    interval = require_interval(body.get('interval'))
    cell_raw = body.get('cell')
    if isinstance(cell_raw, bool) or not isinstance(cell_raw, (int, float)) or int(cell_raw) != cell_raw:
        raise ValueError('ячейка плана от 1 до 63')
    cell = int(cell_raw)
    status = body.get('status')
    if cell < 1 or cell > 63:
        raise ValueError('ячейка плана от 1 до 63')
    if status not in PLAN_STATUSES:
        raise ValueError('неизвестный статус ячейки')
    note = body.get('note') if isinstance(body.get('note'), str) else ''
    db.execute(
        '''INSERT INTO plan_cells (cell, interval, status, note, updated_at) VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(cell, interval) DO UPDATE SET status = excluded.status, note = excluded.note, updated_at = excluded.updated_at''',
        (cell, interval, status, note, now_iso()),
    )
    db.commit()
    return {'ok': True}


def queue_hypothesis(db, body):
    hypothesis_id = body.get('hypothesisId') if isinstance(body.get('hypothesisId'), str) else ''
    hypothesis = find_hypothesis(hypothesis_id)
    if not hypothesis:
        raise ValueError('такой гипотезы нет в списке')
    series = ready_series(db, body.get('seriesId'))
    if hypothesis['rejectBtc'] and is_btc_symbol(series['symbol']):
        raise ValueError('эта гипотеза не ставится на символ, который начинается с BTC')
    strategy_id = body.get('strategyId') if isinstance(body.get('strategyId'), str) else ''
    if strategy_id != hypothesis['strategyId']:
        raise ValueError('плагин стратегии не зарегистрирован')
    get_plugin(strategy_id)
    if not isinstance(body.get('axes'), list):
        raise ValueError('нет сетки')
    queued = dict(body)
    queued['axes'] = apply_hypothesis(body['axes'], hypothesis)
    queued['strategyId'] = hypothesis['strategyId']
    return run_json(create_run(db, queued, hypothesis['id']))


def colors_of(row):
    return {
        'profit33': number_or_none(row['profit_p33']),
        'profit66': number_or_none(row['profit_p66']),
        'pf33': number_or_none(row['pf_p33']),
        'pf66': number_or_none(row['pf_p66']),
    }


def number_or_none(value):
    if value is None or value == '':
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed != parsed or parsed in (float('inf'), float('-inf')):
        return None
    return ready(parsed)


def iso_ms(value):
    if value is None:
        return None
    return datetime.fromtimestamp(float(value) / 1000, timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')


def _first(query, key):
    values = query.get(key)
    return values[0] if values else None


def _number(value, fallback):
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _start_worker():
    global _worker
    env = os.environ.copy()
    backend = str(ROOT / 'backend')
    env['PYTHONPATH'] = backend + os.pathsep + env.get('PYTHONPATH', '')
    _worker = subprocess.Popen([sys.executable, '-m', 'ibot.worker'], cwd=str(ROOT), env=env)
    threading.Thread(target=_watch_worker, args=(_worker,), daemon=True).start()


def _watch_worker(process):
    global _restarts
    code = process.wait()
    if _shutting_down:
        return
    _restarts += 1
    print(f'воркер остановился с кодом {code}', flush=True)
    if _restarts <= 5:
        threading.Timer(1, _start_worker).start()


def _stop(signum, _frame):
    global _shutting_down
    _shutting_down = True
    if _worker and _worker.poll() is None:
        _worker.send_signal(signum)
    raise SystemExit(0)


def main():
    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    _start_worker()
    server = ThreadingHTTPServer(('127.0.0.1', PORT), Handler)
    print(f'тестировщик слушает http://127.0.0.1:{PORT}', flush=True)
    server.serve_forever()
