from backend.engine.executor.executor import SmartExecutor, ExecutionContext
from backend.models.case import TestCase, Step


def test_execution_context_creation():
    case = TestCase(id="c1", suite_id="s1", module="/", title="test",
                    steps=[Step(1, "click button")], expected="ok")
    ctx = ExecutionContext(case=case, script="print('hello')", session_id="sess1")
    assert ctx.ai_call_count == 0
    assert ctx.retry_count == 0


def test_executor_analyzes_selector_failure():
    exe = SmartExecutor(ai=None)
    result = exe.analyze_selector_failure(
        original_selector=".old-class",
        page_summary={"url": "/test", "text_snippet": "No button here"},
        case_context="test case context"
    )
    assert "selector" in result
    assert "confidence" in result


def test_executor_classifies_failures():
    exe = SmartExecutor(ai=None)
    summary = [
        {"case_id": "1", "status": "failed", "ai_judgment": "bug", "ai_confidence": 0.9},
        {"case_id": "2", "status": "failed", "ai_judgment": "selector_changed", "ai_confidence": 0.8},
        {"case_id": "3", "status": "blocked", "ai_judgment": None},
        {"case_id": "4", "status": "error", "ai_judgment": "script_error"},
    ]
    analysis = exe.classify_results(summary)
    assert len(analysis["bugs"]) == 1
    assert len(analysis["script_issues"]) == 2
    assert len(analysis["environment_issues"]) == 1  # blocked case without judgment
