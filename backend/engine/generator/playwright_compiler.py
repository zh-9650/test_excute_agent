"""PlaywrightCompiler — ActionIR → Playwright Python 脚本

确定性编译，不依赖 AI。将 ActionIR 中的每一步转换为 Playwright API 调用。

Locator 优先级：
1. get_by_test_id
2. get_by_role + name
3. get_by_label
4. get_by_placeholder
5. get_by_text
6. locator (CSS)
"""

import re
import ast
from backend.engine.recorder.action_ir import ActionIR, ActionStep
from backend.engine.browser.locator_engine import locator_dict_to_code


class PlaywrightCompiler:
    def compile(self, ir: ActionIR) -> str:
        """将 ActionIR 编译为 Playwright Python 脚本"""
        lines = []
        safe_id = _sanitize_identifier(ir.case_id)
        lines.append(_HEADER.format(
            case_id=safe_id,
            case_title=_escape_str(ir.case_title),
        ))

        for step in ir.steps:
            step_lines = self._compile_step(step)
            if step_lines:
                lines.append(f"        # 步骤 {step.order}: {step.natural_step}")
                lines.extend(step_lines)

        # 断言
        if ir.expected:
            lines.append(f"        # 预期结果: {ir.expected}")
            lines.append(f"        # TODO: 请根据预期结果添加断言")

        lines.append(_FOOTER.format(case_id=safe_id))
        return "\n".join(lines)

    def _compile_step(self, step: ActionStep) -> list[str]:
        """编译单个步骤（可能包含多个 tool calls）"""
        indent = "        "  # 8 spaces, inside async with block

        # 优先使用录制的 tool_calls（支持一个自然语言步骤对应多个动作）
        if step.tool_calls:
            import json

            out: list[str] = []
            for tc in step.tool_calls:
                result = tc.get("result", {})
                if result and not result.get("success", True):
                    continue
                func = tc.get("function", {})
                name = func.get("name", "")
                if name in ("snapshot", "screenshot"):
                    continue
                args_raw = func.get("arguments", {}) or {}
                if isinstance(args_raw, str):
                    try:
                        args = json.loads(args_raw)
                    except Exception:
                        args = {}
                elif isinstance(args_raw, dict):
                    args = args_raw
                else:
                    args = {}

                line = self._compile_tool_call(name, args, indent)
                if line:
                    out.append(line)
            return out

        # 回退：使用抽取后的单动作字段
        action = step.action
        locator_code = self._get_locator_code(step)

        if action == "navigate":
            url = step.value or step.locator.get("value", "")
            return [f'{indent}await page.goto("{_escape_str(url)}")']

        elif action == "click":
            if locator_code:
                return [f"{indent}await {locator_code}.click()"]
            return []

        elif action == "fill":
            value = _escape_str(step.value)
            if locator_code:
                return [f'{indent}await {locator_code}.fill("{value}")']
            return []

        elif action == "hover":
            if locator_code:
                return [f"{indent}await {locator_code}.hover()"]
            return []

        elif action == "select_option":
            value = _escape_str(step.value)
            if locator_code:
                return [f'{indent}await {locator_code}.select_option("{value}")']
            return []

        elif action == "press_key":
            key = _escape_str(step.value)
            return [f'{indent}await page.keyboard.press("{key}")']

        elif action == "wait":
            ms = int(step.value) if step.value.isdigit() else 1000
            return [f"{indent}await page.wait_for_timeout({ms})"]

        elif action == "assert_visible":
            if locator_code:
                return [f"{indent}await {locator_code}.wait_for(state='visible')"]
            return []

        elif action == "assert_text":
            text = _escape_str(step.value)
            return [f'{indent}await page.get_by_text("{text}").wait_for(state="visible")']

        elif action == "assert_url":
            url_pattern = _escape_str(step.value)
            return [f'{indent}assert "{url_pattern}" in page.url']

        elif action in ("done", "blocked"):
            return [f"{indent}# {action}: {step.error or step.reason}"]

        return [f"{indent}# 未知动作: {action}"]

    def _compile_tool_call(self, name: str, args: dict, indent: str) -> str:
        locator = args.get("locator") or {}
        locator_code = locator_dict_to_code(locator) if locator and locator.get("strategy") else ""

        if name == "navigate":
            url = args.get("url", "")
            return f'{indent}await page.goto("{_escape_str(url)}")' if url else ""
        if name == "click":
            return f"{indent}await {locator_code}.click()" if locator_code else ""
        if name == "fill":
            value = _escape_str(str(args.get("value", "")))
            return f'{indent}await {locator_code}.fill("{value}")' if locator_code else ""
        if name == "hover":
            return f"{indent}await {locator_code}.hover()" if locator_code else ""
        if name == "select_option":
            value = _escape_str(str(args.get("value", "")))
            return f'{indent}await {locator_code}.select_option("{value}")' if locator_code else ""
        if name == "press_key":
            key = _escape_str(str(args.get("key", "")))
            return f'{indent}await page.keyboard.press("{key}")' if key else ""
        if name == "wait":
            ms = int(args.get("ms", 1000) or 1000)
            return f"{indent}await page.wait_for_timeout({ms})"
        if name == "expect_visible":
            return f"{indent}await {locator_code}.wait_for(state='visible')" if locator_code else ""
        if name == "expect_text":
            text = _escape_str(str(args.get("text", "")))
            return f'{indent}await page.get_by_text("{text}").wait_for(state="visible")' if text else ""
        if name == "expect_url":
            pattern = _escape_str(str(args.get("url_pattern", "")))
            return f'{indent}assert "{pattern}" in page.url' if pattern else ""

        return ""

    def _get_locator_code(self, step: ActionStep) -> str:
        """获取步骤的 Playwright locator 代码"""
        # 优先用 locator 字典
        if step.locator and step.locator.get("strategy"):
            return locator_dict_to_code(step.locator)

        # 用 target_ref 构建（需要快照上下文，这里回退到 tag）
        if step.target_ref:
            # 没有快照上下文，无法解析 ref，用注释标记
            return ""

        return ""

    def compile_with_validation(self, ir: ActionIR) -> tuple[str, list[str]]:
        """编译并验证脚本"""
        script = self.compile(ir)
        errors = self.validate(script)
        return script, errors

    def validate(self, script: str) -> list[str]:
        """验证脚本的语法和基本规则"""
        errors = []

        # AST 语法检查
        try:
            ast.parse(script)
        except SyntaxError as e:
            errors.append(f"语法错误: {e}")
            return errors

        # 检查导入
        if "playwright" not in script:
            errors.append("缺少 playwright 导入")

        # 检查 async def
        if "async def" not in script:
            errors.append("缺少 async def")

        # 检查禁止的 API
        forbidden = ["selenium", "time.sleep", "webdriver"]
        for f in forbidden:
            if f in script:
                errors.append(f"包含禁止的 API: {f}")

        return errors


_HEADER = '''"""自动生成的 Playwright 测试脚本
用例: {case_title}
ID: {case_id}

由 ActionIR 编译生成，请勿手动修改。
"""

import asyncio
from playwright.async_api import async_playwright


async def test_{case_id}():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()
'''

_FOOTER = '''
        await browser.close()


if __name__ == "__main__":
    asyncio.run(test_{case_id}())
'''


def _sanitize_identifier(s: str) -> str:
    """将字符串转为合法 Python 标识符（保留字母数字下划线）"""
    s = re.sub(r'[^a-zA-Z0-9_]', '_', s)
    if s and s[0].isdigit():
        s = 'id_' + s
    return s or 'case'


def _escape_str(s: str) -> str:
    """转义字符串中的引号和反斜杠"""
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
