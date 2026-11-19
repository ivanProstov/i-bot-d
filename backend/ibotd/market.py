import re

MARKET = 'binance-usd-m'

USD_M_INTERVALS = ['1m', '3m', '5m', '15m', '30m', '1h', '2h', '4h', '6h', '8h', '12h', '1d', '1w']

INTERVAL_MS = {
    '1m': 60_000, '3m': 180_000, '5m': 300_000, '15m': 900_000, '30m': 1_800_000,
    '1h': 3_600_000, '2h': 7_200_000, '4h': 14_400_000, '6h': 21_600_000, '8h': 28_800_000,
    '12h': 43_200_000, '1d': 86_400_000, '1w': 604_800_000,
}


def require_interval(value):
    if value not in INTERVAL_MS:
        raise ValueError('таймфрейм не из списка USD-M')
    return value


def interval_ms(interval):
    if interval not in INTERVAL_MS:
        raise ValueError(f'таймфрейм {interval} не из списка USD-M')
    return INTERVAL_MS[interval]


def require_symbol(value):
    if not isinstance(value, str):
        raise ValueError('нужен символ')
    symbol = value.strip().upper()
    if not re.fullmatch(r'[A-Z0-9]{4,30}', symbol):
        raise ValueError('символ должен быть кодом Binance, например BTCUSDT')
    return symbol
