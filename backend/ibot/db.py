import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / 'data'


def data_dir():
    (DATA / 'series').mkdir(parents=True, exist_ok=True)
    return DATA


def connect():
    data_dir()
    db = sqlite3.connect(DATA / 'tester.sqlite', timeout=5)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA journal_mode = WAL')
    db.execute('PRAGMA busy_timeout = 5000')
    db.executescript('''
        CREATE TABLE IF NOT EXISTS ideas (
          id TEXT PRIMARY KEY, name TEXT NOT NULL, rule_text TEXT NOT NULL,
          strategy_id TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS series (
          id TEXT PRIMARY KEY, symbol TEXT NOT NULL, interval TEXT NOT NULL,
          start_ms INTEGER, end_ms INTEGER, bars INTEGER NOT NULL DEFAULT 0,
          gaps_json TEXT NOT NULL DEFAULT '{"count":0,"items":[]}',
          min_qty REAL, step_size REAL, tick_size REAL, min_notional REAL,
          status TEXT NOT NULL, progress_bars INTEGER NOT NULL DEFAULT 0,
          error TEXT, updated_at TEXT NOT NULL, UNIQUE(symbol, interval)
        );
        CREATE TABLE IF NOT EXISTS runs (
          id TEXT PRIMARY KEY, idea_id TEXT, hypothesis_id TEXT, parent_run_id TEXT,
          parent_row_ids_json TEXT, series_id TEXT NOT NULL, symbol TEXT NOT NULL,
          interval TEXT NOT NULL, from_ms INTEGER NOT NULL, to_ms INTEGER NOT NULL,
          strategy_id TEXT NOT NULL, axes_json TEXT NOT NULL, settings_json TEXT NOT NULL,
          month_keys_json TEXT, status TEXT NOT NULL, total INTEGER NOT NULL,
          processed INTEGER NOT NULL DEFAULT 0, finished INTEGER NOT NULL DEFAULT 0,
          stopped INTEGER NOT NULL DEFAULT 0, per_minute REAL, error TEXT,
          profit_p33 REAL, profit_p66 REAL, pf_p33 REAL, pf_p66 REAL,
          created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT
        );
        CREATE TABLE IF NOT EXISTS result_rows (
          id TEXT PRIMARY KEY, run_id TEXT NOT NULL, ordinal INTEGER NOT NULL,
          status TEXT NOT NULL, reason TEXT, params_json TEXT NOT NULL,
          profit REAL, profit_fact REAL, winrate REAL, trades INTEGER,
          max_draw REAL, max_draw_pct REAL, max_draw_at TEXT,
          worst_trade REAL, worst_trade_at TEXT, worst_open REAL, worst_open_at TEXT,
          positive_month_share REAL, best_month_share REAL, months_json TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS result_rows_run_profit ON result_rows(run_id, profit);
        CREATE INDEX IF NOT EXISTS result_rows_run_pf ON result_rows(run_id, profit_fact);
        CREATE INDEX IF NOT EXISTS result_rows_run_dd ON result_rows(run_id, max_draw_pct);
        CREATE INDEX IF NOT EXISTS result_rows_run_win ON result_rows(run_id, winrate);
        CREATE INDEX IF NOT EXISTS result_rows_run_trades ON result_rows(run_id, trades);
        CREATE INDEX IF NOT EXISTS result_rows_run_status ON result_rows(run_id, status);
        CREATE TABLE IF NOT EXISTS drafts (
          id TEXT PRIMARY KEY, run_id TEXT NOT NULL, row_id TEXT NOT NULL,
          config_json TEXT NOT NULL, metrics_json TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS books (
          id TEXT PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL, band TEXT NOT NULL,
          rows_json TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS plan_cells (
          cell INTEGER NOT NULL, interval TEXT NOT NULL, status TEXT NOT NULL,
          note TEXT, updated_at TEXT NOT NULL, PRIMARY KEY (cell, interval)
        );
    ''')
    return db


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')
