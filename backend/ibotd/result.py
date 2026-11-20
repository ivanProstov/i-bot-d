"""Строка результата прогона.

Имена правее MaxDraw в спеке не заданы. Ниже те имена, которыми таблица и xlsx
уже пользуются. orderLife — заголовок колонки lifetimeBars, не отдельное поле конфига.
"""

STORAGE_TO_PUBLIC = (
    ('profit', 'Profit'),
    ('profit_fact', 'ProfitFact'),
    ('winrate', 'Winrate'),
    ('trades', 'Trades'),
    ('max_draw', 'MaxDraw'),
    ('max_draw_pct', 'MaxDrawPct'),
    ('max_draw_at', 'MaxDrawAt'),
    ('worst_trade', 'WorstTrade'),
    ('worst_trade_at', 'WorstTradeAt'),
    ('worst_open', 'WorstOpen'),
    ('worst_open_at', 'WorstOpenAt'),
    ('positive_month_share', 'positiveMonthShare'),
    ('best_month_share', 'bestMonthShare'),
)

PARAM_COLUMNS = (
    ('fastType', 'fastType'),
    ('fastPeriod', 'fastPeriod'),
    ('slowType', 'slowType'),
    ('slowPeriod', 'slowPeriod'),
    ('offsetPct', 'offsetPct'),
    ('lifetimeBars', 'orderLife'),
    ('takeProfitPct', 'takeProfitPct'),
    ('stopLossPct', 'stopLossPct'),
    ('minSignalGapBars', 'minSignalGapBars'),
    ('direction', 'direction'),
    ('crossMode', 'crossMode'),
    ('exitMode', 'exitMode'),
)

METRIC_COLUMNS = (
    ('Profit', 'Profit'),
    ('ProfitFact', 'ProfitFact'),
    ('Winrate', 'Winrate'),
    ('Trades', 'Trades'),
    ('MaxDraw', 'MaxDraw'),
    ('MaxDrawPct', 'MaxDrawPct'),
    ('MaxDrawAt', 'MaxDrawAt'),
    ('WorstTrade', 'WorstTrade'),
    ('WorstTradeAt', 'WorstTradeAt'),
    ('WorstOpen', 'WorstOpen'),
    ('WorstOpenAt', 'WorstOpenAt'),
    ('positiveMonthShare', 'plusMonthsPct'),
    ('bestMonthShare', 'bestMonthPct'),
)


def public_result(row_id, status, reason, params, stored, month_keys, month_values):
    body = {
        'id': row_id,
        'status': status,
        'reason': reason,
        'params': params,
    }
    for storage, public in STORAGE_TO_PUBLIC:
        body[public] = stored[storage]
    body['months'] = [
        {'month': month, 'profit': month_values[index] if index < len(month_values) else None}
        for index, month in enumerate(month_keys)
    ]
    return body
