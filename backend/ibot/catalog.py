CATALOG = [
    {'id': 'ma-cross', 'name': 'Пересечение скользящих', 'implemented': True, 'where': 'раздел 4.3'},
    {'id': 'bollinger', 'name': 'Полосы Боллинджера', 'implemented': False, 'where': 'раздел 7.1'},
    {'id': 'bollinger-dump', 'name': 'Пролив от средней линии Боллинджера', 'implemented': False, 'where': 'раздел 7.2'},
]

MA_TYPES = ['SMA', 'EMA', 'SMMA', 'WMA', 'VWMA']

MA_PARAMS = [
    {'key': 'fastType', 'label': 'Тип быстрой', 'type': 'enum', 'default': 'SMA', 'grid': True, 'options': MA_TYPES},
    {'key': 'fastPeriod', 'label': 'Период быстрой', 'type': 'number', 'unit': 'бары', 'default': 10, 'grid': True, 'integer': True, 'min': 1},
    {'key': 'slowType', 'label': 'Тип медленной', 'type': 'enum', 'default': 'SMA', 'grid': True, 'options': MA_TYPES},
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
    {'key': 'orderNotional', 'label': 'Размер заявки', 'type': 'number', 'unit': 'USDT', 'default': 1000, 'grid': False, 'min': 0},
    {'key': 'entryOnClose', 'label': 'Сигнал по закрытию бара', 'type': 'bool', 'default': True, 'grid': False},
]

MA_HYPOTHESES = [
    {'id': 'ma-direct-both-tpsl', 'title': 'Прямое пересечение, тейк и стоп, лонг и шорт', 'detail': 'То, что в спеке уже отобрано в бой.', 'pin': {'direction': 'both', 'crossMode': 'direct', 'exitMode': 'tp_sl'}, 'rejectBtc': False},
    {'id': 'ma-direct-flip', 'title': 'Прямое пересечение, переворот на обратном пересечении', 'detail': 'Без тесного тейка. Широкий стоп берётся из диапазона стопа на сетке, число в спеке не задано.', 'pin': {'direction': 'both', 'crossMode': 'direct', 'exitMode': 'flip_on_cross'}, 'rejectBtc': False},
    {'id': 'ma-direct-long-tpsl', 'title': 'Прямое пересечение, тейк и стоп, только лонг', 'detail': 'Та же связка тейка и стопа, направление только лонг.', 'pin': {'direction': 'long', 'crossMode': 'direct', 'exitMode': 'tp_sl'}, 'rejectBtc': False},
    {'id': 'ma-direct-short-tpsl', 'title': 'Прямое пересечение, тейк и стоп, только шорт', 'detail': 'Та же связка тейка и стопа, направление только шорт.', 'pin': {'direction': 'short', 'crossMode': 'direct', 'exitMode': 'tp_sl'}, 'rejectBtc': False},
    {'id': 'ma-reverse', 'title': 'Обратное пересечение', 'detail': 'Лонг, когда быстрая пересекает медленную сверху вниз, и зеркало для шорта. Выход остаётся тем, что включено на сетке.', 'pin': {'direction': 'both', 'crossMode': 'reverse'}, 'rejectBtc': False},
    {'id': 'ma-short-alt', 'title': 'Только шорт не на битке', 'detail': 'Направление только шорт. Символ, который начинается с BTC, в очередь не ставится. Список слабых альтов в спеке не задан.', 'pin': {'direction': 'short'}, 'rejectBtc': True},
]

PLAN_COLUMNS = [
    {'index': 1, 'title': 'Без индикаторов', 'cellFrom': 1, 'cellTo': 9, 'runnable': True},
    {'index': 2, 'title': 'С RSI', 'cellFrom': 10, 'cellTo': 18, 'runnable': False},
    {'index': 3, 'title': 'С MACD стандарт', 'cellFrom': 19, 'cellTo': 27, 'runnable': False},
    {'index': 4, 'title': 'С MACD 8, 17, 5', 'cellFrom': 28, 'cellTo': 36, 'runnable': False},
    {'index': 5, 'title': 'С дельтой 1d, 1h, 5m', 'cellFrom': 37, 'cellTo': 45, 'runnable': False},
    {'index': 6, 'title': 'Боллинджер дневки, вход на минутках', 'cellFrom': 46, 'cellTo': 54, 'runnable': False},
    {'index': 7, 'title': 'Боллинджер и два удачных способа', 'cellFrom': 55, 'cellTo': 63, 'runnable': False},
]

