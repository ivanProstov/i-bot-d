from ibotd.averages import crosses, moving_average

# Минус большой, чтобы первый взятый сигнал не попал под паузу.
_NO_SIGNAL = -1_000_000_000

PARAMS = (
    {'key': 'fastType', 'label': 'Тип быстрой', 'type': 'enum', 'default': 'SMA', 'grid': True, 'options': ['SMA', 'EMA', 'SMMA', 'WMA', 'VWMA']},
    {'key': 'fastPeriod', 'label': 'Период быстрой', 'type': 'number', 'unit': 'бары', 'default': 10, 'grid': True, 'integer': True, 'min': 1},
    {'key': 'slowType', 'label': 'Тип медленной', 'type': 'enum', 'default': 'SMA', 'grid': True, 'options': ['SMA', 'EMA', 'SMMA', 'WMA', 'VWMA']},
    {'key': 'slowPeriod', 'label': 'Период медленной', 'type': 'number', 'unit': 'бары', 'default': 30, 'grid': True, 'integer': True, 'min': 1},
    {'key': 'offsetPct', 'label': 'Смещение входа', 'type': 'number', 'unit': '%', 'default': 0, 'grid': True, 'min': 0},
    {'key': 'lifetimeBars', 'label': 'Время жизни заявки', 'type': 'number', 'unit': 'бары', 'default': 5, 'grid': True, 'integer': True, 'min': 1},
    {'key': 'takeProfitPct', 'label': 'Тейк', 'type': 'number', 'unit': '%', 'default': 1, 'grid': True, 'min': 0},
    {'key': 'stopLossPct', 'label': 'Стоп', 'type': 'number', 'unit': '%', 'default': 1, 'grid': True, 'min': 0},
    {'key': 'minSignalGapBars', 'label': 'Пауза между сигналами', 'type': 'number', 'unit': 'бары', 'default': 0, 'grid': True, 'integer': True, 'min': 0},
    {'key': 'direction', 'label': 'Направление', 'type': 'enum', 'default': 'both', 'grid': True, 'options': ['long', 'short', 'both'], 'hypothesis': True},
    {'key': 'crossMode', 'label': 'Логика пересечения', 'type': 'enum', 'default': 'direct', 'grid': True, 'options': ['direct', 'reverse'], 'hypothesis': True},
    {'key': 'exitMode', 'label': 'Выход', 'type': 'enum', 'default': 'tp_sl', 'grid': True, 'options': ['tp_sl', 'flip_on_cross'], 'hypothesis': True},
    {'key': 'leverage', 'label': 'Плечо', 'type': 'number', 'default': 1, 'grid': False, 'min': 1},
    {'key': 'orderNotional', 'label': 'Размер заявки', 'type': 'number', 'unit': 'USDT', 'default': 1000, 'grid': False, 'min': 0, 'positive': True},
    {'key': 'entryOnClose', 'label': 'Сигнал по закрытию бара', 'type': 'bool', 'default': True, 'grid': False},
)


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
    """Пересечение двух средних. Сигнал только по закрытию бара.

    На бар плагин отвечает пустотой либо одним действием: лимитный вход или переворот.
    Снять вход, передвинуть тейк и передвинуть стоп этот плагин не шлёт: тейк и стоп
    стоят в действии входа, снятие лимитки делает счёт прогона по времени жизни.
    """

    id = 'ma-cross'
    name = 'Пересечение скользящих'
    rule = (
        'Быстрая средняя пересекла медленную. Прямой режим: снизу вверх лонг, сверху вниз шорт. '
        'Обратный режим меняет стороны. Выход тейком и стопом либо переворотом на противоположном пересечении. '
        'Сигнал только по закрытию бара.'
    )
    params = PARAMS
    series_params = ('fastType', 'fastPeriod', 'slowType', 'slowPeriod')
    constraint = {'left': 'fastPeriod', 'op': '<', 'right': 'slowPeriod'}
    fixed = {'entryOnClose': True}

    def create_memory(self):
        return {'lastSignal': _NO_SIGNAL}

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
