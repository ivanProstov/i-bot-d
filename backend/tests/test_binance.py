import json
from pathlib import Path

import pytest

from ibotd.binance import fetch_klines_page, fetch_symbol_rules


def test_klines_and_rules_parse_a_fake_exchange():
    def opener(url):
        if 'klines' in url:
            assert 'symbol=BTCUSDT' in url
            assert 'interval=5m' in url
            assert url.startswith('https://fapi.binance.com/fapi/v1/klines?')
            body = [[1, '10', '11', '9', '10.5', '100']]
            return 200, json.dumps(body).encode()
        body = {
            'symbols': [{
                'filters': [
                    {'filterType': 'LOT_SIZE', 'minQty': '0.001', 'stepSize': '0.001'},
                    {'filterType': 'PRICE_FILTER', 'tickSize': '0.10'},
                    {'filterType': 'MIN_NOTIONAL', 'notional': '5'},
                ],
            }],
        }
        return 200, json.dumps(body).encode()

    candles = fetch_klines_page('BTCUSDT', '5m', 0, 10, opener=opener)
    assert candles == [{
        'openTime': 1.0, 'open': 10.0, 'high': 11.0, 'low': 9.0, 'close': 10.5, 'volume': 100.0,
    }]
    rules = fetch_symbol_rules('BTCUSDT', opener=opener)
    assert rules == {'minQty': 0.001, 'stepSize': 0.001, 'tickSize': 0.1, 'minNotional': 5.0}


def test_exchange_errors_retry_only_server_failures():
    calls = {'n': 0}

    def fail_once(url):
        calls['n'] += 1
        if calls['n'] == 1:
            return 500, b''
        return 200, b'[]'

    slept = []
    assert fetch_klines_page('BTCUSDT', '1m', 0, 1, opener=fail_once, sleep=slept.append) == []
    assert slept == [1]

    def rejected(url):
        calls['rejected'] = calls.get('rejected', 0) + 1
        return 400, b'{"msg":"bad"}'

    with pytest.raises(ValueError, match='Binance 400: bad'):
        fetch_klines_page('BTCUSDT', '1m', 0, 1, opener=rejected, sleep=slept.append)
    assert calls['rejected'] == 1
    with pytest.raises(ValueError, match='не список свечей'):
        fetch_klines_page('BTCUSDT', '1m', 0, 1, opener=lambda url: (200, b'{}'))


def test_module_does_not_invent_trade_paths():
    text = Path('backend/ibotd/binance.py').read_text()
    for token in ('/order', 'listenKey', 'positionRisk', 'positionSide', 'fstream', 'api_key', 'apiKey'):
        assert token not in text
    tester = '\n'.join(path.read_text() for path in Path('backend/ibot').rglob('*.py'))
    assert 'place_order' not in tester
    assert '/fapi/v1/order' not in tester