USD_M_INTERVALS = ['1m', '3m', '5m', '15m', '30m', '1h', '2h', '4h', '6h', '8h', '12h', '1d', '1w']

INTERVAL_MS = {
    '1m': 60_000, '3m': 180_000, '5m': 300_000, '15m': 900_000, '30m': 1_800_000,
    '1h': 3_600_000, '2h': 7_200_000, '4h': 14_400_000, '6h': 21_600_000, '8h': 28_800_000,
    '12h': 43_200_000, '1d': 86_400_000, '1w': 604_800_000,
}


def public_plugin():
    return {
        'id': 'ma-cross',
        'name': 'Пересечение скользящих',
        'rule': 'Быстрая средняя пересекла медленную. Прямой режим: снизу вверх лонг, сверху вниз шорт. Обратный режим меняет стороны. Выход тейком и стопом либо переворотом на противоположном пересечении. Сигнал только по закрытию бара.',
        'params': MA_PARAMS,
        'seriesParams': ['fastType', 'fastPeriod', 'slowType', 'slowPeriod'],
        'constraint': {'left': 'fastPeriod', 'op': '<', 'right': 'slowPeriod'},
    }


def plan_cell_meta(cell):
    column = next((item for item in PLAN_COLUMNS if item['cellFrom'] <= cell <= item['cellTo']), None)
    if not column:
        return None
    offset = cell - column['cellFrom']
    direction = 'только лонг' if offset < 3 else 'только шорт' if offset < 6 else 'лонг и шорт'
    return {'column': column['title'], 'direction': direction, 'variant': (offset % 3) + 1}


def apply_hypothesis(axes, hypothesis):
    next_axes = []
    for axis in axes:
        if axis.get('kind') == 'enum':
            next_axes.append({'key': axis['key'], 'kind': 'enum', 'values': list(axis.get('values') or [])})
        else:
            next_axes.append({'key': axis['key'], 'kind': 'number', 'from': axis['from'], 'to': axis['to'], 'step': axis['step']})
    for key, value in (hypothesis.get('pin') or {}).items():
        if not value:
            continue
        pinned = {'key': key, 'kind': 'enum', 'values': [value]}
        index = next((i for i, axis in enumerate(next_axes) if axis['key'] == key), -1)
        if index >= 0:
            next_axes[index] = pinned
        else:
            next_axes.append(pinned)
    return next_axes


def is_btc_symbol(symbol):
    return str(symbol).upper().startswith('BTC')


def video_ma_preset():
    return {
        'numbers': {
            'fastPeriod': {'from': '10', 'to': '350', 'step': '2'},
            'slowPeriod': {'from': '', 'to': '', 'step': '5'},
            'offsetPct': {'from': '0', 'to': '2', 'step': '0.1'},
            'lifetimeBars': {'from': '1', 'to': '10', 'step': '1'},
            'takeProfitPct': {'from': '1', 'to': '10', 'step': '0.5'},
            'stopLossPct': {'from': '1', 'to': '10', 'step': '0.5'},
            'minSignalGapBars': {'from': '0', 'to': '0', 'step': '1'},
        },
        'enums': {
            'fastType': ['SMA', 'EMA'],
            'slowType': ['SMA', 'EMA'],
            'direction': ['long', 'short', 'both'],
            'crossMode': ['direct'],
            'exitMode': ['tp_sl'],
        },
        'note': {
            'fastPeriod': 'В спеке примерно от 10 до 350, шаг 2. «Около 150 значений» — оценка автора, счёт по границам даёт 171.',
            'slowPeriod': 'Шаг 5 есть в спеке. Нижняя и верхняя границы числом в спеке не записаны, поля пустые.',
            'lifetimeBars': 'В спеке примерно от 1 до 10. Шаг в спеке не назван, в пресете шаг 1.',
            'stopLossPct': 'Отдельные границы стопа в спеке не названы. Пресет копирует первый проход тейка: от 1 до 10, шаг 0.5. Поля можно изменить.',
            'minSignalGapBars': 'Диапазон паузы в спеке не назван. У отобранных ботов был 0, поэтому в пресете одно значение 0.',
            'crossMode': 'Обратное пересечение в пресете выключено: автор его не прогонял. Галочку можно добавить.',
            'exitMode': 'В пресете включён тейк и стоп. Переворот остаётся доступной осью.',
        },
    }
