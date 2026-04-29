import hashlib
import re
from backend.storage.database import get_db


class HealingStore:
    def find(self, original_selector: str, page_url: str) -> dict | None:
        db = get_db()
        url = self._url_to_pattern(page_url)
        row = db.execute(
            """SELECT * FROM healing_records
               WHERE original_selector = ? AND ? LIKE REPLACE(page_url_pattern, '*', '%')
               ORDER BY success_count DESC, last_used_at DESC
               LIMIT 1""",
            (original_selector, url)
        ).fetchone()
        db.close()
        return dict(row) if row else None

    def add(self, original_selector: str, healed_selector: str, page_url_pattern: str, strategy: str = ""):
        db = get_db()
        rid = hashlib.md5(f"{original_selector}{page_url_pattern}".encode()).hexdigest()[:16]
        db.execute(
            """INSERT OR REPLACE INTO healing_records
               (id, original_selector, healed_selector, page_url_pattern, strategy, last_used_at)
               VALUES (?, ?, ?, ?, ?, datetime('now'))""",
            (rid, original_selector, healed_selector, page_url_pattern, strategy)
        )
        db.commit()
        db.close()

    def increment_success(self, original_selector: str, page_url_pattern: str):
        db = get_db()
        db.execute(
            "UPDATE healing_records SET success_count = success_count + 1, last_used_at = datetime('now') WHERE original_selector = ? AND page_url_pattern = ?",
            (original_selector, page_url_pattern)
        )
        db.commit()
        db.close()

    def increment_fail(self, original_selector: str, page_url_pattern: str):
        db = get_db()
        db.execute(
            "UPDATE healing_records SET fail_count = fail_count + 1 WHERE original_selector = ? AND page_url_pattern = ?",
            (original_selector, page_url_pattern)
        )
        db.execute(
            "DELETE FROM healing_records WHERE fail_count >= 3 AND original_selector = ? AND page_url_pattern = ?",
            (original_selector, page_url_pattern)
        )
        db.commit()
        db.close()

    def list_all(self) -> list[dict]:
        db = get_db()
        rows = db.execute("SELECT * FROM healing_records ORDER BY success_count DESC").fetchall()
        db.close()
        return [dict(r) for r in rows]

    def clear(self):
        db = get_db()
        db.execute("DELETE FROM healing_records")
        db.commit()
        db.close()

    def _url_to_pattern(self, url: str) -> str:
        return re.sub(r'/[^/]+(\?|#|$)', '/*', url)
