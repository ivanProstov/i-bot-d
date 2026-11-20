PLAN_COLUMNS = [
    {'index': 1, 'title': 'Без индикаторов', 'cellFrom': 1, 'cellTo': 9, 'runnable': True},
    {'index': 2, 'title': 'С RSI', 'cellFrom': 10, 'cellTo': 18, 'runnable': False},
    {'index': 3, 'title': 'С MACD стандарт', 'cellFrom': 19, 'cellTo': 27, 'runnable': False},
    {'index': 4, 'title': 'С MACD 8, 17, 5', 'cellFrom': 28, 'cellTo': 36, 'runnable': False},
    {'index': 5, 'title': 'С дельтой 1d, 1h, 5m', 'cellFrom': 37, 'cellTo': 45, 'runnable': False},
    {'index': 6, 'title': 'Боллинджер дневки, вход на минутках', 'cellFrom': 46, 'cellTo': 54, 'runnable': False},
    {'index': 7, 'title': 'Боллинджер и два удачных способа', 'cellFrom': 55, 'cellTo': 63, 'runnable': False},
]


def plan_cell_meta(cell):
    column = next((item for item in PLAN_COLUMNS if item['cellFrom'] <= cell <= item['cellTo']), None)
    if not column:
        return None
    offset = cell - column['cellFrom']
    direction = 'только лонг' if offset < 3 else 'только шорт' if offset < 6 else 'лонг и шорт'
    return {'column': column['title'], 'direction': direction, 'variant': (offset % 3) + 1}


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
