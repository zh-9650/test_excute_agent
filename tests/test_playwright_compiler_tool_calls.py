import os
import sys
import json

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.engine.generator.playwright_compiler import PlaywrightCompiler
from backend.engine.recorder.action_ir import ActionIR, ActionStep


def test_compiler_emits_multiple_actions_from_tool_calls():
    ir = ActionIR(run_id="r1", case_id="case1", case_title="t", status="passed")
    step = ActionStep(
        order=1,
        natural_step="compound",
        action="fill",
        locator={},
        value="",
        tool_calls=[
            {
                "function": {"name": "fill", "arguments": json.dumps({"locator": {"strategy": "placeholder", "value": "用户名"}, "value": "u"})},
                "result": {"success": True},
            },
            {
                "function": {"name": "fill", "arguments": json.dumps({"locator": {"strategy": "placeholder", "value": "密码"}, "value": "p"})},
                "result": {"success": True},
            },
            {
                "function": {"name": "click", "arguments": json.dumps({"locator": {"strategy": "role", "role": "button", "name": "登录"}})},
                "result": {"success": True},
            },
        ],
    )
    ir.steps.append(step)

    script = PlaywrightCompiler().compile(ir)
    assert 'get_by_placeholder("用户名")' in script
    assert 'get_by_placeholder("密码")' in script
    assert 'get_by_role("button", name="登录")' in script
