"""SemanticSnapshot + LocatorEngine 单元测试"""
import pytest
from backend.engine.browser.semantic_snapshot import (
    SemanticSnapshot, SnapshotSection, SnapshotElement, LocatorCandidate,
    _classify_section, _infer_page_type,
)
from backend.engine.browser.locator_engine import (
    compile_locator_from_dict, get_best_locator_str, locator_dict_to_code,
)


# === SemanticSnapshot 数据结构测试 ===

def test_snapshot_element_to_dict():
    el = SnapshotElement(
        ref="el_001",
        tag="button",
        role="button",
        name="查询",
        text="查询",
        locator_candidates=[
            LocatorCandidate(strategy="role", role="button", name="查询"),
            LocatorCandidate(strategy="text", value="查询"),
        ],
    )
    d = el.to_dict()
    assert d["ref"] == "el_001"
    assert d["tag"] == "button"
    assert d["role"] == "button"
    assert d["name"] == "查询"
    assert len(d["locator_candidates"]) == 2
    assert d["locator_candidates"][0]["strategy"] == "role"


def test_snapshot_section_to_dict():
    section = SnapshotSection(
        name="搜索区",
        type="search",
        elements=[
            SnapshotElement(ref="el_001", tag="input", placeholder="请输入关键词"),
            SnapshotElement(ref="el_002", tag="button", text="搜索"),
        ],
    )
    d = section.to_dict()
    assert d["name"] == "搜索区"
    assert d["type"] == "search"
    assert len(d["elements"]) == 2


def test_semantic_snapshot_find_element():
    snapshot = SemanticSnapshot(
        url="http://example.com",
        title="测试页",
        sections=[
            SnapshotSection(
                name="导航",
                type="navigation",
                elements=[
                    SnapshotElement(ref="el_001", tag="a", name="首页"),
                    SnapshotElement(ref="el_002", tag="a", name="文档"),
                ],
            ),
            SnapshotSection(
                name="搜索",
                type="search",
                elements=[
                    SnapshotElement(ref="el_010", tag="input", placeholder="搜索"),
                ],
            ),
        ],
    )
    assert snapshot.find_element("el_001").name == "首页"
    assert snapshot.find_element("el_010").tag == "input"
    assert snapshot.find_element("el_999") is None


def test_semantic_snapshot_all_elements():
    snapshot = SemanticSnapshot(
        url="http://example.com",
        title="测试",
        sections=[
            SnapshotSection(name="A", type="navigation", elements=[
                SnapshotElement(ref="el_001", tag="a"),
            ]),
            SnapshotSection(name="B", type="content", elements=[
                SnapshotElement(ref="el_002", tag="button"),
                SnapshotElement(ref="el_003", tag="button"),
            ]),
        ],
    )
    assert len(snapshot.all_elements()) == 3


def test_snapshot_to_dict_roundtrip():
    snapshot = SemanticSnapshot(
        url="http://example.com/page",
        title="页面标题",
        page_type="list",
        sections=[
            SnapshotSection(
                name="导航",
                type="navigation",
                elements=[
                    SnapshotElement(
                        ref="el_001",
                        tag="a",
                        role="link",
                        name="文档中心",
                        text="文档中心",
                        locator_candidates=[
                            LocatorCandidate(strategy="role", role="link", name="文档中心"),
                        ],
                    ),
                ],
            ),
        ],
    )
    d = snapshot.to_dict()
    assert d["url"] == "http://example.com/page"
    assert d["title"] == "页面标题"
    assert d["page_type"] == "list"
    assert len(d["sections"]) == 1
    assert d["sections"][0]["elements"][0]["ref"] == "el_001"


# === 分类逻辑测试 ===

def test_classify_section_navigation():
    assert _classify_section("body > nav.main-nav", [], "a", "首页") == "navigation"
    assert _classify_section("body > div.header", ["header-bar"], "a", "") == "navigation"
    assert _classify_section("body > div.sidebar", [], "a", "") == "navigation"


def test_classify_section_search():
    assert _classify_section("body > div.search-bar", [], "input", "") == "search"
    assert _classify_section("body > div.toolbar", [], "button", "") == "search"


def test_classify_section_form():
    assert _classify_section("body > div.content", [], "input", "") == "form"
    assert _classify_section("body > div.form-group", [], "select", "") == "form"


def test_classify_section_modal():
    assert _classify_section("body > div.modal", [], "button", "") == "modal"
    assert _classify_section("body > div.dialog", [], "button", "") == "modal"


def test_classify_section_footer():
    assert _classify_section("body > div.footer", [], "a", "") == "footer"
    assert _classify_section("body > div.pagination", [], "a", "") == "footer"


def test_classify_section_content():
    assert _classify_section("body > div.main > div.card", [], "button", "编辑") == "content"


# === 页面类型推断测试 ===

def test_infer_page_type_login():
    assert _infer_page_type("http://example.com/login", "登录", []) == "login"
    assert _infer_page_type("http://example.com/signin", "用户登录", []) == "login"


def test_infer_page_type_list():
    assert _infer_page_type("http://example.com/users/index", "用户列表", []) == "list"


def test_infer_page_type_form():
    elements = [{"tag": "input"}] * 6
    assert _infer_page_type("http://example.com/create", "新建", elements) == "form"


def test_infer_page_type_unknown():
    assert _infer_page_type("http://example.com/xyz", "随便", []) == "unknown"


# === LocatorEngine 测试 ===

def test_compile_locator_from_dict_role():
    """role 策略应该返回正确的 locator 类型"""
    # 这里只测试代码生成，不测试实际 Playwright（需要浏览器）
    d = {"strategy": "role", "role": "button", "name": "查询"}
    code = locator_dict_to_code(d)
    assert 'get_by_role("button"' in code
    assert 'name="查询"' in code


def test_compile_locator_from_dict_placeholder():
    d = {"strategy": "placeholder", "value": "请输入文档标题"}
    code = locator_dict_to_code(d)
    assert 'get_by_placeholder("请输入文档标题")' in code


def test_compile_locator_from_dict_text():
    d = {"strategy": "text", "value": "文档中心"}
    code = locator_dict_to_code(d)
    assert 'get_by_text("文档中心")' in code


def test_compile_locator_from_dict_css():
    d = {"strategy": "css", "value": "#search-input"}
    code = locator_dict_to_code(d)
    assert 'locator("#search-input")' in code


def test_compile_locator_from_dict_testid():
    d = {"strategy": "testid", "value": "submit-btn"}
    code = locator_dict_to_code(d)
    assert 'get_by_test_id("submit-btn")' in code


def test_get_best_locator_str():
    el = SnapshotElement(
        ref="el_001",
        tag="input",
        placeholder="请输入关键词",
        locator_candidates=[
            LocatorCandidate(strategy="placeholder", value="请输入关键词"),
        ],
    )
    code = get_best_locator_str(el)
    assert 'get_by_placeholder("请输入关键词")' in code


def test_get_best_locator_str_fallback():
    el = SnapshotElement(ref="el_001", tag="div", locator_candidates=[])
    code = get_best_locator_str(el)
    assert 'locator("div")' in code


def test_escape_quotes():
    from backend.engine.browser.locator_engine import _escape
    assert _escape('hello "world"') == 'hello \\"world\\"'
    assert _escape('path\\to') == 'path\\\\to'
