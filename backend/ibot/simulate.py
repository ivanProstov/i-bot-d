import math
from datetime import datetime, timezone

from ibot.grid import series_key


def month_keys_of(open_time):
    return _month_span(open_time)


def simulate(plugin, series, params, settings, cache=None):
    close = series['close']
    n = len(close)
    month_keys = _month_span(series['openTime'])
    month_index = {month: index for index, month in enumerate(month_keys)}
    month_profit = [0.0 for _ in month_keys]
    month_known = [True for _ in month_keys]
    key = series_key(plugin.series_params, params)
    if cache is not None and cache.get('key') == key:
        prepared = cache['prepared']
    else:
        prepared = plugin.prepare(series, params)
        if cache is not None:
            cache['key'] = key
            cache['prepared'] = prepared
    memory = plugin.create_memory()
    deposit = settings['deposit']
    realized = 0.0
    gross_profit = 0.0
    gross_loss = 0.0
    trades = 0
    wins = 0
    worst_trade = None
    worst_trade_at = None
    worst_open = None
    worst_open_at = None
    peak = deposit
    max_draw = 0.0
    max_draw_at = None
    position = None
    pending = None
    stopped = False
    stop_at = max(0, n - 1)

    def book_trade(pnl, open_time):
        nonlocal realized, trades, wins, gross_profit, gross_loss, worst_trade, worst_trade_at
        realized += pnl
        trades += 1
        if pnl > 0:
            wins += 1
            gross_profit += pnl
        elif pnl < 0:
            gross_loss += -pnl
        if worst_trade is None or pnl < worst_trade:
            worst_trade = pnl
            worst_trade_at = _day(open_time)
        month = _day(open_time)[:7]
        index = month_index.get(month)
        if index is not None:
            month_profit[index] += pnl

    for index in range(n):
        high = series['high'][index]
        low = series['low'][index]
        price = close[index]
        open_time = series['openTime'][index]
        filled_this_bar = False
        if pending and pending['from'] <= index <= pending['until']:
            touched = low <= pending['price'] if pending['side'] == 'long' else high >= pending['price']
            if touched:
                position = _open_position(pending['side'], pending['price'], pending['stop'], pending['take'], index, settings)
                pending = None
                filled_this_bar = position is not None
            elif index == pending['until']:
                pending = None
        if position and index >= position['protectFrom']:
            stop_hit = low <= position['stop'] if position['side'] == 'long' else high >= position['stop']
            take_hit = position['take'] is not None and (high >= position['take'] if position['side'] == 'long' else low <= position['take'])
            if stop_hit or (take_hit and not filled_this_bar):
                exit_price = position['stop'] if stop_hit else position['take']
                book_trade(_close_position(position, exit_price), open_time)
                position = None
        adverse = _mark_adverse(position, index, low, high, price, realized, deposit)
        drawdown = peak - adverse['equityWorst']
        if drawdown > max_draw:
            max_draw = drawdown
            max_draw_at = _day(open_time)
        if adverse['equityMark'] > peak:
            peak = adverse['equityMark']
        if adverse['worstUnrealized'] is not None and (worst_open is None or adverse['worstUnrealized'] < worst_open):
            worst_open = adverse['worstUnrealized']
            worst_open_at = _day(open_time)
        if deposit > 0 and deposit - adverse['equityWorst'] >= deposit * settings['earlyStopPct'] / 100:
            stopped = True
            stop_at = index
            break
        ctx = {
            'index': index,
            'openTime': open_time,
            'open': series['open'][index],
            'high': high,
            'low': low,
            'close': price,
            'volume': series['volume'][index],
            'positionSide': position['side'] if position else None,
            'positionEntry': position['entry'] if position else 0,
            'pending': pending is not None,
        }
        action = plugin.on_bar(prepared, ctx, params, memory)
        if not action:
            continue
        if action['type'] == 'cancel_entry':
            pending = None
            continue
        if action['type'] == 'stop' and position:
            position['stop'] = action['price']
            continue
        if action['type'] == 'take' and position:
            position['take'] = action['price']
            continue
        if action['type'] == 'flip':
            if position:
                book_trade(_close_position(position, action['price']), open_time)
                position = None
            position = _open_position(action['side'], action['price'], action['stopPrice'], action['takePrice'], index + 1, settings)
            continue
        if action['type'] == 'limit_entry' and not position:
            if action['price'] == price:
                position = _open_position(action['side'], price, action['stopPrice'], action['takePrice'], index + 1, settings)
                pending = None
            else:
                pending = {
                    'side': action['side'],
                    'price': action['price'],
                    'stop': action['stopPrice'],
                    'take': action['takePrice'],
                    'from': index + 1,
                    'until': index + action['lifetimeBars'],
                }
    if stopped and series['openTime']:
        stop_month = _day(series['openTime'][stop_at])[:7]
        for index, month in enumerate(month_keys):
            if month > stop_month:
                month_known[index] = False
                month_profit[index] = 0
    months = [{'month': month, 'profit': month_profit[index] if month_known[index] else None} for index, month in enumerate(month_keys)]
    computed = [item for item in months if item['profit'] is not None]
    positive = len([item for item in computed if item['profit'] > 0])
    profit_sum = sum(item['profit'] for item in computed)
    best = max((item['profit'] for item in computed), default=0)
    return {
        'status': 'stopped' if stopped else 'done',
        'reason': f"просадка от стартового депозита >= {settings['earlyStopPct']}%" if stopped else None,
        'profit': realized,
        'profitFact': gross_profit / gross_loss if gross_loss > 0 else None,
        'winrate': (wins / trades) * 100 if trades else None,
        'trades': trades,
        'maxDraw': max_draw,
        'maxDrawPct': (max_draw / deposit) * 100 if deposit > 0 else 0,
        'maxDrawAt': max_draw_at,
        'worstTrade': worst_trade,
        'worstTradeAt': worst_trade_at,
        'worstOpen': worst_open,
        'worstOpenAt': worst_open_at,
        'positiveMonthShare': (positive / len(computed)) * 100 if computed else None,
        'bestMonthShare': (best / profit_sum) * 100 if profit_sum > 0 else None,
        'months': months,
    }


