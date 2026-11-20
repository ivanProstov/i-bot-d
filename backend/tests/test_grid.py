import pytest

from ibot.grid import enumerate_grid, grid_summary, number_count
from ibot.server import row_filter
from ibot.validate import parse_run_input


def periods():
    return [
        {'key': 'fastPeriod', 'kind': 'number', 'from': 2, 'to': 4, 'step': 2},
        {'key': 'slowPeriod', 'kind': 'number', 'from': 2, 'to': 4, 'step': 2},
    ]


def test_number_count_includes_both_ends_and_rejects_a_bad_step():
    assert number_count(10, 350, 2) == 171
    assert number_count(0, 2, 0.1) == 21
    assert number_count(1, 10, 0.5) == 19
    assert number_count(1, 1, 0.3) == 1
    assert number_count(1, 0, 1) == 0
    assert number_count(0, 1, 0) == 0
    assert number_count(float('nan'), 1, 1) == 0


def test_equal_periods_drop_out_only_while_the_rule_is_on():
    axes = periods()
    constraint = {'left': 'fastPeriod', 'op': '<', 'right': 'slowPeriod'}
    kept = {(item['fastPeriod'], item['slowPeriod']) for item in enumerate_grid(axes, constraint)}
    assert kept == {(2, 4)}
    assert len(list(enumerate_grid(axes, None))) == 4
    summary = grid_summary({'fastPeriod': 'Период быстрой', 'slowPeriod': 'Период медленной'}, constraint, axes, True)
    assert summary['raw'] == 4
    assert summary['total'] == 1
    assert summary['excluded'] == 3
    opened = grid_summary({}, constraint, axes, False)
    assert opened['total'] == 4
    assert opened['excluded'] == 0


def test_parse_run_input_rejects_a_broken_range():
    body = {
        'strategyId': 'ma-cross',
        'axes': [
            {'key': 'fastType', 'kind': 'enum', 'values': ['SMA']},
            {'key': 'fastPeriod', 'kind': 'number', 'from': 12, 'to': 10, 'step': 2},
        ],
        'deposit': 1000,
        'earlyStopPct': 25,
        'orderNotional': 1000,
        'leverage': 1,
    }
    with pytest.raises(ValueError, match='конец диапазона'):
        parse_run_input(body, None, None)
    body['axes'][1] = {'key': 'fastPeriod', 'kind': 'number', 'from': 10, 'to': 12, 'step': 0}
    with pytest.raises(ValueError, match='шаг должен быть больше нуля'):
        parse_run_input(body, None, None)
    body['axes'] = []
    with pytest.raises(ValueError, match='сетка пустая'):
        parse_run_input(body, None, None)
    body['axes'] = [{'key': 'fastType', 'kind': 'enum', 'values': ['RMA']}]
    with pytest.raises(ValueError, match='нет в списке'):
        parse_run_input(body, None, None)


def test_row_filter_applies_profit_and_winrate_and_skips_blanks():
    where, args = row_filter('run-1', {
        'status': ['done'],
        'minProfit': ['10'],
        'minWinrate': ['30'],
        'minProfitFact': [''],
        'maxDrawPct': ['25'],
    })
    assert 'profit >= ?' in where
    assert '(winrate IS NULL OR winrate >= ?)' in where
    assert 'max_draw_pct <= ?' in where
    assert 'profit_fact' not in where
    assert args == ['run-1', 'done', 10.0, 25.0, 30.0]
    blank, _ = row_filter('run-1', {'minWinrate': ['']})
    assert 'winrate' not in blank
    filled, _ = row_filter('run-1', {'minProfitFact': ['0'], 'minWinrate': ['0'], 'maxWinrate': ['50']})
    assert '(profit_fact IS NULL OR profit_fact >= ?)' in filled
    assert '(winrate IS NULL OR winrate >= ?)' in filled
    assert 'winrate <= ?' in filled
    assert 'winrate IS NULL OR winrate <=' not in filled


def test_zero_minimum_keeps_empty_profit_fact_and_winrate(tmp_path, monkeypatch):
    import ibot.db as database
    from ibot.db import connect
    from ibot.server import query_rows

    monkeypatch.setattr(database, 'DATA', tmp_path)
    db = connect()
    try:
        db.execute(
            '''INSERT INTO runs (
                id, series_id, symbol, interval, from_ms, to_ms, strategy_id,
                axes_json, settings_json, month_keys_json, status, total, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            ('run', 'series', 'WINUSDT', '5m', 0, 1, 'ma-cross', '[]', '{}', '[]', 'done', 4, '2020-01-01T00:00:00.000Z'),
        )
        stored = (
            ('none', 0, None, None, 0),
            ('zero', -10, 0, 0, 1),
            ('winner', 10, None, 100, 1),
            ('loss', 1, -1, 0, 1),
        )
        for ordinal, (row_id, profit, profit_fact, winrate, trades) in enumerate(stored):
            db.execute(
                '''INSERT INTO result_rows (
                    id, run_id, ordinal, status, params_json, profit, profit_fact, winrate, trades, months_json
                ) VALUES (?, ?, ?, 'done', '{}', ?, ?, ?, ?, '[]')''',
                (row_id, 'run', ordinal, profit, profit_fact, winrate, trades),
            )
        db.commit()

        def ids(query):
            body = query_rows(db, 'run', query)
            return body['total'], {row['id'] for row in body['rows']}

        assert ids({'status': ['done'], 'minWinrate': ['0']}) == (4, {'none', 'zero', 'winner', 'loss'})
        assert ids({'status': ['done'], 'minProfitFact': ['0']}) == (3, {'none', 'zero', 'winner'})
        assert ids({'status': ['done'], 'minWinrate': ['1']}) == (2, {'none', 'winner'})
        assert ids({'status': ['done'], 'minTrades': ['1']}) == (3, {'zero', 'winner', 'loss'})
        winner = next(row for row in query_rows(db, 'run', {'status': ['done'], 'ids': ['winner']})['rows'])
        assert winner['Profit'] == 10
        assert winner['Winrate'] == 100
        assert winner['ProfitFact'] is None
    finally:
        db.close()
