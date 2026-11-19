import math

SAFE = 9007199254740991


def scale_of(number):
    if not math.isfinite(number):
        return 1
    text = f'{number:.8f}'.rstrip('0').rstrip('.')
    if '.' not in text:
        return 1
    return 10 ** (len(text) - text.index('.') - 1)


def number_count(start, end, step):
    if not all(math.isfinite(value) for value in (start, end, step)):
        return 0
    if step <= 0 or end < start:
        return 0
    scale = max(scale_of(start), scale_of(end), scale_of(step))
    left = round(start * scale)
    right = round(end * scale)
    scaled_step = round(step * scale)
    if scaled_step <= 0 or right < left:
        return 0
    return (right - left) // scaled_step + 1


def number_values(start, end, step):
    count = number_count(start, end, step)
    scale = max(scale_of(start), scale_of(end), scale_of(step))
    left = round(start * scale)
    scaled_step = round(step * scale)
    return [(left + index * scaled_step) / scale for index in range(count)]


def axis_values(axis):
    if axis.get('kind') == 'enum':
        return list(axis.get('values') or [])
    return number_values(float(axis['from']), float(axis['to']), float(axis['step']))


def axis_size(axis):
    if axis.get('kind') == 'enum':
        return len(axis.get('values') or [])
    return number_count(float(axis['from']), float(axis['to']), float(axis['step']))


def _multiply(values):
    acc = 1
    for value in values:
        if value <= 0:
            return {'value': 0, 'overflow': False}
        if acc > SAFE / value:
            return {'value': None, 'overflow': True}
        acc *= value
    return {'value': acc, 'overflow': False}


def grid_summary(labels, constraint, axes, constraint_enabled):
    parts = [f"{labels.get(axis['key'], axis['key'])} {axis_size(axis)}" for axis in axes]
    raw = _multiply([axis_size(axis) for axis in axes])
    use_constraint = bool(constraint and constraint_enabled)
    if not use_constraint or not constraint:
        return {
            'formula': ' × '.join(parts) if parts else 'нет осей',
            'raw': raw['value'],
            'total': raw['value'],
            'excluded': 0,
            'overflow': raw['overflow'],
        }
    left = next((axis for axis in axes if axis['key'] == constraint['left']), None)
    right = next((axis for axis in axes if axis['key'] == constraint['right']), None)
    if not left or not right or left.get('kind') == 'enum' or right.get('kind') == 'enum':
        return {
            'formula': ' × '.join(parts),
            'raw': raw['value'],
            'total': raw['value'],
            'excluded': 0,
            'overflow': raw['overflow'],
        }
    pairs = 0
    for left_value in number_values(float(left['from']), float(left['to']), float(left['step'])):
        for right_value in number_values(float(right['from']), float(right['to']), float(right['step'])):
            if left_value < right_value:
                pairs += 1
    others = [axis for axis in axes if axis['key'] not in (constraint['left'], constraint['right'])]
    rest = _multiply([axis_size(axis) for axis in others])
    total = None
    overflow = rest['overflow']
    if not overflow and rest['value'] is not None:
        if pairs > 0 and rest['value'] > SAFE / pairs:
            overflow = True
        else:
            total = pairs * rest['value']
    excluded = None
    if raw['value'] is not None and total is not None:
        excluded = raw['value'] - total
    return {
        'formula': f"{' × '.join(parts)} , правило {constraint['left']} < {constraint['right']}",
        'raw': raw['value'],
        'total': total,
        'excluded': excluded,
        'overflow': raw['overflow'] or overflow,
    }


def enumerate_grid(axes, constraint):
    values = [axis_values(axis) for axis in axes]
    index = [0 for _ in axes]
    sizes = [len(column) for column in values]
    if not axes or any(size == 0 for size in sizes):
        return
    left = next((i for i, axis in enumerate(axes) if constraint and axis['key'] == constraint['left']), -1)
    right = next((i for i, axis in enumerate(axes) if constraint and axis['key'] == constraint['right']), -1)
    while True:
        allowed = True
        if left >= 0 and right >= 0:
            left_value = values[left][index[left]]
            right_value = values[right][index[right]]
            if isinstance(left_value, (int, float)) and isinstance(right_value, (int, float)) and left_value >= right_value:
                allowed = False
        if allowed:
            yield {axes[i]['key']: values[i][index[i]] for i in range(len(axes))}
        cursor = len(axes) - 1
        while cursor >= 0:
            index[cursor] += 1
            if index[cursor] < sizes[cursor]:
                break
            index[cursor] = 0
            cursor -= 1
        if cursor < 0:
            return
