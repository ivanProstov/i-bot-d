import json
import math


def dumps(value):
    return json.dumps(ready(value), ensure_ascii=False)


def ready(value):
    if isinstance(value, float):
        if math.isfinite(value) and value.is_integer() and abs(value) <= 9_007_199_254_740_991:
            return int(value)
        return value
    if isinstance(value, dict):
        return {key: ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [ready(item) for item in value]
    return value
