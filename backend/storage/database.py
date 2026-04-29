import sqlite3
from pathlib import Path

DB_DIR = Path("data")
DB_PATH = DB_DIR / "test_platform.db"


def get_db() -> sqlite3.Connection:
    DB_DIR.mkdir(exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    conn = get_db()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS test_suites (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        file_name TEXT,
        case_count INTEGER DEFAULT 0,
        created_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS test_cases (
        id TEXT PRIMARY KEY,
        suite_id TEXT NOT NULL,
        module TEXT,
        title TEXT,
        preconditions TEXT DEFAULT '',
        steps TEXT DEFAULT '[]',
        expected TEXT DEFAULT '',
        keywords TEXT DEFAULT '',
        priority INTEGER DEFAULT 2,
        test_type TEXT DEFAULT '功能测试',
        stage TEXT DEFAULT '系统测试阶段',
        status TEXT DEFAULT 'pending',
        completeness TEXT DEFAULT 'unknown',
        FOREIGN KEY (suite_id) REFERENCES test_suites(id)
    );

    CREATE TABLE IF NOT EXISTS test_runs (
        id TEXT PRIMARY KEY,
        suite_id TEXT NOT NULL,
        target_url TEXT,
        credentials TEXT DEFAULT '{}',
        status TEXT DEFAULT 'pending',
        started_at TEXT,
        finished_at TEXT,
        config TEXT DEFAULT '{}',
        FOREIGN KEY (suite_id) REFERENCES test_suites(id)
    );

    CREATE TABLE IF NOT EXISTS case_results (
        id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL,
        case_id TEXT NOT NULL,
        status TEXT,
        ai_judgment TEXT,
        ai_confidence REAL,
        retry_count INTEGER DEFAULT 0,
        duration_ms INTEGER DEFAULT 0,
        screenshot_paths TEXT DEFAULT '[]',
        video_path TEXT,
        FOREIGN KEY (run_id) REFERENCES test_runs(id),
        FOREIGN KEY (case_id) REFERENCES test_cases(id)
    );

    CREATE TABLE IF NOT EXISTS ai_calls (
        id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL,
        case_id TEXT,
        scenario TEXT,
        model TEXT,
        prompt TEXT,
        response TEXT,
        judgment TEXT,
        confidence REAL,
        duration_ms INTEGER DEFAULT 0,
        created_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS element_map (
        id TEXT PRIMARY KEY,
        exploration_id TEXT NOT NULL,
        page_url TEXT,
        selector TEXT,
        tag TEXT,
        text TEXT,
        aria_label TEXT,
        classes TEXT,
        collected_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS exploration_logs (
        id TEXT PRIMARY KEY,
        exploration_id TEXT NOT NULL,
        page_url TEXT,
        target_module TEXT,
        status TEXT,
        elements_found INTEGER DEFAULT 0,
        error_reason TEXT,
        screenshot_path TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS healing_records (
        id TEXT PRIMARY KEY,
        original_selector TEXT NOT NULL,
        healed_selector TEXT NOT NULL,
        page_url_pattern TEXT NOT NULL,
        context_signature TEXT,
        strategy TEXT DEFAULT '',
        success_count INTEGER DEFAULT 1,
        fail_count INTEGER DEFAULT 0,
        last_used_at TEXT,
        created_at TEXT DEFAULT (datetime('now')),
        UNIQUE(original_selector, page_url_pattern)
    );
    """)
    conn.commit()
    conn.close()


init_db()
