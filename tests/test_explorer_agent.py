"""ExplorerAgent + DecisionSchema + BrowserTools 单元测试"""
import pytest
import json
from unittest.mock import AsyncMock, MagicMock, patch

from backend.engine.agent.decision_schema import validate_decision, VALID_ACTIONS, BROWSER_TOOLS
from backend.engine.agent.explorer_agent import ExplorerAgent, CaseExplorationResult, StepResult
from backend.engine.agent.prompts import format_snapshot_for_prompt, format_history_for_prompt
from backend.engine.browser.browser_tool import BrowserTools, ToolResult
from backend.engine.browser.semantic_snapshot import (
    SemanticSnapshot, SnapshotSection, SnapshotElement, LocatorCandidate,
)


# === DecisionSchema 测试 ===

def test_validate_decision_valid():
    decision = {
        "action": "click",
        "target_ref": "el_001",
        "locator": {"strategy": "role", "role": "button", "name": "查询"},
        "reason": "点击查询按钮",
        "confidence": 0.9,
    }
    ok, msg = validate_decision(decision)
    assert ok, msg


def test_validate_decision_missing_action():
    decision = {"reason": "test", "confidence": 0.5}
    ok, msg = validate_decision(decision)
    assert not ok
    assert "action" in msg


def test_validate_decision_invalid_action():
    decision = {"action": "fly", "reason": "test", "confidence": 0.5}
    ok, msg = validate_decision(decision)
    assert not ok
    assert "未知" in msg


def test_validate_decision_click_needs_ref_or_locator():
    decision = {"action": "click", "reason": "test", "confidence": 0.5}
    ok, msg = validate_decision(decision)
    assert not ok
    assert "ref" in msg or "locator" in msg


def test_validate_decision_fill_needs_value():
    decision = {"action": "fill", "target_ref": "el_001", "reason": "test", "confidence": 0.5}
    ok, msg = validate_decision(decision)
    assert not ok
    assert "value" in msg


def test_validate_decision_navigate_needs_value():
    decision = {"action": "navigate", "reason": "test", "confidence": 0.5}
    ok, msg = validate_decision(decision)
    assert not ok
    assert "value" in msg


def test_validate_decision_confidence_range():
    decision = {"action": "wait", "reason": "test", "confidence": 1.5}
    ok, msg = validate_decision(decision)
    assert not ok
    assert "confidence" in msg


def test_all_actions_valid():
    for action in VALID_ACTIONS:
        decision = {"action": action, "reason": "test", "confidence": 0.5}
        if action in ("click", "fill", "hover", "select_option", "assert_visible"):
            decision["target_ref"] = "el_001"
        if action == "fill":
            decision["value"] = "test"
        if action == "navigate":
            decision["value"] = "http://example.com"
        if action == "select_option":
            decision["value"] = "option1"
        ok, msg = validate_decision(decision)
        assert ok, f"action={action}: {msg}"


def test_browser_tools_schema_count():
    assert len(BROWSER_TOOLS) == 12
    names = [t["function"]["name"] for t in BROWSER_TOOLS]
    assert "snapshot" in names
    assert "click" in names
    assert "fill" in names
    assert "navigate" in names


# === Prompts 测试 ===

def test_format_snapshot_for_prompt():
    snap = SemanticSnapshot(
        url="http://example.com",
        title="测试页",
        page_type="list",
        sections=[
            SnapshotSection(
                name="导航区",
                type="navigation",
                elements=[
                    SnapshotElement(ref="el_001", tag="a", role="link", name="首页"),
                ],
            ),
        ],
    )
    text = format_snapshot_for_prompt(snap)
    assert "el_001" in text
    assert "导航区" in text
    assert "首页" in text


def test_format_history_for_prompt():
    history = [
        {"action": "点击登录", "success": True, "message": "成功"},
        {"action": "输入密码", "success": False, "message": "元素未找到"},
    ]
    text = format_history_for_prompt(history)
    assert "点击登录" in text
    assert "输入密码" in text
    assert "✓" in text
    assert "✗" in text


def test_format_history_empty():
    assert format_history_for_prompt([]) == ""


# === BrowserTools 测试（mock page） ===

