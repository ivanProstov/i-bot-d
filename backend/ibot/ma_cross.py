from ibot.averages import crosses, moving_average


def _num(params, key):
    value = params.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f'параметр {key} должен быть числом')
    return float(value)


def _text(params, key):
    value = params.get(key)
    if not isinstance(value, str):
        raise ValueError(f'параметр {key} должен быть строкой')
    return value


def _ma(value):
    if value in ('SMA', 'EMA', 'SMMA', 'WMA', 'VWMA'):
        return value
    raise ValueError(f'неизвестный тип средней {value}')


def _side_from_cross(cross, mode):
    if mode == 'direct':
        return 'long' if cross > 0 else 'short'
    return 'short' if cross > 0 else 'long'


def _limit_price(close, side, offset_pct):
    if side == 'long':
        return close * (1 - offset_pct / 100)
    return close * (1 + offset_pct / 100)


def _stop_price(price, side, stop_pct):
    if side == 'long':
        return price * (1 - stop_pct / 100)
    return price * (1 + stop_pct / 100)


def _take_price(price, side, take_pct):
    if side == 'long':
        return price * (1 + take_pct / 100)
    return price * (1 - take_pct / 100)


class MaCross:
    series_params = ['fastType', 'fastPeriod', 'slowType', 'slowPeriod']
    constraint = {'left': 'fastPeriod', 'op': '<', 'right': 'slowPeriod'}

    def create_memory(self):
        return {'lastSignal': -1_000_000_000}

    def prepare(self, series, params):
        fast = moving_average(_ma(_text(params, 'fastType')), series['close'], series['volume'], int(_num(params, 'fastPeriod')))
        slow = moving_average(_ma(_text(params, 'slowType')), series['close'], series['volume'], int(_num(params, 'slowPeriod')))
        return {'cross': crosses(fast, slow)}

    def on_bar(self, prepared, ctx, params, memory):
        cross = prepared['cross'][ctx['index']]
        if not cross:
            return None
        direction = _text(params, 'direction')
        side = _side_from_cross(cross, _text(params, 'crossMode'))
        if direction != 'both' and direction != side:
            return None
        if ctx['index'] - memory['lastSignal'] <= _num(params, 'minSignalGapBars'):
            return None
        offset_pct = _num(params, 'offsetPct')
        stop_pct = _num(params, 'stopLossPct')
        take_pct = _num(params, 'takeProfitPct')
        lifetime = _num(params, 'lifetimeBars')
        exit_mode = _text(params, 'exitMode')
        if ctx['positionSide'] and exit_mode == 'flip_on_cross' and ctx['positionSide'] != side:
            memory['lastSignal'] = ctx['index']
            return {
                'type': 'flip',
                'side': side,
                'price': ctx['close'],
                'stopPrice': _stop_price(ctx['close'], side, stop_pct),
                'takePrice': None,
            }
        if ctx['positionSide']:
            return None
        memory['lastSignal'] = ctx['index']
        price = _limit_price(ctx['close'], side, offset_pct)
        return {
            'type': 'limit_entry',
            'side': side,
            'price': price,
            'lifetimeBars': lifetime,
            'stopPrice': _stop_price(price, side, stop_pct),
            'takePrice': _take_price(price, side, take_pct) if exit_mode == 'tp_sl' else None,
        }


PLUGIN = MaCross()
