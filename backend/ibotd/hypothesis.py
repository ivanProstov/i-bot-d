"""Шесть гипотез пересечения скользящих из раздела 4.6.

Соответствие «вар 1 / вар 2 / вар 3» конкретному правилу в спеке не задано
и в этом пакете не назначается. Очередь только подставляет названные оси.
"""

HYPOTHESES = {
    'ma-cross': (
        {
            'id': 'ma-direct-both-tpsl',
            'title': 'Прямое пересечение, тейк и стоп, лонг и шорт',
            'detail': 'То, что в спеке уже отобрано в бой.',
            'pin': {'direction': 'both', 'crossMode': 'direct', 'exitMode': 'tp_sl'},
            'rejectBtc': False,
        },
        {
            'id': 'ma-direct-flip',
            'title': 'Прямое пересечение, переворот на обратном пересечении',
            'detail': 'Без тесного тейка. Широкий стоп берётся из диапазона стопа на сетке, число в спеке не задано.',
            'pin': {'direction': 'both', 'crossMode': 'direct', 'exitMode': 'flip_on_cross'},
            'rejectBtc': False,
        },
        {
            'id': 'ma-direct-long-tpsl',
            'title': 'Прямое пересечение, тейк и стоп, только лонг',
            'detail': 'Та же связка тейка и стопа, направление только лонг.',
            'pin': {'direction': 'long', 'crossMode': 'direct', 'exitMode': 'tp_sl'},
            'rejectBtc': False,
        },
        {
            'id': 'ma-direct-short-tpsl',
            'title': 'Прямое пересечение, тейк и стоп, только шорт',
            'detail': 'Та же связка тейка и стопа, направление только шорт.',
            'pin': {'direction': 'short', 'crossMode': 'direct', 'exitMode': 'tp_sl'},
            'rejectBtc': False,
        },
        {
            'id': 'ma-reverse',
            'title': 'Обратное пересечение',
            'detail': 'Лонг, когда быстрая пересекает медленную сверху вниз, и зеркало для шорта. Выход остаётся тем, что включено на сетке.',
            'pin': {'direction': 'both', 'crossMode': 'reverse'},
            'rejectBtc': False,
        },
        {
            'id': 'ma-short-alt',
            'title': 'Только шорт не на битке',
            'detail': 'Направление только шорт. Символ, который начинается с BTC, в очередь не ставится. Список слабых альтов в спеке не задан.',
            'pin': {'direction': 'short'},
            'rejectBtc': True,
        },
    ),
}


def hypotheses_for(strategy_id):
    return [dict(item, pin=dict(item['pin'])) for item in HYPOTHESES.get(strategy_id, ())]


def find_hypothesis(hypothesis_id):
    if not isinstance(hypothesis_id, str):
        return None
    for strategy_id, items in HYPOTHESES.items():
        for item in items:
            if item['id'] == hypothesis_id:
                return {'strategyId': strategy_id, **item, 'pin': dict(item['pin'])}
    return None


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
