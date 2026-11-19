import os
import struct
from datetime import datetime, timezone

from ibot.db import data_dir

HEADER = 16
RECORD = 48


def series_path(series_id):
    return data_dir() / 'series' / f'{series_id}.bin'


def save_series(series_id, data):
    n = len(data['close'])
    header = struct.pack('<4sIII', b'IBK1', 1, n, 0)
    body = bytearray(n * RECORD)
    for index in range(n):
        offset = index * RECORD
        struct.pack_into(
            '<6d', body, offset,
            data['openTime'][index], data['open'][index], data['high'][index],
            data['low'][index], data['close'][index], data['volume'][index],
        )
    target = series_path(series_id)
    temp = target.with_suffix('.bin.tmp')
    temp.write_bytes(header + body)
    os.replace(temp, target)


def load_series(series_id):
    buf = series_path(series_id).read_bytes()
    magic, _version, n, _reserved = struct.unpack_from('<4sIII', buf, 0)
    if magic != b'IBK1':
        raise ValueError('файл ряда повреждён')
    numbers = struct.unpack_from('<' + 'd' * (n * 6), buf, HEADER)
    columns = [[] for _ in range(6)]
    for index in range(n):
        base = index * 6
        for column in range(6):
            columns[column].append(numbers[base + column])
    keys = ['openTime', 'open', 'high', 'low', 'close', 'volume']
    return dict(zip(keys, columns))


def slice_series(data, from_ms, to_ms):
    start = _lower_bound(data['openTime'], from_ms)
    end = _lower_bound(data['openTime'], to_ms + 1)
    if end < start:
        end = start
    return {key: values[start:end] for key, values in data.items()}


def merge_series(left, right):
    i = j = 0
    merged = {key: [] for key in left}
    left_n = len(left['close'])
    right_n = len(right['close'])
    while i < left_n or j < right_n:
        take_right = i >= left_n or (j < right_n and right['openTime'][j] < left['openTime'][i])
        same = i < left_n and j < right_n and left['openTime'][i] == right['openTime'][j]
        source = right if same or take_right else left
        index = j if same or take_right else i
        for key in merged:
            merged[key].append(source[key][index])
        if same:
            i += 1
            j += 1
        elif take_right:
            j += 1
        else:
            i += 1
    return merged


def empty_series():
    return {key: [] for key in ('openTime', 'open', 'high', 'low', 'close', 'volume')}


def find_gaps(open_time, interval):
    items = []
    count = 0
    for index in range(1, len(open_time)):
        diff = open_time[index] - open_time[index - 1]
        if diff > interval * 1.5:
            count += 1
            if len(items) < 200:
                items.append({
                    'after': datetime.fromtimestamp(open_time[index - 1] / 1000, timezone.utc).isoformat().replace('+00:00', 'Z'),
                    'before': datetime.fromtimestamp(open_time[index] / 1000, timezone.utc).isoformat().replace('+00:00', 'Z'),
                    'missingBars': max(1, round(diff / interval) - 1),
                })
    return {'count': count, 'items': items}


def _lower_bound(times, target):
    lo = 0
    hi = len(times)
    while lo < hi:
        mid = (lo + hi) >> 1
        if times[mid] < target:
            lo = mid + 1
        else:
            hi = mid
    return lo
