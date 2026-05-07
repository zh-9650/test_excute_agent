"""v3 Pipeline 集成测试 — 验证 ActionIR → PlaywrightCompiler 链路"""
import pytest
import json
import tempfile
import os
from unittest.mock import MagicMock

from backend.engine.recorder.action_ir import ActionIR, ActionStep
from backend.engine.recorder.run_recorder import RunRecorder
from backend.engine.generator.playwright_compiler import PlaywrightCompiler
from backend.engine.agent.explorer_agent import CaseExplorationResult, StepResult


def test_ir_to_script_basic():
    """IR 编译为 Playwright 脚本的基本流程"""
    ir = ActionIR(
        run_id="run_001",
        case_id="case_001",
        case_title="文档搜索",
        module="文档中心",
        expected="列表显示匹配文档",
        steps=[
            ActionStep(
                order=1,
                natural_step="导航到文档中心",
                action="navigate",
                value="http://example.com/docs",
                status="passed",
            ),
            ActionStep(
                order=2,
                natural_step="在搜索框输入关键字",
                action="fill",
                locator={"strategy": "placeholder", "value": "请输入文档标题"},
                value="自动存储",
                status="passed",
            ),
            ActionStep(
                order=3,
                natural_step="点击查询按钮",
                action="click",
                locator={"strategy": "role", "role": "button", "name": "查询"},
                status="passed",
            ),
        ],
        status="passed",
    )

    compiler = PlaywrightCompiler()
    script = compiler.compile(ir)

    # 验证脚本内容
    assert "playwright" in script
    assert "async def" in script
    assert 'page.goto("http://example.com/docs")' in script
    assert 'get_by_placeholder("请输入文档标题")' in script
    assert 'get_by_role("button", name="查询")' in script
    assert "click()" in script
    assert "文档搜索" in script


def test_ir_to_script_validation():
    """编译后验证脚本语法"""
    ir = ActionIR(
        run_id="run_001",
        case_id="case_001",
        case_title="测试",
        steps=[
            ActionStep(order=1, natural_step="导航", action="navigate", value="http://example.com"),
            ActionStep(order=2, natural_step="点击", action="click", locator={"strategy": "text", "value": "确定"}),
        ],
    )

    compiler = PlaywrightCompiler()
    script, errors = compiler.compile_with_validation(ir)

    assert len(errors) == 0, f"Validation errors: {errors}"
    assert "goto" in script
    assert 'get_by_text("确定")' in script


def test_ir_to_script_assertions():
    """断言步骤的编译"""
    ir = ActionIR(
        run_id="run_001",
        case_id="case_001",
        case_title="断言测试",
        steps=[
            ActionStep(order=1, natural_step="检查元素可见", action="assert_visible",
                      locator={"strategy": "role", "role": "button", "name": "提交"}),
            ActionStep(order=2, natural_step="检查文本", action="assert_text", value="操作成功"),
            ActionStep(order=3, natural_step="检查URL", action="assert_url", value="/success"),
        ],
    )

    compiler = PlaywrightCompiler()
    script = compiler.compile(ir)

    assert "wait_for(state='visible')" in script
    assert 'get_by_text("操作成功")' in script
    assert '"/success" in page.url' in script


def test_ir_to_script_full_pipeline():
    """完整管道：探索结果 → IR → 脚本"""
    with tempfile.TemporaryDirectory() as tmpdir:
        recorder = RunRecorder("run_test", output_dir=tmpdir)
        compiler = PlaywrightCompiler()

        # 模拟探索结果
        case = MagicMock()
        case.module = "用户管理"
        case.expected = "用户创建成功"

        step1 = StepResult(
            step_num=1, natural_step="点击新建用户按钮",
            actions=[{"function": {"name": "click", "arguments": json.dumps({"ref": "el_001", "locator": {"strategy": "text", "value": "新建用户"}})}}],
            success=True, message="成功", url_before="http://a.com", url_after="http://a.com",
        )
        step2 = StepResult(
            step_num=2, natural_step="输入用户名",
            actions=[{"function": {"name": "fill", "arguments": json.dumps({"ref": "el_002", "value": "testuser", "locator": {"strategy": "placeholder", "value": "请输入用户名"}})}}],
            success=True, message="成功", url_before="http://a.com", url_after="http://a.com",
        )
        step3 = StepResult(
            step_num=3, natural_step="点击保存",
            actions=[{"function": {"name": "click", "arguments": json.dumps({"ref": "el_003", "locator": {"strategy": "role", "role": "button", "name": "保存"}})}}],
            success=True, message="成功", url_before="http://a.com", url_after="http://a.com/users",
        )

        exploration = CaseExplorationResult(
            case_id="case_001", case_title="新建用户", status="passed",
            steps=[step1, step2, step3], total_ai_calls=3,
        )

        # 录制为 IR
        ir = recorder.record_case(case, exploration)
        assert ir.status == "passed"
        assert len(ir.steps) == 3

        # 保存 IR
        ir_path = recorder.save_ir(ir)
        assert os.path.exists(ir_path)

        # 编译为脚本
        script = compiler.compile(ir)
        errors = compiler.validate(script)
        assert len(errors) == 0, f"Errors: {errors}"

        # 验证脚本内容
        assert 'get_by_text("新建用户")' in script
        assert 'get_by_placeholder("请输入用户名")' in script
        assert 'get_by_role("button", name="保存")' in script
        assert 'fill("testuser")' in script


def test_playwright_compiler_empty_ir():
    """空 IR 编译"""
    ir = ActionIR(run_id="r", case_id="c", case_title="空", steps=[])
    compiler = PlaywrightCompiler()
    script = compiler.compile(ir)
    assert "async def" in script
    errors = compiler.validate(script)
    assert len(errors) == 0


def test_playwright_compiler_no_forbidden_apis():
    """确保不生成禁止的 API"""
    ir = ActionIR(
        run_id="r", case_id="c", case_title="测试",
        steps=[ActionStep(order=1, natural_step="等待", action="wait", value="500")],
    )
    compiler = PlaywrightCompiler()
    script = compiler.compile(ir)
    assert "selenium" not in script
    assert "time.sleep" not in script
    assert "wait_for_timeout(500)" in script
