import pytest
from backend.models.case import TestCase, CaseStatus, Step


def test_create_test_case():
    case = TestCase(
        id="case-001",
        suite_id="suite-001",
        module="/场景管理(#147)",
        title="场景列表正确展示",
        preconditions="用户已登录",
        steps=[
            Step(order=1, action="进入/场景管理(#147)页面"),
            Step(order=2, action="观察场景列表")
        ],
        expected="正确展示场景列表",
        keywords="场景,列表展示",
        priority=1,
        test_type="功能测试",
        stage="系统测试阶段"
    )
    assert case.status == CaseStatus.PENDING
    assert len(case.steps) == 2
    assert case.priority == 1


def test_step_model():
    step = Step(order=1, action="点击编辑按钮", enrichment={
        "target_url": "/scenario/1/edit",
        "selector_hint": "button.edit-btn"
    })
    assert step.is_enriched is True
    assert step.target_url == "/scenario/1/edit"


def test_case_status_transitions():
    case = TestCase(id="case-001", suite_id="s-001", module="/", title="t")
    assert case.status == CaseStatus.PENDING
    case.transition_to(CaseStatus.EXPLORING)
    assert case.status == CaseStatus.EXPLORING
    case.transition_to(CaseStatus.GENERATING)
    assert case.status == CaseStatus.GENERATING
    case.transition_to(CaseStatus.RUNNING)
    assert case.status == CaseStatus.RUNNING
    case.transition_to(CaseStatus.PASSED)
    assert case.status == CaseStatus.PASSED
    # 非法转换应抛异常
    with pytest.raises(ValueError):
        case.transition_to(CaseStatus.EXPLORING)  # 不能从 PASSED 到 EXPLORING


def test_default_values():
    case = TestCase(id="c1", suite_id="s1", module="/m", title="t")
    assert case.priority == 2
    assert case.test_type == "功能测试"
    assert case.stage == "系统测试阶段"
    assert case.completeness == "unknown"
    assert case.preconditions == ""
    assert case.expected == ""