@pytest.mark.asyncio
async def test_browser_tool_snapshot():
    page = AsyncMock()
    page.url = "http://example.com"
    page.title = AsyncMock(return_value="测试页")
    page.evaluate = AsyncMock(return_value=[
        {"tag": "button", "role": "button", "name": "查询", "text": "查询", "placeholder": "",
         "aria_label": "", "testid": "", "classes": [], "href": "",
         "rect": {"x": 0, "y": 0, "w": 100, "h": 30},
         "locator_candidates": [{"strategy": "role", "role": "button", "name": "查询"}],
         "dom_path": "body > div > button"},
    ])

    tools = BrowserTools(page)
    result = await tools.snapshot()
    assert result.success
    assert "1 个可交互元素" in result.message


@pytest.mark.asyncio
async def test_browser_tool_click():
    page = AsyncMock()
    page.url = "http://example.com"
    page.title = AsyncMock(return_value="测试")
    page.get_by_role = MagicMock(return_value=AsyncMock())
    page.wait_for_load_state = AsyncMock()

    tools = BrowserTools(page)
    # Without snapshot, click with locator dict
    result = await tools.click(ref="el_001", locator={"strategy": "role", "role": "button", "name": "查询"})
    assert result.success


@pytest.mark.asyncio
async def test_browser_tool_navigate():
    page = AsyncMock()
    page.goto = AsyncMock()
    page.url = "http://example.com/new"
    page.title = AsyncMock(return_value="新页面")

    tools = BrowserTools(page)
    result = await tools.navigate("http://example.com/new")
    assert result.success
    assert "导航成功" in result.message


@pytest.mark.asyncio
async def test_browser_tool_fill():
    page = AsyncMock()
    page.get_by_placeholder = MagicMock(return_value=AsyncMock())

    tools = BrowserTools(page)
    result = await tools.fill(ref="el_001", value="测试内容", locator={"strategy": "placeholder", "value": "请输入"})
    assert result.success


@pytest.mark.asyncio
async def test_browser_tool_wait():
    page = AsyncMock()
    tools = BrowserTools(page)
    result = await tools.wait(ms=100)
    assert result.success
    assert "100ms" in result.message


# === ExplorerAgent 测试（mock AI + mock tools） ===

@pytest.mark.asyncio
async def test_explorer_agent_explore_case():
    # Mock AI provider
    ai = AsyncMock()
    ai.chat_with_tools = AsyncMock(return_value={
        "tool_calls": [
            {
                "id": "call_001",
                "function": {
                    "name": "click",
                    "arguments": json.dumps({"ref": "el_001", "locator": {"strategy": "role", "role": "button", "name": "查询"}}),
                }
            }
        ],
        "content": "",
    })

    # Mock page
    page = AsyncMock()
    page.url = "http://example.com"
    page.title = AsyncMock(return_value="测试")
    page.evaluate = AsyncMock(return_value=[
        {"tag": "button", "role": "button", "name": "查询", "text": "查询", "placeholder": "",
         "aria_label": "", "testid": "", "classes": [], "href": "",
         "rect": {"x": 0, "y": 0, "w": 100, "h": 30},
         "locator_candidates": [{"strategy": "role", "role": "button", "name": "查询"}],
         "dom_path": "body > div > button"},
    ])
    page.get_by_role = MagicMock(return_value=AsyncMock())
    page.wait_for_load_state = AsyncMock()

    tools = BrowserTools(page)
    agent = ExplorerAgent(tools, ai)

    # Mock case
    case = MagicMock()
    case.id = "case_001"
    case.title = "测试用例"
    case.steps = [MagicMock(order=1, action="点击查询按钮")]

    result = await agent.explore_case(case, "run_001")
    assert result.case_id == "case_001"
    assert len(result.steps) == 1
    assert result.steps[0].success


@pytest.mark.asyncio
async def test_explorer_agent_no_tool_calls():
    ai = AsyncMock()
    ai.chat_with_tools = AsyncMock(return_value={
        "tool_calls": [],
        "content": "我无法确定操作",
    })

    page = AsyncMock()
    page.url = "http://example.com"
    page.title = AsyncMock(return_value="测试")
    page.evaluate = AsyncMock(return_value=[])

    tools = BrowserTools(page)
    agent = ExplorerAgent(tools, ai)

    case = MagicMock()
    case.id = "case_001"
    case.title = "测试"
    case.steps = [MagicMock(order=1, action="点击按钮")]

    result = await agent.explore_case(case, "run_001")
    assert result.steps[0].success is False
    assert "未找到匹配的操作" in result.steps[0].message or "AI 未返回操作指令" in result.steps[0].message
