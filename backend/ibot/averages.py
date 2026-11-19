import math


def moving_average(kind, close, volume, period):
    if period < 1 or int(period) != period:
        raise ValueError(f'период средней должен быть целым числом от 1, получено {period}')
    period = int(period)
    if kind == 'SMA':
        return _sma(close, period)
    if kind == 'EMA':
        return _ema(close, period)
    if kind == 'SMMA':
        return _smma(close, period)
    if kind == 'WMA':
        return _wma(close, period)
    return _vwma(close, volume, period)


def _empty(length):
    return [math.nan] * length


def _sma(close, period):
    out = _empty(len(close))
    total = 0.0
    for index, price in enumerate(close):
        total += price
        if index >= period:
            total -= close[index - period]
        if index >= period - 1:
            out[index] = total / period
    return out


def _ema(close, period):
    out = _empty(len(close))
    if len(close) < period:
        return out
    prev = sum(close[:period]) / period
    out[period - 1] = prev
    k = 2 / (period + 1)
    for index in range(period, len(close)):
        prev = close[index] * k + prev * (1 - k)
        out[index] = prev
    return out


def _smma(close, period):
    out = _empty(len(close))
    if len(close) < period:
        return out
    prev = sum(close[:period]) / period
    out[period - 1] = prev
    for index in range(period, len(close)):
        prev = (prev * (period - 1) + close[index]) / period
        out[index] = prev
    return out


def _wma(close, period):
    out = _empty(len(close))
    if len(close) < period:
        return out
    denom = period * (period + 1) / 2
    weighted = 0.0
    total = 0.0
    for index in range(period):
        weighted += close[index] * (index + 1)
        total += close[index]
    out[period - 1] = weighted / denom
    for index in range(period, len(close)):
        leaving = close[index - period]
        weighted = weighted - total + period * close[index]
        total = total - leaving + close[index]
        out[index] = weighted / denom
    return out


def _vwma(close, volume, period):
    out = _empty(len(close))
    sum_pv = 0.0
    sum_v = 0.0
    for index, price in enumerate(close):
        sum_pv += price * volume[index]
        sum_v += volume[index]
        if index >= period:
            sum_pv -= close[index - period] * volume[index - period]
            sum_v -= volume[index - period]
        if index >= period - 1:
            out[index] = math.nan if sum_v == 0 else sum_pv / sum_v
    return out


def crosses(fast, slow):
    out = [0] * len(fast)
    for index in range(1, len(fast)):
        prev_fast, prev_slow = fast[index - 1], slow[index - 1]
        next_fast, next_slow = fast[index], slow[index]
        if any(math.isnan(value) for value in (prev_fast, prev_slow, next_fast, next_slow)):
            continue
        if prev_fast <= prev_slow and next_fast > next_slow:
            out[index] = 1
        elif prev_fast >= prev_slow and next_fast < next_slow:
            out[index] = -1
    return out
