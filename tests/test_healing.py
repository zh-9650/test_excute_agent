from backend.engine.executor.healing import HealingStore
from backend.storage.database import init_db


def test_add_and_find_healing_record():
    init_db()
    store = HealingStore()
    store.add(".btn-delete", "button:has-text('删除')", "*/scenario/*", "text_match")
    result = store.find(".btn-delete", "https://test.com/scenario/123")
    assert result is not None
    assert result["healed_selector"] == "button:has-text('删除')"


def test_find_returns_none_for_unknown():
    store = HealingStore()
    result = store.find(".nonexistent", "https://test.com/page")
    assert result is None


def test_auto_delete_on_excessive_failures():
    store = HealingStore()
    store.add(".btn-bad", "button.bad", "*/bad/*", "css_stable")
    store.increment_fail(".btn-bad", "*/bad/*")
    store.increment_fail(".btn-bad", "*/bad/*")
    store.increment_fail(".btn-bad", "*/bad/*")
    result = store.find(".btn-bad", "https://x.com/bad/page")
    assert result is None


def test_list_all():
    store = HealingStore()
    store.clear()
    store.add(".a", "button.a", "*/a/*", "text_match")
    store.add(".b", "button.b", "*/b/*", "role_match")
    all_records = store.list_all()
    assert len(all_records) == 2
    store.clear()
