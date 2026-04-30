import json
from backend.engine.reporter.reporter import ReportGenerator


def test_generate_markdown_report():
    gen = ReportGenerator(
        templates_dir="backend/templates"
    )
    run_data = {
        "run_id": "run-001", "target_url": "https://test.com",
        "started_at": "2026-04-29T14:30:00", "finished_at": "2026-04-29T14:52:00",
        "summary": {"total": 10, "passed": 8, "failed": 1, "blocked": 1, "error": 0},
        "module_stats": [{"module": "/场景管理", "total": 10, "passed": 8, "failed": 1, "blocked": 1, "error": 0}],
        "failed_cases": [{
            "case_id": "1", "module": "/场景", "case_title": "全选删除",
            "step": 1, "action": "全选删除",
            "ai_judgment": "bug", "ai_confidence": 0.91,
            "ai_reasoning": "按钮无响应", "screenshot": "shots/c1.png"
        }],
        "blocked_cases": [], "error_cases": [],
        "ai_decisions": [{"case_id": "1", "case_title": "全选删除", "scenario": "selector_failure", "judgment": "bug", "confidence": 0.91, "reasoning": "button disappeared"}],
        "ai_call_count": 3,
        "env_info": {"playwright": "1.52", "browser": "Chromium"}
    }
    md = gen.generate_markdown(run_data)
    assert "# 测试报告" in md
    assert "run-001" in md
    assert "全选删除" in md
    assert "bug" in md


def test_generate_json_report():
    gen = ReportGenerator(
        templates_dir="backend/templates"
    )
    run_data = {
        "run_id": "r1", "target_url": "",
        "started_at": "", "finished_at": "",
        "summary": {"total": 5, "passed": 5, "failed": 0, "blocked": 0, "error": 0},
        "module_stats": [], "failed_cases": [], "blocked_cases": [], "error_cases": [],
        "ai_decisions": [], "ai_call_count": 0, "env_info": {}
    }
    json_str = gen.generate_json(run_data)
    data = json.loads(json_str)
    assert data["run_id"] == "r1"
    assert data["summary"]["total"] == 5
