import pytest
from backend.engine.parser.csv_parser import CSVParser
from backend.engine.parser.enricher import CaseEnricher
from backend.models.case import TestCase, Step


@pytest.fixture
def sample_csv_utf8():
    return """所属模块,测试点,前置条件,步骤,预期,关键词,优先级,测试类型,适用阶段
/场景管理(#147),场景列表正确展示,1. 用户已登录,1. 进入页面 2. 观察列表,1. 正确展示 2. 显示3条,场景,1,功能测试,系统测试阶段
/场景管理(#147),新增场景-正常流程,1. 用户已登录,1. 点击新增 2. 输入名称 3. 保存,1. 创建成功 2. 列表刷新,新增,1,功能测试,系统测试阶段
"""


def test_parse_csv_utf8(sample_csv_utf8):
    parser = CSVParser()
    cases = parser.parse(sample_csv_utf8)
    assert len(cases) == 2
    assert cases[0].module == "/场景管理(#147)"
    assert cases[0].title == "场景列表正确展示"
    assert len(cases[0].steps) == 2
    assert cases[0].priority == 1


def test_parse_csv_with_gbk():
    parser = CSVParser()
    content = "所属模块,测试点,前置条件,步骤,预期,关键词,优先级,测试类型,适用阶段\n/测试,测试点1,条件,1. 步骤1,1. 预期1,关键,1,功能测试,系统测试阶段"
    cases = parser.parse(content.encode("gb2312"))
    assert len(cases) == 1


def test_parse_empty_steps():
    parser = CSVParser()
    content = "所属模块,测试点,前置条件,步骤,预期,关键词,优先级,测试类型,适用阶段\n/测试,测试点1,条件,,1. 预期1,,1,功能测试,系统测试阶段"
    cases = parser.parse(content)
    assert cases[0].steps == []


def test_parse_missing_columns():
    parser = CSVParser()
    content = "所属模块,测试点\n/测试,测试点1"
    cases = parser.parse(content)
    assert len(cases) == 0


def test_completeness_detection_complete():
    parser = CSVParser()
    content = "所属模块,测试点,前置条件,步骤,预期,关键词,优先级,测试类型,适用阶段\n/测试,进入页面查看列表,1. 已登录,1. 进入/场景页面 2. 点击新增按钮 3. 观察列表,1. 列表展示,,1,功能测试,系统测试阶段"
    cases = parser.parse(content)
    assert cases[0].completeness == "complete"


def test_completeness_detection_incomplete():
    parser = CSVParser()
    content = "所属模块,测试点,前置条件,步骤,预期,关键词,优先级,测试类型,适用阶段\n/测试,点击编辑,1. 已登录,1. 点击编辑,1. 弹窗出现,,1,功能测试,系统测试阶段"
    cases = parser.parse(content)
    assert cases[0].completeness == "incomplete"


# --- Enricher tests ---

@pytest.fixture
def incomplete_case():
    return TestCase(
        id="c-001", suite_id="s-001",
        module="/场景管理(#147)", title="编辑按钮",
        steps=[Step(order=1, action="点击编辑按钮")],
        expected="弹出编辑弹窗",
        completeness="incomplete"
    )


@pytest.fixture
def complete_case():
    return TestCase(
        id="c-002", suite_id="s-001",
        module="/场景管理(#147)", title="进入场景页面查看列表",
        steps=[Step(order=1, action="进入/场景管理(#147)页面"), Step(order=2, action="观察列表")],
        expected="展示场景列表",
        completeness="complete"
    )


def test_enricher_skips_complete_cases(complete_case):
    enricher = CaseEnricher(ai_provider=None)
    result = enricher.evaluate(complete_case)
    assert result["needs_enrichment"] is False


def test_enricher_detects_incomplete(incomplete_case):
    enricher = CaseEnricher(ai_provider=None)
    result = enricher.evaluate(incomplete_case)
    assert result["needs_enrichment"] is True
    assert "target_url" in result["template"]
    assert "selector_hint" in result["template"]


def test_batch_evaluate():
    enricher = CaseEnricher(ai_provider=None)
    cases = [
        TestCase(id="1", suite_id="s", module="/m", title="进入页面查看", steps=[Step(1, "进入/m页面")], completeness="complete"),
        TestCase(id="2", suite_id="s", module="/m", title="点击按钮", steps=[Step(1, "点击按钮")], completeness="incomplete"),
    ]
    results = enricher.batch_evaluate(cases)
    assert len(results["needs_enrichment"]) == 1
    assert len(results["ready"]) == 1


def test_apply_enrichment(incomplete_case):
    enricher = CaseEnricher(ai_provider=None)
    enricher.apply_enrichment(incomplete_case, {
        "target_url": "/scenario/1",
        "selector_hint": "button.edit-btn"
    })
    assert incomplete_case.completeness == "enriched"
    for step in incomplete_case.steps:
        assert step.is_enriched is True
