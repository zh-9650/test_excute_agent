import os
import sys
import json
from unittest.mock import MagicMock, AsyncMock

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.engine.agent.explorer_agent import ExplorerAgent
from backend.engine.browser.browser_tool import ToolResult


class _FakeTools:
    def __init__(self, snapshots):
        self._snapshots = list(snapshots)
        self.page = AsyncMock()
        self.page.url = "http://example.local/login"

    async def snapshot(self):
        if self._snapshots:
            data = self._snapshots.pop(0)
        else:
            data = {"url": self.page.url, "title": "page", "page_type": "unknown", "sections": []}
        return ToolResult(success=True, tool="snapshot", message="ok", data=data)

    def get_last_snapshot(self):
        return None

    async def click(self, ref="", locator=None):
        return ToolResult(success=True, tool="click", message="ok", data={"url": self.page.url})

    async def fill(self, ref="", value="", locator=None):
        return ToolResult(success=True, tool="fill", message="ok", data={"ref": ref, "value": value})

    async def hover(self, ref="", locator=None):
        return ToolResult(success=True, tool="hover", message="ok")

    async def select_option(self, ref="", value="", locator=None):
        return ToolResult(success=True, tool="select_option", message="ok")

    async def navigate(self, url=""):
        self.page.url = url
        return ToolResult(success=True, tool="navigate", message="ok", data={"url": url})

    async def press_key(self, key=""):
        return ToolResult(success=True, tool="press_key", message="ok")

    async def wait(self, ms=1000):
        return ToolResult(success=True, tool="wait", message="ok")

    async def screenshot(self, path=""):
        return ToolResult(success=True, tool="screenshot", message="ok", data={"path": path})

    async def expect_visible(self, ref="", locator=None):
        return ToolResult(success=True, tool="expect_visible", message="ok")

    async def expect_text(self, text=""):
        return ToolResult(success=True, tool="expect_text", message="ok")

    async def expect_url(self, url_pattern=""):
        return ToolResult(success=True, tool="expect_url", message="ok")


@pytest.mark.asyncio
async def test_compound_username_password_step_requires_two_fills_and_uses_credentials():
    # snapshot that exposes both username+password fields
    snap = {
        "url": "http://example.local/login",
        "title": "Login",
        "page_type": "login",
        "sections": [
            {
                "name": "Form",
                "type": "form",
                "elements": [
                    {
                        "ref": "el_001",
                        "tag": "input",
                        "role": "textbox",
                        "name": "用户名",
                        "placeholder": "用户名",
                        "locator_candidates": [{"strategy": "placeholder", "value": "用户名"}],
                    },
                    {
                        "ref": "el_002",
                        "tag": "input",
                        "role": "textbox",
                        "name": "密码",
                        "placeholder": "密码",
                        "locator_candidates": [{"strategy": "placeholder", "value": "密码"}],
                    },
                ],
            }
        ],
    }

    tools = _FakeTools([snap])
    ai = MagicMock()
    ai.chat_with_tools = MagicMock()
    agent = ExplorerAgent(tools, ai, credentials={"username": "zhanghong", "password": "123456"})

    case = MagicMock()
    case.id = "c1"
    case.title = "login"
    case.steps = [MagicMock(order=1, action="输入用户名密码")]

    result = await agent.explore_case(case, "run1")
    assert result.status == "passed"
    assert result.steps[0].success is True

    fills = [a for a in result.steps[0].actions if a.get("function", {}).get("name") == "fill"]
    assert len(fills) == 2
    args0 = json.loads(fills[0]["function"]["arguments"])
    args1 = json.loads(fills[1]["function"]["arguments"])
    assert {"zhanghong", "123456"} == {args0["value"], args1["value"]}


@pytest.mark.asyncio
async def test_login_click_step_fails_if_still_on_login_page():
    before = {
        "url": "http://example.local/login",
        "title": "Login",
        "page_type": "login",
        "sections": [
            {
                "name": "Form",
                "type": "form",
                "elements": [
                    {
                        "ref": "el_010",
                        "tag": "button",
                        "role": "button",
                        "name": "登录",
                        "text": "登录",
                        "locator_candidates": [{"strategy": "role", "role": "button", "name": "登录"}],
                    }
                ],
            }
        ],
    }
    after = dict(before)  # still login page after click

    tools = _FakeTools([before, after])
    ai = MagicMock()
    ai.chat_with_tools = MagicMock(return_value={
        "tool_calls": [
            {
                "id": "call_1",
                "function": {
                    "name": "click",
                    "arguments": json.dumps({"ref": "el_010", "locator": {"strategy": "role", "role": "button", "name": "登录"}}),
                },
            }
        ],
        "content": "",
    })
    agent = ExplorerAgent(tools, ai)

    case = MagicMock()
    case.id = "c2"
    case.title = "login"
    case.steps = [MagicMock(order=1, action="点击登录按钮")]

    result = await agent.explore_case(case, "run2")
    assert result.status != "passed"
    assert result.steps[0].success is False
