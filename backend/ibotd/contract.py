"""Конфиг бота и снимок метрик, из-за которых строку взяли в торговлю.

Торговля читает strategyId и словарь params. Чужие ключи плагина в словарь не входят.
"""

import math
import re

from ibotd.codec import ready
from ibotd.market import MARKET, require_interval, require_symbol
from ibotd.registry import get_plugin


def normalize_params(plugin, params):
    if not isinstance(params, dict):
        raise ValueError('params должен быть словарём параметров плагина')
    known = {item['key']: item for item in plugin.params}
    extra = [key for key in params if key not in known]
    if extra:
        raise ValueError(f"параметр {extra[0]} не принадлежит стратегии {plugin.id}")
    fixed = getattr(plugin, 'fixed', {})
    cleaned = {}
    for key, definition in known.items():
        if key not in params:
            raise ValueError(f'в параметрах нет {key}')
        value = params[key]
        if definition['type'] == 'bool':
            if not isinstance(value, bool):
                raise ValueError(f'параметр {key} должен быть да или нет')
            cleaned[key] = value
        elif definition['type'] == 'enum':
            allowed = set(definition.get('options') or [])
            if not isinstance(value, str) or value not in allowed:
                raise ValueError(f'{key}: значения {value} нет в списке')
            cleaned[key] = value
        elif definition['type'] == 'number':
            cleaned[key] = _number(value, key, definition)
        else:
            raise ValueError(f'у параметра {key} неизвестный тип')
        if key in fixed and cleaned[key] != fixed[key]:
            raise ValueError(f'параметр {key} для этого плагина должен быть {fixed[key]!r}')
    return ready(cleaned)


def build_bot_config(*, strategy_id, params, run_id, symbol, interval, lot_step):
    plugin = get_plugin(strategy_id)
    if not isinstance(run_id, str) or not run_id.strip():
        raise ValueError('у конфига нет runId')
    if lot_step is not None and not _positive_number(lot_step):
        raise ValueError('шаг лота должен быть больше нуля')
    return ready({
        'strategyId': plugin.id,
        'params': normalize_params(plugin, params),
        'runId': run_id,
        'symbol': require_symbol(symbol),
        'market': MARKET,
        'interval': require_interval(interval),
        'lotStep': lot_step,
    })


def metrics_snapshot(*, profit, profit_fact, winrate, trades, max_draw, history_from, history_to, early_stop_pct, run_id):
    if not isinstance(run_id, str) or not run_id.strip():
        raise ValueError('у снимка нет runId')
    return ready({
        'Profit': _metric(profit, 'Profit'),
        'ProfitFact': _metric(profit_fact, 'ProfitFact', allow_none=True),
        'Winrate': _metric(winrate, 'Winrate', allow_none=True),
        'Trades': _trades(trades),
        'MaxDraw': _metric(max_draw, 'MaxDraw'),
        'historyFrom': _day(history_from, 'начало истории'),
        'historyTo': _day(history_to, 'конец истории'),
        'earlyStopPct': _early(early_stop_pct),
        'runId': run_id,
    })


def _number(value, key, definition):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ValueError(f'параметр {key} должен быть числом')
    number = float(value)
    if definition.get('integer'):
        if not number.is_integer():
            raise ValueError(f'{key}: нужны целые числа')
        number = int(number)
    minimum = definition.get('min')
    if minimum is not None and number < minimum:
        raise ValueError(f'{key}: значение меньше {minimum}')
    if definition.get('positive') and not number > 0:
        raise ValueError(f'{key}: значение должно быть больше нуля')
    return number


def _positive_number(value):
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(float(value)) and float(value) > 0


def _metric(value, label, allow_none=False):
    if value is None and allow_none:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ValueError(f'{label}: нужно число')
    return float(value)


def _trades(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ValueError('Trades: нужно число')
    if not float(value).is_integer() or value < 0:
        raise ValueError('Trades: нужно целое число от нуля')
    return int(value)


def _day(value, label):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        raise ValueError(f'{label} нужно в виде ГГГГ-ММ-ДД')
    return value


def _early(value):
    number = _metric(value, 'порог просадки')
    if number < 0 or number > 100:
        raise ValueError('порог просадки задаётся от 0 до 100 процентов')
    return number