def _open_position(side, price, stop, take, protect_from, settings):
    if not price > 0 or not settings['orderNotional'] > 0:
        return None
    qty = _round_lot(settings['orderNotional'] / price, settings.get('lotStep'))
    if not qty > 0:
        return None
    if settings.get('minQty') is not None and qty < settings['minQty']:
        return None
    return {'side': side, 'entry': price, 'qty': qty, 'stop': stop, 'take': take, 'protectFrom': protect_from}


def _close_position(position, exit_price):
    if position['side'] == 'long':
        return (exit_price - position['entry']) * position['qty']
    return (position['entry'] - exit_price) * position['qty']


def _mark_adverse(position, index, low, high, close, realized, deposit):
    if not position or index < position['protectFrom']:
        equity = deposit + realized
        return {'equityMark': equity, 'equityWorst': equity, 'worstUnrealized': None}
    if position['side'] == 'long':
        worst = (low - position['entry']) * position['qty']
        mark = (close - position['entry']) * position['qty']
    else:
        worst = (position['entry'] - high) * position['qty']
        mark = (position['entry'] - close) * position['qty']
    return {'equityMark': deposit + realized + mark, 'equityWorst': deposit + realized + worst, 'worstUnrealized': worst}


def _round_lot(qty, step):
    if step is None or not step > 0:
        return qty
    text = f'{step:.12f}'.rstrip('0').rstrip('.')
    decimals = 0 if '.' not in text else len(text.split('.')[1])
    units = math.floor(qty / step + 1e-9)
    return round(units * step, decimals)


def _day(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime('%Y-%m-%d')


def _month_span(open_time):
    if not len(open_time):
        return []
    start = _day(open_time[0])[:7]
    end = _day(open_time[len(open_time) - 1])[:7]
    out = [start]
    cursor = start
    while cursor < end:
        cursor = _next_month(cursor)
        out.append(cursor)
    return out


def _next_month(month):
    year, value = [int(part) for part in month.split('-')]
    value += 1
    if value == 13:
        value = 1
        year += 1
    return f'{year}-{value:02d}'
