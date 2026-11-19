from ibotd.hypothesis import HYPOTHESES, apply_hypothesis, find_hypothesis, hypotheses_for, is_btc_symbol


def axes():
    return [
        {'key': 'stopLossPct', 'kind': 'number', 'from': 1, 'to': 10, 'step': 0.5},
        {'key': 'exitMode', 'kind': 'enum', 'values': ['tp_sl', 'flip_on_cross']},
        {'key': 'direction', 'kind': 'enum', 'values': ['long', 'short', 'both']},
        {'key': 'crossMode', 'kind': 'enum', 'values': ['direct', 'reverse']},
    ]


def by_key(items, key):
    return next(item for item in items if item['key'] == key)


def test_six_hypotheses_pin_only_named_axes():
    assert list(HYPOTHESES) == ['ma-cross']
    listed = hypotheses_for('ma-cross')
    assert [item['id'] for item in listed] == [
        'ma-direct-both-tpsl',
        'ma-direct-flip',
        'ma-direct-long-tpsl',
        'ma-direct-short-tpsl',
        'ma-reverse',
        'ma-short-alt',
    ]
    assert find_hypothesis('нет') is None
    reverse = find_hypothesis('ma-reverse')
    pinned = apply_hypothesis(axes(), reverse)
    assert by_key(pinned, 'crossMode')['values'] == ['reverse']
    assert by_key(pinned, 'direction')['values'] == ['both']
    assert by_key(pinned, 'exitMode')['values'] == ['tp_sl', 'flip_on_cross']
    flip = apply_hypothesis(axes(), find_hypothesis('ma-direct-flip'))
    assert by_key(flip, 'exitMode')['values'] == ['flip_on_cross']
    assert by_key(flip, 'stopLossPct') == {'key': 'stopLossPct', 'kind': 'number', 'from': 1, 'to': 10, 'step': 0.5}
    short = apply_hypothesis(axes(), find_hypothesis('ma-short-alt'))
    assert by_key(short, 'direction')['values'] == ['short']
    assert by_key(short, 'crossMode')['values'] == ['direct', 'reverse']
    assert 'variant' not in reverse


def test_short_alt_rejects_btc_symbol_only():
    assert find_hypothesis('ma-short-alt')['rejectBtc'] is True
    assert is_btc_symbol('BTCUSDT') is True
    assert is_btc_symbol('btcusdt') is True
    assert is_btc_symbol('ETHUSDT') is False
