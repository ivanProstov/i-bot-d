import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

import pytest

from ibot.db import connect
from ibot.download import JOBS, LOCK
from ibot.engine import claim_next_run, execute_run
from ibot.server import Handler
from ibotd import binance


def ms(year, month, day):
    return int(datetime(year, month, day, tzinfo=timezone.utc).timestamp() * 1000)


def kline(open_ms, close, high=None, low=None):
    high = close if high is None else high
    low = close if low is None else low
    return [open_ms, str(close), str(high), str(low), str(close), '1', open_ms + 299_999, '0', 1, '0', '0', '0']


def build_candles():
    base = ms(2020, 1, 15)
    step = 300_000
    candles = [kline(base + index * step, close) for index, close in enumerate((10, 10, 10, 11))]
    candles.append(kline(base + 4 * step, 8, 8, 8))
    candles.append(kline(ms(2020, 2, 15), 8, 8, 8))
    return candles


class FakeExchange:
    def __init__(self, candles):
        self.candles = candles
        self.urls = []
        self.rules_fail = set()
        self.kline_fail = set()
        self.kline_empty = set()

    def __call__(self, url):
        self.urls.append(url)
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme != 'https' or parsed.netloc != 'fapi.binance.com':
            raise AssertionError(url)
        if parsed.path not in ('/fapi/v1/klines', '/fapi/v1/exchangeInfo'):
            raise AssertionError(url)
        query = urllib.parse.parse_qs(parsed.query)
        symbol = query.get('symbol', [''])[0]
        if parsed.path == '/fapi/v1/klines':
            if symbol in self.kline_fail:
                return 400, b'{"msg":"klines down"}', 'bad'
            if symbol in self.kline_empty:
                return 200, b'[]', ''
            start = int(query['startTime'][0])
            end = int(query['endTime'][0])
            rows = [row for row in self.candles if start <= int(row[0]) <= end]
            return 200, json.dumps(rows).encode(), ''
        if symbol in self.rules_fail:
            return 400, b'{"msg":"rules down"}', 'bad'
        body = {
            'symbols': [{
                'symbol': symbol,
                'filters': [
                    {'filterType': 'LOT_SIZE', 'minQty': '0.001', 'stepSize': '0.001'},
                    {'filterType': 'PRICE_FILTER', 'tickSize': '0.10'},
                    {'filterType': 'MIN_NOTIONAL', 'notional': '5'},
                ],
            }],
        }
        return 200, json.dumps(body).encode(), ''


def call(base, method, path, body=None):
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(
        base + path,
        data=data,
        method=method,
        headers={'Content-Type': 'application/json'},
    )
    last_error = None
    for _ in range(20):
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                raw = response.read()
                return response.status, json.loads(raw.decode()) if raw else {}
        except urllib.error.HTTPError as error:
            raw = error.read()
            return error.code, json.loads(raw.decode()) if raw else {}
        except urllib.error.URLError as error:
            last_error = error
            time.sleep(0.02)
    raise AssertionError(last_error)


def wait_series(base, series_id):
    last = None
    for _ in range(100):
        code, last = call(base, 'GET', f'/api/series/{series_id}?from=2020-01-01&to=2020-02-28')
        assert code == 200
        if last['status'] in ('ready', 'error'):
            with LOCK:
                busy = series_id in JOBS
            if not busy:
                return last
        time.sleep(0.02)
    raise AssertionError(last)


def download(base, symbol):
    code, body = call(base, 'POST', '/api/series/download', {
        'symbol': symbol,
        'interval': '5m',
        'start': '2020-01-01',
        'end': '2020-02-28',
    })
    assert code == 202, body
    return wait_series(base, body['id'])


