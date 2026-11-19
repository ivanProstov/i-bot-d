import math


def floor_to_step(qty, step):
    """Объём вниз до шага лота. Без шага объём не меняется."""
    if step is None or not step > 0:
        return qty
    text = f'{step:.12f}'.rstrip('0').rstrip('.')
    decimals = 0 if '.' not in text else len(text.split('.')[1])
    units = math.floor(qty / step + 1e-9)
    return round(units * step, decimals)
