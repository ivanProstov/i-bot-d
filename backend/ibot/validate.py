import math
import re
from datetime import datetime, timezone

from ibot.grid import grid_summary
from ibotd.registry import get_plugin, grid_params, param_labels


def parse_day_start(value):
    return _parse_day(value, '00:00:00.000')


def parse_day_end(value):
    return _parse_day(value, '23:59:59.999')


def _parse_day(value, clock):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        raise ValueError('дата нужна в виде ГГГГ-ММ-ДД')
    parsed = datetime.strptime(f'{value}T{clock}', '%Y-%m-%dT%H:%M:%S.%f').replace(tzinfo=timezone.utc)
    return int(parsed.timestamp() * 1000)


def parse_run_input(body, lot_step, min_qty):
    plugin = get_plugin(body.get('strategyId'))
    axes = _parse_axes(plugin, body.get('axes'))
    deposit = _required_number(body.get('deposit'), 'депозит')
    early = _required_number(body.get('earlyStopPct'), 'порог просадки')
    notional = _required_number(body.get('orderNotional'), 'размер заявки')
    leverage = _required_number(body.get('leverage'), 'плечо')
    if not deposit > 0:
        raise ValueError('депозит должен быть больше нуля')
    if early < 0 or early > 100:
        raise ValueError('порог просадки задаётся от 0 до 100 процентов')
    if not notional > 0:
        raise ValueError('размер заявки должен быть больше нуля')
    if not leverage >= 1:
        raise ValueError('плечо должно быть не меньше 1')
    enabled = body.get('constraintEnabled') is not False
    summary = grid_summary(param_labels(plugin), plugin.constraint, axes, enabled)
    if summary['overflow'] or summary['total'] is None:
        raise ValueError('комбинаций слишком много, сузьте сетку')
    if summary['total'] <= 0:
        raise ValueError('в сетке нет ни одной комбинации')
    return {
        'strategyId': plugin.id,
        'axes': _order_axes(plugin.series_params, axes),
        'deposit': deposit,
        'earlyStopPct': early,
        'orderNotional': notional,
        'leverage': leverage,
        'constraintEnabled': enabled,
        'lotStep': lot_step,
        'minQty': min_qty,
    }


def to_settings(parsed):
    return {
        'deposit': parsed['deposit'],
        'earlyStopPct': parsed['earlyStopPct'],
        'orderNotional': parsed['orderNotional'],
        'leverage': parsed['leverage'],
        'constraintEnabled': parsed['constraintEnabled'],
        'entryOnClose': True,
        'lotStep': parsed['lotStep'],
        'minQty': parsed['minQty'],
    }


def summary_for(body):
    plugin = get_plugin(body.get('strategyId'))
    axes = _parse_axes(plugin, body.get('axes'))
    return grid_summary(param_labels(plugin), plugin.constraint, axes, body.get('constraintEnabled') is not False)


def _parse_axes(plugin, value):
    if not isinstance(value, list) or not value:
        raise ValueError('сетка пустая')
    defs = grid_params(plugin)
    seen = set()
    axes = []
    for raw in value:
        if not isinstance(raw, dict):
            raise ValueError('ось сетки задана не объектом')
        key = raw.get('key') if isinstance(raw.get('key'), str) else ''
        definition = defs.get(key)
        if not definition:
            raise ValueError(f"параметр {key or 'без имени'} нельзя перебирать")
        if key in seen:
            raise ValueError(f'параметр {key} указан дважды')
        seen.add(key)
        if definition['type'] == 'enum' or raw.get('kind') == 'enum':
            values = raw.get('values')
            if not isinstance(values, list) or not values:
                raise ValueError(f'у {key} не выбраны значения')
            allowed = set(definition.get('options') or [])
            for item in values:
                if str(item) not in allowed:
                    raise ValueError(f'{key}: значения {item} нет в списке')
            axes.append({'key': key, 'kind': 'enum', 'values': [str(item) for item in values]})
            continue
        start = _required_number(raw.get('from'), key)
        end = _required_number(raw.get('to'), key)
        step = _required_number(raw.get('step'), key)
        if end < start:
            raise ValueError(f'{key}: конец диапазона меньше начала')
        if not step > 0:
            raise ValueError(f'{key}: шаг должен быть больше нуля')
        if definition.get('min') is not None and start < definition['min']:
            raise ValueError(f"{key}: начало меньше {definition['min']}")
        if definition.get('integer') and not all(float(item).is_integer() for item in (start, end, step)):
            raise ValueError(f'{key}: нужны целые числа')
        axes.append({'key': key, 'kind': 'number', 'from': start, 'to': end, 'step': step})
    return axes


def _order_axes(series_params, axes):
    series = set(series_params)
    return [axis for axis in axes if axis['key'] in series] + [axis for axis in axes if axis['key'] not in series]


def _required_number(value, label):
    if isinstance(value, bool) or value is None or value == '':
        raise ValueError(f'{label}: нужно число')
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        raise ValueError(f'{label}: нужно число') from None
    if not math.isfinite(parsed):
        raise ValueError(f'{label}: нужно число')
    return parsed