def grid_axes(stop_from=1, stop_to=50, stop_step=49, fast=2, slow=3, direction=None, cross=None, exit_mode=None):
    return [
        {'key': 'fastType', 'kind': 'enum', 'values': ['SMA']},
        {'key': 'fastPeriod', 'kind': 'number', 'from': fast, 'to': fast, 'step': 1},
        {'key': 'slowType', 'kind': 'enum', 'values': ['SMA']},
        {'key': 'slowPeriod', 'kind': 'number', 'from': slow, 'to': slow, 'step': 1},
        {'key': 'offsetPct', 'kind': 'number', 'from': 0, 'to': 0, 'step': 0.1},
        {'key': 'lifetimeBars', 'kind': 'number', 'from': 1, 'to': 1, 'step': 1},
        {'key': 'takeProfitPct', 'kind': 'number', 'from': 50, 'to': 50, 'step': 0.5},
        {'key': 'stopLossPct', 'kind': 'number', 'from': stop_from, 'to': stop_to, 'step': stop_step},
        {'key': 'minSignalGapBars', 'kind': 'number', 'from': 0, 'to': 0, 'step': 1},
        {'key': 'direction', 'kind': 'enum', 'values': direction or ['long', 'short', 'both']},
        {'key': 'crossMode', 'kind': 'enum', 'values': cross or ['direct', 'reverse']},
        {'key': 'exitMode', 'kind': 'enum', 'values': exit_mode or ['tp_sl', 'flip_on_cross']},
    ]


def run_body(series_id, axes, **extra):
    body = {
        'seriesId': series_id,
        'from': '2020-01-01',
        'to': '2020-02-28',
        'strategyId': 'ma-cross',
        'axes': axes,
        'deposit': 1000,
        'earlyStopPct': 25,
        'orderNotional': 1000,
        'leverage': 1,
        'constraintEnabled': True,
    }
    body.update(extra)
    return body


def drain(run_id):
    db = connect()
    try:
        claimed = claim_next_run(db)
        assert claimed == run_id
        execute_run(db, run_id)
    finally:
        db.close()


def axis(run, key):
    return next(item for item in run['axes'] if item['key'] == key)


def month(row, name):
    return next(item for item in row['months'] if item['month'] == name)


