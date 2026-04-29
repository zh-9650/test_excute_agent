import json
from backend.engine.parser.csv_parser import CSVParser
from backend.engine.parser.enricher import CaseEnricher
from backend.engine.generator.generator import ScriptGenerator
from backend.storage.database import init_db, get_db


def real_csv():
    return """所属模块,测试点,前置条件,步骤,预期,关键词,优先级,测试类型,适用阶段
/文档中心(#145),进入页面查看并点击新建,1. 用户已登录,1. 进入/文档中心(#145)页面 2. 点击新建按钮 3. 观察列表,1. 正确展示 2. 显示12条,文档,1,功能测试,系统测试阶段
/文档中心(#145),进入页面新建文档,1. 用户已登录,1. 进入/文档中心页面 2. 点击新建 3. 输入标题 4. 保存,1. 创建成功 2. 列表出现新文档,新建,1,功能测试,系统测试阶段
/文档中心(#145),进入页面删除文档,1. 用户已登录 2. 存在文档A,1. 进入/文档中心页面 2. 选择文档A 3. 点击删除 4. 确认,1. 删除成功 2. 列表刷新,删除,1,功能测试,系统测试阶段
"""


def test_full_pipeline_parse_to_script():
    """完整管线：解析 → 补全评估 → 脚本生成"""
    parser = CSVParser()
    cases = parser.parse(real_csv())
    assert len(cases) == 3

    enricher = CaseEnricher()
    results = enricher.batch_evaluate(cases)
    assert len(results["ready"]) >= 1

    gen = ScriptGenerator()
    for case_id in results["ready"]:
        case = next(c for c in cases if c.id == case_id)
        script = gen.build_script_template(case, {})
        assert "from playwright.async_api import" in script
        precheck = gen.precheck(script)
        assert precheck["valid"] is True, f"Script failed precheck: {precheck['errors']}"


def test_end_to_end_state_transitions():
    """端到端状态转换验证"""
    parser = CSVParser()
    cases = parser.parse(real_csv())
    case = cases[0]
    assert case.status.value == "pending"

    case.transition_to(case.status.__class__.EXPLORING)
    assert case.status.value == "exploring"

    case.transition_to(case.status.__class__.GENERATING)
    assert case.status.value == "generating"

    case.transition_to(case.status.__class__.RUNNING)
    assert case.status.value == "running"

    case.transition_to(case.status.__class__.PASSED)
    assert case.status.value == "passed"


def test_database_persistence():
    """数据库持久化测试"""
    init_db()
    parser = CSVParser()
    cases = parser.parse(real_csv())

    db = get_db()
    suite_id = "test-suite-int-001"
    db.execute("INSERT OR REPLACE INTO test_suites (id, name, case_count) VALUES (?, ?, ?)",
               (suite_id, "test", len(cases)))

    for case in cases:
        db.execute(
            """INSERT OR REPLACE INTO test_cases
               (id, suite_id, module, title, steps, expected, status)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (case.id, suite_id, case.module, case.title,
             json.dumps([{"order": s.order, "action": s.action} for s in case.steps], ensure_ascii=False),
             case.expected, case.status.value)
        )
    db.commit()

    rows = db.execute("SELECT * FROM test_cases WHERE suite_id = ?", (suite_id,)).fetchall()
    assert len(rows) == 3

    db.execute("DELETE FROM test_cases WHERE suite_id = ?", (suite_id,))
    db.execute("DELETE FROM test_suites WHERE id = ?", (suite_id,))
    db.commit()
    db.close()


def test_enrichment_to_script_pipeline():
    """补全 → 脚本生成管线"""
    parser = CSVParser()
    cases = parser.parse(real_csv())
    enricher = CaseEnricher()

    for case in cases:
        eval_result = enricher.evaluate(case)
        if eval_result["needs_enrichment"]:
            enricher.apply_enrichment(case, {
                "target_url": "/doc-center",
                "selector_hint": "button.action-btn"
            })
            assert case.completeness == "enriched"
            for step in case.steps:
                assert step.is_enriched is True

    # 验证可从所有用例生成脚本
    gen = ScriptGenerator()
    for case in cases:
        script = gen.build_script_template(case, {})
        assert len(script) > 0
        result = gen.precheck(script)
        assert result["valid"] is True
