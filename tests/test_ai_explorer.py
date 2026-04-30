"""AI 探索引擎单元测试"""
import pytest
import json
from unittest.mock import AsyncMock, MagicMock
from backend.engine.explorer.ai_explorer import AIExplorer, StepRecord, CaseExplorationResult
from backend.engine.explorer.browser import ElementInfo


def test_step_record_defaults():
    r = StepRecord(step_num=1, action_desc="点击登录")
    assert r.step_num == 1
    assert r.success is False
    assert r.retry_count == 0
    assert r.ai_action == ""


def test_case_exploration_result_defaults():
    r = CaseExplorationResult(case_id="c1", case_title="测试")
    assert r.status == "pending"
    assert r.total_retries == 0
    assert len(r.steps) == 0


def test_format_elements():
    browser = MagicMock()
    ai = MagicMock()
    explorer = AIExplorer(browser=browser, ai_provider=ai)

    elements = [
        ElementInfo(tag="button", text="登录", selector="button:has-text('登录')",
                    aria_label="", classes=[], attributes={"type": "submit"}),
        ElementInfo(tag="input", text="", selector="input[placeholder='用户名']",
                    aria_label="", classes=[], attributes={"type": "text", "placeholder": "用户名"}),
    ]
    result = explorer._format_elements(elements)
    assert "[0] <button>" in result
    assert "text='登录'" in result
    assert "type='submit'" in result
    assert "[1] <input>" in result
    assert "placeholder='用户名'" in result


def test_parse_decision_from_dict():
    browser = MagicMock()
    ai = MagicMock()
    explorer = AIExplorer(browser=browser, ai_provider=ai)

    response = {"action": "click", "selector": "button.submit", "value": "", "confidence": 0.9}
    result = explorer._parse_decision(response)
    assert result["action"] == "click"
    assert result["selector"] == "button.submit"


def test_parse_decision_from_json_string():
    browser = MagicMock()
    ai = MagicMock()
    explorer = AIExplorer(browser=browser, ai_provider=ai)

    response = '{"action": "fill", "selector": "input[name=user]", "value": "admin", "confidence": 0.8}'
    result = explorer._parse_decision(response)
    assert result["action"] == "fill"
    assert result["value"] == "admin"


def test_parse_decision_from_ai_response():
    """测试从 AIResponse 对象解析"""
    from backend.ai.base import AIResponse
    browser = MagicMock()
    ai = MagicMock()
    explorer = AIExplorer(browser=browser, ai_provider=ai)

    response = AIResponse(judgment="click", confidence=0.85, action={"type": "click"}, reasoning="test")
    result = explorer._parse_decision(response)
    # AIResponse 没有 action dict 作为顶层，应该返回 judgment 相关
    assert isinstance(result, dict)


@pytest.mark.asyncio
async def test_explore_case_success():
    """测试单用例探索成功流程"""
    browser = MagicMock()
    browser.take_screenshot = AsyncMock()
    browser.collect_interactive_elements = AsyncMock(return_value=[
        ElementInfo(tag="button", text="登录", selector="button:has-text('登录')")
    ])

    ai = MagicMock()
    ai.explore_decide = AsyncMock(return_value={
        "action": "click",
        "selector": "button:has-text('登录')",
        "value": "",
        "reasoning": "点击登录按钮",
        "confidence": 0.95
    })

    # Mock page.click
    browser.page = MagicMock()
    browser.page.click = AsyncMock()

    explorer = AIExplorer(browser=browser, ai_provider=ai)

    # 创建模拟用例
    from backend.models.case import TestCase, Step
    case = TestCase(id="c1", suite_id="s1", module="/login", title="登录测试",
                    steps=[Step(order=1, action="点击登录按钮")],
                    expected="登录成功")

    result = await explorer.explore_case(case, "run-001")
    assert result.status == "explored"
    assert len(result.steps) == 1
    assert result.steps[0].success is True
    assert result.steps[0].ai_action == "click"


@pytest.mark.asyncio
async def test_explore_case_failure_after_retries():
    """测试单步失败超过重试次数"""
    browser = MagicMock()
    browser.take_screenshot = AsyncMock()
    browser.collect_interactive_elements = AsyncMock(return_value=[])

    ai = MagicMock()
    ai.explore_decide = AsyncMock(return_value={
        "action": "click",
        "selector": "#nonexistent",
        "value": "",
        "reasoning": "test",
        "confidence": 0.5
    })

    browser.page = MagicMock()
    browser.page.click = AsyncMock(side_effect=Exception("Element not found"))

    explorer = AIExplorer(browser=browser, ai_provider=ai, max_step_retries=2)

    from backend.models.case import TestCase, Step
    case = TestCase(id="c1", suite_id="s1", module="/test", title="失败测试",
                    steps=[Step(order=1, action="点击不存在的按钮")])

    result = await explorer.explore_case(case, "run-001")
    assert result.status == "explore_failed"
    assert result.total_retries == 2
    assert result.steps[0].success is False


@pytest.mark.asyncio
async def test_execute_action_types():
    """测试不同操作类型的执行"""
    browser = MagicMock()
    browser.page = MagicMock()
    browser.page.click = AsyncMock()
    browser.page.fill = AsyncMock()
    browser.page.select_option = AsyncMock()
    browser.page.evaluate = AsyncMock()
    browser.goto = AsyncMock()

    ai = MagicMock()
    explorer = AIExplorer(browser=browser, ai_provider=ai)

    # click
    r = await explorer._execute_action("click", "button.submit", "")
    assert r["success"] is True

    # fill
    r = await explorer._execute_action("fill", "input.name", "admin")
    assert r["success"] is True

    # navigate
    r = await explorer._execute_action("navigate", "", "http://test.com")
    assert r["success"] is True

    # wait
    r = await explorer._execute_action("wait", "", "")
    assert r["success"] is True

    # unknown
    r = await explorer._execute_action("fly", "", "")
    assert r["success"] is False