@pytest.fixture
def api(tmp_path, monkeypatch):
    from http.server import ThreadingHTTPServer

    import ibot.db as database
    import ibot.download as download

    exchange = FakeExchange(build_candles())
    monkeypatch.setattr(database, 'DATA', tmp_path)
    monkeypatch.setattr(binance, '_urlopen', exchange)
    monkeypatch.setattr(download.time, 'sleep', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(binance.time, 'sleep', lambda *_args, **_kwargs: None)
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{server.server_address[1]}'
    try:
        yield base, exchange
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        with LOCK:
            JOBS.clear()


def test_queue_cutoff_second_pass_and_table_use_mocked_exchange(api):
    base, exchange = api
    series = download(base, 'BTCUSDT')
    assert series['status'] == 'ready'
    assert series['bars'] == 6
    assert series['sliceBars'] == 6
    assert series['lotStep'] == 0.001
    assert series['symbol'] == 'BTCUSDT'
    assert exchange.urls
    for url in exchange.urls:
        assert url.startswith('https://fapi.binance.com/fapi/v1/')

    code, queued = call(base, 'POST', '/api/hypotheses/queue', run_body(
        series['id'],
        grid_axes(),
        hypothesisId='ma-direct-long-tpsl',
    ))
    assert code == 201, queued
    assert queued['status'] == 'queued'
    assert queued['hypothesisId'] == 'ma-direct-long-tpsl'
    assert queued['total'] == 2
    assert axis(queued, 'direction')['values'] == ['long']
    assert axis(queued, 'crossMode')['values'] == ['direct']
    assert axis(queued, 'exitMode')['values'] == ['tp_sl']
    assert axis(queued, 'stopLossPct')['from'] == 1
    assert axis(queued, 'stopLossPct')['to'] == 50

    code, plan = call(base, 'GET', '/api/plan?interval=5m')
    assert code == 200
    assert len(plan['cells']) == 63
    assert {cell['status'] for cell in plan['cells']} == {'not_started'}

    drain(queued['id'])
    code, run = call(base, 'GET', f"/api/runs/{queued['id']}")
    assert run['status'] == 'done'
    assert run['finished'] == 1
    assert run['stopped'] == 1
    assert run['processed'] == 2

    code, table = call(base, 'GET', f"/api/runs/{queued['id']}/rows?status=all&limit=10")
    assert table['total'] == 2
    by_stop = {row['params']['stopLossPct']: row for row in table['rows']}
    done = by_stop[1]
    stopped = by_stop[50]
    assert done['status'] == 'done'
    assert done['Trades'] == 1
    assert done['Profit'] < 0
    assert done['params']['direction'] == 'long'
    assert month(done, '2020-02')['profit'] == 0
    assert stopped['status'] == 'stopped'
    assert stopped['reason'].startswith('просадка от стартового депозита')
    assert stopped['MaxDraw'] > 250
    assert month(stopped, '2020-02')['profit'] is None

    code, filtered = call(base, 'GET', f"/api/runs/{queued['id']}/rows?status=done&minProfit=0&minWinrate=1")
    assert filtered['total'] == 0
    code, visible = call(base, 'GET', f"/api/runs/{queued['id']}/rows?status=done")
    assert visible['total'] == 1

    code, moved = call(base, 'POST', f"/api/runs/{queued['id']}/cutoff", {
        'metric': 'Profit',
        'op': '>=',
        'value': 0,
    })
    assert moved == {'moved': 1}
    code, rejected = call(base, 'GET', f"/api/runs/{queued['id']}/rows?status=rejected&limit=10")
    assert rejected['total'] == 2
    discarded = next(row for row in rejected['rows'] if row['status'] == 'discarded')
    assert discarded['reason'].startswith('порог Profit >= 0')
    code, restored = call(base, 'POST', f"/api/runs/{queued['id']}/restore")
    assert restored == {'restored': 1}
    code, after = call(base, 'GET', f"/api/runs/{queued['id']}/rows?status=rejected&limit=10")
    assert after['total'] == 1
    assert after['rows'][0]['status'] == 'stopped'

    code, denied = call(base, 'POST', '/api/drafts', {'runId': queued['id'], 'rowIds': [stopped['id']]})
    assert code == 400
    assert 'досчитанн' in denied['error']
    code, drafts = call(base, 'POST', '/api/drafts', {'runId': queued['id'], 'rowIds': [done['id']]})
    assert code == 201, drafts
    config = drafts['drafts'][0]['config']
    metrics = drafts['drafts'][0]['metrics']
    assert config['strategyId'] == 'ma-cross'
    assert config['market'] == 'binance-usd-m'
    assert config['params']['entryOnClose'] is True
    assert config['params']['direction'] == 'long'
    assert config['lotStep'] == 0.001
    assert metrics['earlyStopPct'] == 25
    assert metrics['runId'] == queued['id']
    assert metrics['Trades'] == 1

    code, book_denied = call(base, 'POST', '/api/books', {
        'name': 'проверка',
        'kind': 'research',
        'band': 'short',
        'runId': queued['id'],
        'rowIds': [stopped['id']],
    })
    assert code == 400
    assert book_denied['error'] == 'в сводную берётся только досчитанная строка'
    code, books = call(base, 'GET', '/api/books')
    assert books['books'] == []
    code, book = call(base, 'POST', '/api/books', {
        'name': 'проверка',
        'kind': 'research',
        'band': 'short',
        'runId': queued['id'],
        'rowIds': [done['id']],
    })
    assert code == 201, book
    assert book['rows'] == 1

    code, child = call(base, 'POST', '/api/runs', run_body(
        series['id'],
        grid_axes(stop_from=1, stop_to=1, stop_step=0.3, direction=['long'], cross=['direct'], exit_mode=['tp_sl']),
        parentRunId=queued['id'],
        parentRowIds=[done['id']],
    ))
    assert code == 201, child
    assert child['parentRunId'] == queued['id']
    assert child['parentRowIds'] == [done['id']]
    assert child['hypothesisId'] is None
    assert child['status'] == 'queued'
    assert child['total'] == 1
    drain(child['id'])
    code, refined = call(base, 'GET', f"/api/runs/{child['id']}")
    assert refined['status'] == 'done'
    assert refined['finished'] == 1
    assert refined['stopped'] == 0
    assert refined['parentRunId'] == queued['id']

    code, btc = call(base, 'POST', '/api/hypotheses/queue', run_body(
        series['id'],
        grid_axes(direction=['short']),
        hypothesisId='ma-short-alt',
    ))
    assert code == 400
    assert 'BTC' in btc['error']
    code, unknown = call(base, 'POST', '/api/hypotheses/queue', run_body(
        series['id'],
        grid_axes(),
        hypothesisId='нет',
    ))
    assert code == 400
    code, foreign = call(base, 'POST', '/api/runs', run_body(series['id'], grid_axes(), strategyId='bollinger'))
    assert code == 400
    assert 'реестре' in foreign['error']
    code, empty = call(base, 'POST', '/api/runs', run_body(series['id'], []))
    assert code == 400
    assert 'пуст' in empty['error']
    code, backwards = call(base, 'POST', '/api/runs', run_body(series['id'], grid_axes(fast=10, slow=3)))
    assert code == 400
    assert 'нет ни одной комбинации' in backwards['error']


def test_download_errors_and_incremental_tail_stay_on_the_mock(api):
    base, exchange = api
    candles = exchange.candles
    first = download(base, 'BTCUSDT')
    assert first['status'] == 'ready'
    assert first['bars'] == 6
    first_kline_count = len([url for url in exchange.urls if '/klines' in url])
    assert first_kline_count >= 1
    jan1 = ms(2020, 1, 1)
    assert any(f'startTime={jan1}' in url for url in exchange.urls if '/klines' in url)

    again = download(base, 'BTCUSDT')
    assert again['status'] == 'ready'
    assert again['bars'] == 6
    fresh = [url for url in exchange.urls if '/klines' in url][first_kline_count:]
    starts = [int(urllib.parse.parse_qs(urllib.parse.urlparse(url).query)['startTime'][0]) for url in fresh]
    assert jan1 in starts
    assert candles[0][0] not in starts
    assert ms(2020, 2, 15) + 300_000 in starts

    exchange.rules_fail.add('ETHUSDT')
    eth = download(base, 'ETHUSDT')
    assert eth['status'] == 'ready'
    assert eth['error'] is None
    assert eth['lotStep'] is None
    assert eth['minQty'] is None
    assert eth['bars'] == 6

    exchange.kline_fail.add('SOLUSDT')
    sol = download(base, 'SOLUSDT')
    assert sol['status'] == 'error'
    assert 'Binance' in sol['error']

    exchange.kline_empty.add('XRPUSDT')
    empty = download(base, 'XRPUSDT')
    assert empty['status'] == 'error'
    assert 'свечи' in empty['error']

    for url in exchange.urls:
        parsed = urllib.parse.urlparse(url)
        assert parsed.netloc == 'fapi.binance.com'
        assert parsed.path in ('/fapi/v1/klines', '/fapi/v1/exchangeInfo')
        assert 'signature' not in url


def test_cancel_finishes_the_open_batch_and_stays_cancelled(api):
    base, _exchange = api
    series = download(base, 'BTCUSDT')
    assert series['status'] == 'ready'
    code, queued = call(base, 'POST', '/api/runs', run_body(
        series['id'],
        grid_axes(stop_from=1, stop_to=1, stop_step=1, direction=['long'], cross=['direct'], exit_mode=['tp_sl']),
    ))
    assert code == 201, queued
    assert queued['status'] == 'queued'
    assert queued['total'] == 1

    db = connect()
    try:
        assert claim_next_run(db) == queued['id']
    finally:
        db.close()
    code, cancelled = call(base, 'POST', f"/api/runs/{queued['id']}/cancel")
    assert cancelled['status'] == 'cancelled'

    db = connect()
    try:
        execute_run(db, queued['id'])
    finally:
        db.close()
    code, run = call(base, 'GET', f"/api/runs/{queued['id']}")
    assert run['status'] == 'cancelled'
    code, table = call(base, 'GET', f"/api/runs/{queued['id']}/rows?status=all&limit=10")
    assert table['total'] == 1
    assert table['rows'][0]['status'] == 'done'
