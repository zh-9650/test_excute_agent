"""ActionIR + RunRecorder 单元测试"""
import pytest
import json
import os
import tempfile
from unittest.mock import MagicMock

from backend.engine.recorder.action_ir import ActionIR, ActionStep
from backend.engine.recorder.run_recorder import RunRecorder
from backend.engine.agent.explorer_agent import CaseExplorationResult, StepResult


# === ActionStep 测试 ===

def test_action_step_to_dict():
    step = ActionStep(
        order=1,
        natural_step="在搜索框输入关键字",
        action="fill",
        locator={"strategy": "placeholder", "value": "请输入关键词"},
        value="自动存储",
        status="passed",
    )
    d = step.to_dict()
    assert d["order"] == 1
    assert d["action"] == "fill"
    assert d["locator"]["strategy"] == "placeholder"
    assert d["value"] == "自动存储"


def test_action_step_from_dict():
    data = {
        "order": 2,
        "natural_step": "点击查询按钮",
        "action": "click",
        "locator": {"strategy": "role", "role": "button", "name": "查询"},
        "status": "passed",
    }
    step = ActionStep.from_dict(data)
    assert step.order == 2
    assert step.action == "click"
    assert step.locator["role"] == "button"


def test_action_step_roundtrip():
    step = ActionStep(
        order=1,
        natural_step="测试",
        action="click",
        locator={"strategy": "text", "value": "确定"},
        before_url="http://a.com",
        after_url="http://b.com",
        status="passed",
    )
    d = step.to_dict()
    step2 = ActionStep.from_dict(d)
    assert step2.order == step.order
    assert step2.action == step.action
    assert step2.locator == step.locator


# === ActionIR 测试 ===

def test_action_ir_to_dict():
    ir = ActionIR(
        run_id="run_001",
        case_id="case_001",
        case_title="搜索功能",
        module="文档中心",
        steps=[
            ActionStep(order=1, natural_step="输入关键字", action="fill", value="测试"),
            ActionStep(order=2, natural_step="点击查询", action="click"),
        ],
        status="passed",
    )
    d = ir.to_dict()
    assert d["run_id"] == "run_001"
    assert d["case_id"] == "case_001"
    assert len(d["steps"]) == 2
    assert d["steps"][0]["action"] == "fill"


def test_action_ir_json_roundtrip():
    ir = ActionIR(
        run_id="run_001",
        case_id="case_001",
        case_title="测试用例",
        steps=[
            ActionStep(order=1, natural_step="步骤1", action="navigate", value="http://example.com"),
            ActionStep(order=2, natural_step="步骤2", action="click", locator={"strategy": "role", "role": "button", "name": "确定"}),
        ],
        status="passed",
    )
    json_str = ir.to_json()
    ir2 = ActionIR.from_json(json_str)
    assert ir2.run_id == "run_001"
    assert len(ir2.steps) == 2
    assert ir2.steps[1].locator["strategy"] == "role"


def test_action_ir_save_load():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "test_ir.json")
        ir = ActionIR(
            run_id="run_001",
            case_id="case_001",
            case_title="保存测试",
            steps=[ActionStep(order=1, natural_step="步骤1", action="click")],
        )
        ir.save(path)
        assert os.path.exists(path)

        ir2 = ActionIR.load(path)
        assert ir2.run_id == "run_001"
        assert len(ir2.steps) == 1


def test_action_ir_from_dict():
    data = {
        "run_id": "run_002",
        "case_id": "case_002",
        "case_title": "新建文档",
        "module": "文档中心",
        "expected": "文档创建成功",
        "steps": [
            {"order": 1, "natural_step": "点击新建按钮", "action": "click", "locator": {"strategy": "text", "value": "新建"}, "status": "passed"},
        ],
        "status": "passed",
    }
    ir = ActionIR.from_dict(data)
    assert ir.case_id == "case_002"
    assert ir.expected == "文档创建成功"


# === RunRecorder 测试 ===

def test_run_recorder_record_case():
    with tempfile.TemporaryDirectory() as tmpdir:
        recorder = RunRecorder("run_001", output_dir=tmpdir)

        # Mock case
        case = MagicMock()
        case.module = "文档中心"
        expected = "搜索结果正确"

        # Mock exploration result
        step1 = StepResult(
            step_num=1,
            natural_step="在搜索框输入关键字",
            actions=[
                {"function": {"name": "fill", "arguments": json.dumps({"ref": "el_001", "value": "测试", "locator": {"strategy": "placeholder", "value": "搜索"}})}},
            ],
            success=True,
            message="填写成功",
            url_before="http://example.com",
            url_after="http://example.com",
        )
        step2 = StepResult(
            step_num=2,
            natural_step="点击查询按钮",
            actions=[
                {"function": {"name": "click", "arguments": json.dumps({"ref": "el_002", "locator": {"strategy": "role", "role": "button", "name": "查询"}})}},
            ],
            success=True,
            message="点击成功",
            url_before="http://example.com",
            url_after="http://example.com/search?q=测试",
        )

        exploration = CaseExplorationResult(
            case_id="case_001",
            case_title="文档搜索",
            status="passed",
            steps=[step1, step2],
            total_ai_calls=2,
        )

        ir = recorder.record_case(case, exploration)
        assert ir.case_id == "case_001"
        assert ir.case_title == "文档搜索"
        assert len(ir.steps) == 2
        assert ir.steps[0].action == "fill"
        assert ir.steps[1].action == "click"
        assert ir.status == "passed"


def test_run_recorder_save_ir():
    with tempfile.TemporaryDirectory() as tmpdir:
        recorder = RunRecorder("run_001", output_dir=tmpdir)

        ir = ActionIR(
            run_id="run_001",
            case_id="case_001",
            case_title="测试",
            steps=[ActionStep(order=1, natural_step="步骤1", action="click")],
        )

        path = recorder.save_ir(ir)
        assert os.path.exists(path)
        assert "case_001.json" in path

        # Verify content
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        assert data["run_id"] == "run_001"


def test_run_recorder_save_all_irs():
    with tempfile.TemporaryDirectory() as tmpdir:
        recorder = RunRecorder("run_001", output_dir=tmpdir)

        irs = [
            ActionIR(run_id="run_001", case_id="case_001", case_title="用例1", steps=[]),
            ActionIR(run_id="run_001", case_id="case_002", case_title="用例2", steps=[]),
        ]

        path = recorder.save_all_irs(irs)
        assert os.path.exists(path)

        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        assert data["case_count"] == 2
        assert len(data["cases"]) == 2


def test_run_recorder_screenshot_path():
    with tempfile.TemporaryDirectory() as tmpdir:
        recorder = RunRecorder("run_001", output_dir=tmpdir)
        path = recorder.get_screenshot_path("case_001", 1, "before")
        assert "case_001_step1_before.png" in path
        assert "screenshots" in path
