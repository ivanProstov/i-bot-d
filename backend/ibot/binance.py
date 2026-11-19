import json
import os
import ssl
import time
import urllib.error
import urllib.request

from ibot.catalog import INTERVAL_MS

ORIGIN = 'https://fapi.binance.com'


def fetch_klines_page(symbol, interval, start_time, end_time):
    url = f'{ORIGIN}/fapi/v1/klines?symbol={symbol}&interval={interval}&startTime={int(start_time)}&endTime={int(end_time)}&limit=1500'
    payload = _fetch_json(url)
    if not isinstance(payload, list):
        raise ValueError('Binance вернул не список свечей')
    candles = []
    for row in payload:
        if not isinstance(row, list):
            raise ValueError('свеча Binance не является массивом')
        candles.append({
            'openTime': float(row[0]),
            'open': float(row[1]),
            'high': float(row[2]),
            'low': float(row[3]),
            'close': float(row[4]),
            'volume': float(row[5]),
        })
    return candles


def fetch_symbol_rules(symbol):
    payload = _fetch_json(f'{ORIGIN}/fapi/v1/exchangeInfo?symbol={symbol}')
    symbols = payload.get('symbols') if isinstance(payload, dict) else None
    if not symbols:
        raise ValueError(f'в exchangeInfo нет символа {symbol}')
    filters = symbols[0].get('filters') or []

    def find(name):
        return next((item for item in filters if item.get('filterType') == name), None)

    lot = find('LOT_SIZE') or {}
    price = find('PRICE_FILTER') or {}
    notional = find('MIN_NOTIONAL') or find('NOTIONAL') or {}
    return {
        'minQty': _number(lot.get('minQty')),
        'stepSize': _number(lot.get('stepSize')),
        'tickSize': _number(price.get('tickSize')),
        'minNotional': _number(notional.get('notional') or notional.get('minNotional')),
    }


def interval_ms(interval):
    if interval not in INTERVAL_MS:
        raise ValueError(f'таймфрейм {interval} не из списка USD-M')
    return INTERVAL_MS[interval]


def _fetch_json(url):
    last_error = 'нет ответа'
    context = _ssl_context()
    for attempt in range(1, 4):
        request = urllib.request.Request(url, headers={'User-Agent': 'i-bot-tester'})
        try:
            with urllib.request.urlopen(request, timeout=30, context=context) as response:
                return json.loads(response.read().decode())
        except urllib.error.HTTPError as error:
            if error.code in (429, 418) or error.code >= 500:
                last_error = f'HTTP {error.code}'
                time.sleep(attempt)
                continue
            body = error.read().decode()
            try:
                msg = json.loads(body).get('msg') or error.reason
            except json.JSONDecodeError:
                msg = error.reason
            raise ValueError(f'Binance {error.code}: {msg}') from error
        except urllib.error.URLError as error:
            last_error = str(error.reason)
            time.sleep(attempt)
            continue
    raise ValueError(f'Binance не ответил: {last_error}')


def _ssl_context():
    for path in ('/etc/ssl/cert.pem', '/etc/ssl/certs/ca-certificates.crt'):
        if os.path.isfile(path):
            return ssl.create_default_context(cafile=path)
    return ssl.create_default_context()


def _number(value):
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math_isfinite(parsed) else None


def math_isfinite(value):
    return value == value and value not in (float('inf'), float('-inf'))
