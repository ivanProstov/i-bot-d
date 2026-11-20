"""Публичные свечи и правила символа Binance USD-M.

Тестировщик вызывает только эти публичные методы, без ключа:
`GET /fapi/v1/klines` и `GET /fapi/v1/exchangeInfo` на `https://fapi.binance.com`.
Тестовый хост, заявки, позиции, хедж и пользовательский поток этот модуль не вызывает.
Ключа у модуля нет.
"""

import json
import os
import ssl
import time
import urllib.error
import urllib.request

ORIGIN = 'https://fapi.binance.com'


def fetch_klines_page(symbol, interval, start_time, end_time, opener=None, sleep=None):
    url = f'{ORIGIN}/fapi/v1/klines?symbol={symbol}&interval={interval}&startTime={int(start_time)}&endTime={int(end_time)}&limit=1500'
    payload = _fetch_json(url, opener=opener, sleep=sleep)
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


def fetch_symbol_rules(symbol, opener=None, sleep=None):
    payload = _fetch_json(f'{ORIGIN}/fapi/v1/exchangeInfo?symbol={symbol}', opener=opener, sleep=sleep)
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


def _fetch_json(url, opener=None, sleep=None):
    last_error = 'нет ответа'
    pause = sleep or time.sleep
    fetch = opener or _urlopen
    for attempt in range(1, 4):
        try:
            fetched = fetch(url)
            status, raw = fetched[0], fetched[1]
            reason = fetched[2] if len(fetched) > 2 and fetched[2] else f'HTTP {status}'
        except urllib.error.URLError as error:
            last_error = str(error.reason)
            pause(attempt)
            continue
        if status in (429, 418) or status >= 500:
            last_error = f'HTTP {status}'
            pause(attempt)
            continue
        if status >= 400:
            raise ValueError(f'Binance {status}: {_error_message(raw, reason)}')
        try:
            return json.loads(raw.decode())
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError('Binance вернул не JSON') from error
    raise ValueError(f'Binance не ответил: {last_error}')


def _urlopen(url):
    request = urllib.request.Request(url, headers={'User-Agent': 'i-bot-tester'})
    try:
        with urllib.request.urlopen(request, timeout=30, context=_ssl_context()) as response:
            return response.status, response.read(), ''
    except urllib.error.HTTPError as error:
        return error.code, error.read(), str(error.reason)


def _error_message(raw, fallback):
    try:
        parsed = json.loads(raw.decode())
    except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
        return fallback
    if isinstance(parsed, dict) and parsed.get('msg'):
        return parsed['msg']
    return fallback


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
    return parsed if parsed == parsed and parsed not in (float('inf'), float('-inf')) else None

