"""v3 探索提示词 — 用于 ExplorerAgent 的 AI 调用"""

EXPLORER_SYSTEM_PROMPT = """你是一个 UI 自动化测试执行器。你的任务是执行一个具体的测试步骤。

【重要】页面快照已经采集好了，直接在下面的快照中找到目标元素，然后执行操作。不要调用 snapshot 或 screenshot。

## 你必须做的

1. 阅读步骤描述
2. 在快照中找到目标元素（通过 role、name、placeholder、text 匹配）
3. 调用对应的操作工具（优先用 locator，其次 ref）

## 步骤描述 → 工具调用 对照表

| 步骤描述 | 调用工具 | 参数示例 |
|---------|---------|---------|
| "在XX输入框输入YY" | fill | fill(ref="el_001", value="YY") |
| "点击XX按钮" | click | click(ref="el_002") |
| "选择XX选项" | select_option | select_option(ref="el_003", value="XX") |
| "进入XX页面" | click | click(ref="el_004")  (找菜单/链接) |
| "验证XX可见" | expect_visible | expect_visible(ref="el_005") |

## 示例

步骤: "在用户名输入框输入 test_c"
→ 在快照中找 placeholder 或 name 包含"用户名"的输入框，假设是 el_008
→ 调用: fill(ref="el_008", value="test_c")

步骤: "点击登录按钮"
→ 在快照中找 role=button 且 text 或 name 包含"登录"的元素，假设是 el_011
→ 调用: click(ref="el_011")

## 规则

1. 只执行当前步骤，不要跳步
2. 必须调用工具，不要只返回文字
 3. 优先用 locator（来自元素的 locator_candidates），ref 只作为兜底（ref 格式如 el_001）
 4. 从步骤描述中提取操作值（如"输入 test_c" → value="test_c"）
 5. 如果上次尝试失败，请换一个元素或换一种 locator 策略（role/placeholder/text/css）"""

EXPLORER_USER_TEMPLATE = """## 测试步骤

用例: {case_title}
步骤 {step_num}/{total_steps}: {step_action}

## 历史

{history}

## 页面快照

{snapshot}

请在上面的快照中找到目标元素，然后调用工具执行 "{step_action}"。"""


def build_explorer_prompt(case, step_num: int, step_action: str, snapshot_text: str, history: str) -> str:
    """构建 ExplorerAgent 的用户提示词"""
    return EXPLORER_USER_TEMPLATE.format(
        case_title=case.title,
        module=getattr(case, 'module', ''),
        preconditions=getattr(case, 'preconditions', ''),
        step_num=step_num,
        total_steps=len(case.steps),
        step_action=step_action,
        history=history or "（首次操作，无历史）",
        snapshot=snapshot_text,
    )


def format_snapshot_for_prompt(snapshot) -> str:
    """将 SemanticSnapshot 格式化为 AI 可读的文本"""
    lines = [f"URL: {snapshot.url}", f"标题: {snapshot.title}", f"页面类型: {snapshot.page_type}", ""]

    for section in snapshot.sections:
        lines.append(f"### {section.name} ({section.type})")
        for el in section.elements:
            parts = [f"[{el.ref}] <{el.tag}>"]
            if el.role:
                parts.append(f"role={el.role}")
            if el.name:
                parts.append(f"name=\"{el.name}\"")
            if el.placeholder:
                parts.append(f"placeholder=\"{el.placeholder}\"")
            if el.text and el.text != el.name:
                parts.append(f"text=\"{el.text[:50]}\"")
            if not el.enabled:
                parts.append("(禁用)")
            lines.append("  " + " ".join(parts))
        lines.append("")

    return "\n".join(lines)


def format_history_for_prompt(steps_history: list) -> str:
    """将已执行步骤格式化为历史记录"""
    if not steps_history:
        return ""
    lines = []
    for i, step in enumerate(steps_history, 1):
        status = "✓" if step.get("success") else "✗"
        lines.append(f"{i}. [{status}] {step.get('action', '?')}: {step.get('message', '')}")
    return "\n".join(lines)
