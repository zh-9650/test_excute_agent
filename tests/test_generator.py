import ast
import pytest
from backend.engine.generator.generator import ScriptGenerator
from backend.engine.generator.data_factory import TestDataFactory
from backend.models.case import TestCase, Step
import os


def test_script_template_generation():
    case = TestCase(id="1", suite_id="s", module="/场景", title="列表展示",
                    steps=[Step(1, "进入页面"), Step(2, "观察列表")],
                    expected="列表正确展示",
                    preconditions="1. 用户已登录")
    element_map = {
        "/场景": [
            {"tag": "button", "selector": "button:has-text('新增')", "text": "新增"},
            {"tag": "table", "selector": "table.scenario-table", "text": ""}
        ]
    }
    gen = ScriptGenerator(ai=None)
    script = gen.build_script_template(case, element_map)
    assert "from playwright.async_api import" in script
    assert "async def test_" in script


def test_script_is_valid_python():
    gen = ScriptGenerator(ai=None)
    case = TestCase(id="1", suite_id="s", module="/m", title="t",
                    steps=[Step(1, "点击按钮")], expected="ok")
    script = gen.build_script_template(case, {})
    try:
        ast.parse(script)
    except SyntaxError:
        pytest.fail("Generated script has syntax error")


def test_precheck_passes_valid_script():
    gen = ScriptGenerator(ai=None)
    script = """
from playwright.async_api import async_playwright, expect
async def test_case():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.goto("https://test.com")
        await browser.close()
"""
    result = gen.precheck(script)
    assert result["valid"] is True


def test_precheck_rejects_invalid_script():
    gen = ScriptGenerator(ai=None)
    script = "this is not python { def broken"
    result = gen.precheck(script)
    assert result["valid"] is False
    assert len(result["errors"]) > 0


def test_precheck_detects_missing_import():
    gen = ScriptGenerator(ai=None)
    script = """
async def test_case():
    browser = await p.chromium.launch()
"""
    result = gen.precheck(script)
    assert result["valid"] is False


# --- Data Factory tests ---

def test_generate_file_by_size():
    path = TestDataFactory.generate_file("10MB_file.pdf", size_mb=10)
    assert os.path.exists(path)
    assert os.path.getsize(path) == 10 * 1024 * 1024
    os.remove(path)


def test_generate_string_by_length():
    s = TestDataFactory.generate_string(51)
    assert len(s) == 51


def test_generate_emoji_string():
    s = TestDataFactory.generate_emoji_string(5)
    assert len(s) >= 5


def test_generate_html_string():
    s = TestDataFactory.generate_html_string()
    assert "<script>" in s


def test_generate_from_keyword_file_size():
    path = TestDataFactory.generate_from_keyword("上传大小为10MB的文件")
    assert path is not None
    assert os.path.getsize(path) == 10 * 1024 * 1024
    os.remove(path)


def test_generate_from_keyword_string_length():
    s = TestDataFactory.generate_from_keyword("输入51字符名称")
    assert len(s) == 51


def test_generate_from_keyword_unknown():
    result = TestDataFactory.generate_from_keyword("some random action")
    assert result is None
