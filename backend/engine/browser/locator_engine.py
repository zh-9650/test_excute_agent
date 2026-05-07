"""LocatorEngine — ref → Playwright locator 编译

按稳定性优先级选择 locator 策略：
1. data-testid / data-test
2. role + accessible name
3. label (aria-label)
4. placeholder
5. text
6. CSS (id/name)
"""

from backend.engine.browser.semantic_snapshot import SnapshotElement, LocatorCandidate


def compile_locator(page, element: SnapshotElement):
    """将 SnapshotElement 编译为 Playwright Locator

    按 locator_candidates 的顺序尝试，返回第一个可定位的 locator。
    如果所有候选都失败，回退到 CSS selector。
    """
    for candidate in element.locator_candidates:
        locator = _try_candidate(page, candidate)
        if locator is not None:
            return locator

    # 回退：用 tag + text 构建 CSS
    return page.locator(element.tag)


def compile_locator_from_dict(page, locator_dict: dict):
    """从 AI Decision 中的 locator 字典编译为 Playwright Locator

    locator_dict 格式: {"strategy": "placeholder", "value": "请输入文档标题"}
    或 {"strategy": "role", "role": "button", "name": "查询"}
    """
    strategy = locator_dict.get("strategy", "")

    if strategy == "testid":
        value = locator_dict.get("value", "")
        if value:
            return page.get_by_test_id(value)

    elif strategy == "role":
        role = locator_dict.get("role", "")
        name = locator_dict.get("name", "")
        if role:
            if name:
                return page.get_by_role(role, name=name)
            return page.get_by_role(role)

    elif strategy == "label":
        value = locator_dict.get("value", "")
        if value:
            return page.get_by_label(value)

    elif strategy == "placeholder":
        value = locator_dict.get("value", "")
        if value:
            return page.get_by_placeholder(value)

    elif strategy == "text":
        value = locator_dict.get("value", "")
        if value:
            return page.get_by_text(value, exact=True)

    elif strategy == "css":
        value = locator_dict.get("value", "")
        if value:
            return page.locator(value)

    elif strategy == "xpath":
        value = locator_dict.get("value", "")
        if value:
            return page.locator(f"xpath={value}")

    # 回退到 text
    value = locator_dict.get("value", "")
    if value:
        return page.get_by_text(value)

    return None


def _try_candidate(page, candidate: LocatorCandidate):
    """尝试将 LocatorCandidate 编译为 Playwright Locator"""
    strategy = candidate.strategy

    if strategy == "testid":
        if candidate.value:
            return page.get_by_test_id(candidate.value)

    elif strategy == "role":
        if candidate.role:
            if candidate.name:
                return page.get_by_role(candidate.role, name=candidate.name)
            return page.get_by_role(candidate.role)

    elif strategy == "label":
        if candidate.value:
            return page.get_by_label(candidate.value)

    elif strategy == "placeholder":
        if candidate.value:
            return page.get_by_placeholder(candidate.value)

    elif strategy == "text":
        if candidate.value:
            return page.get_by_text(candidate.value, exact=True)

    elif strategy == "css":
        if candidate.value:
            return page.locator(candidate.value)

    return None


def get_best_locator_str(element: SnapshotElement) -> str:
    """获取最佳 locator 的 Python 代码字符串，用于脚本生成"""
    for candidate in element.locator_candidates:
        code = _candidate_to_code(candidate)
        if code:
            return code

    # 回退
    return f'page.locator("{element.tag}")'


def locator_dict_to_code(locator_dict: dict) -> str:
    """将 locator 字典转换为 Playwright Python 代码字符串"""
    strategy = locator_dict.get("strategy", "")
    value = locator_dict.get("value", "")

    if strategy == "testid":
        return f'page.get_by_test_id("{_escape(value)}")'
    elif strategy == "role":
        role = locator_dict.get("role", "")
        name = locator_dict.get("name", "")
        if name:
            return f'page.get_by_role("{_escape(role)}", name="{_escape(name)}")'
        return f'page.get_by_role("{_escape(role)}")'
    elif strategy == "label":
        return f'page.get_by_label("{_escape(value)}")'
    elif strategy == "placeholder":
        return f'page.get_by_placeholder("{_escape(value)}")'
    elif strategy == "text":
        return f'page.get_by_text("{_escape(value)}")'
    elif strategy == "css":
        return f'page.locator("{_escape(value)}")'
    elif strategy == "xpath":
        return f'page.locator("xpath={_escape(value)}")'

    if value:
        return f'page.get_by_text("{_escape(value)}")'
    return 'page.locator("unknown")'


def _candidate_to_code(candidate: LocatorCandidate) -> str:
    """将 LocatorCandidate 转换为 Python 代码字符串"""
    if candidate.strategy == "testid":
        return f'page.get_by_test_id("{_escape(candidate.value)}")'
    elif candidate.strategy == "role":
        if candidate.name:
            return f'page.get_by_role("{_escape(candidate.role)}", name="{_escape(candidate.name)}")'
        return f'page.get_by_role("{_escape(candidate.role)}")'
    elif candidate.strategy == "label":
        return f'page.get_by_label("{_escape(candidate.value)}")'
    elif candidate.strategy == "placeholder":
        return f'page.get_by_placeholder("{_escape(candidate.value)}")'
    elif candidate.strategy == "text":
        return f'page.get_by_text("{_escape(candidate.value)}")'
    elif candidate.strategy == "css":
        return f'page.locator("{_escape(candidate.value)}")'
    return ""


def _escape(s: str) -> str:
    """转义字符串中的引号和反斜杠"""
    return s.replace("\\", "\\\\").replace('"', '\\"')
