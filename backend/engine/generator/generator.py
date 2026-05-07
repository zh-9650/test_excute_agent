import ast
import json
from backend.models.case import TestCase
from backend.engine.explorer.prompts import (
    SCRIPT_GENERATION_SYSTEM_PROMPT,
    SCRIPT_GENERATION_TEMPLATE,
)


class ScriptGenerator:
    def __init__(self, ai=None):
        self.ai = ai

    def build_script_template(self, case: TestCase, element_map: dict) -> str:
        steps_code = []
        for step in case.steps:
            action = step.action
            selector = self._find_selector(action, element_map, case.module)
            if any(kw in action for kw in ["进入", "打开", "跳转"]):
                url = step.enrichment.get("target_url", "") if step.enrichment else ""
                steps_code.append(f'            await page.goto("{url}")')
            elif "点击" in action:
                if selector:
                    steps_code.append(f"            await page.click('{selector}')")
                else:
                    steps_code.append(f'            # TODO: selector unknown - {action}')
            elif "输入" in action:
                if selector:
                    steps_code.append(f"            await page.fill('{selector}', 'test_data')")
                else:
                    steps_code.append(f'            # TODO: selector unknown - {action}')
            elif any(kw in action for kw in ["观察", "查看", "检查"]):
                if selector:
                    steps_code.append(f"            await expect(page.locator('{selector}')).to_be_visible()")
                else:
                    steps_code.append(f'            # Observe: {action}')

        assertions = self._build_assertions(case.expected)

        script = f'''import asyncio
from playwright.async_api import async_playwright, expect

async def test_{case.id.replace("-", "_")}():
    """Test: {case.title}"""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={{"width": 1920, "height": 1080}},
            locale="zh-CN"
        )
        page = await context.new_page()
        try:
{chr(10).join(steps_code) if steps_code else "            pass"}

            # Assertions
{chr(10).join(assertions) if assertions else "            pass"}

            print("PASS: {case.title}")
        except Exception as e:
            print(f"FAIL: {case.title} - {{e}}")
            await page.screenshot(path=f"failure_{case.id}.png")
            raise
        finally:
            await browser.close()
'''
        return script

    async def generate_with_ai(self, case: TestCase, element_map: dict) -> str | None:
        if not self.ai:
            return None

        elements_desc = []
        for module, elems in element_map.items():
            for e in elems[:30]:
                elements_desc.append({"module": module, "tag": e.get("tag", ""),
                                      "text": e.get("text", ""),
                                      "selector": e.get("selector", "")})

        context = {
            "case_title": case.title,
            "module": case.module,
            "preconditions": case.preconditions,
            "steps": [{"order": s.order, "action": s.action,
                        "target_url": s.enrichment.get("target_url", "") if s.enrichment else ""}
                       for s in case.steps],
            "expected": case.expected,
            "elements": elements_desc
        }

        try:
            raw = await self.ai.generate_script(context)
            if raw and ("async def" in raw or "def test" in raw):
                # 确保包含至少一个 Playwright API 调用
                playwright_apis = ["page.", "goto(", "click(", "fill(", "locator(", "get_by_"]
                if any(api in raw for api in playwright_apis):
                    return raw
                # 即使没有明确的 Playwright API，如果有 def 和 import，也返回
                if "import" in raw and "def" in raw:
                    return raw
        except Exception:
            pass

        return None

    def generate_from_exploration(self, case, exploration_result) -> str:
        """将探索记录直接转换为 Playwright 脚本（无需 AI）"""
        steps_code = []
        for step_record in exploration_result.steps:
            if not step_record.success:
                continue
            action = step_record.ai_action
            selector = step_record.ai_selector.replace("'", "\\'")
            value = step_record.ai_value.replace("'", "\\'")

            if action == "navigate":
                steps_code.append(f'            await page.goto("{value}")')
            elif action == "click":
                steps_code.append(f"            await page.click('{selector}')")
            elif action == "fill":
                steps_code.append(f"            await page.click('{selector}')")
                steps_code.append(f"            await page.fill('{selector}', '')")
                steps_code.append(f"            await page.type('{selector}', '{value}', delay=50)")
            elif action == "select":
                steps_code.append(f"            await page.select_option('{selector}', '{value}')")
            elif action == "hover":
                steps_code.append(f"            await page.hover('{selector}')")
            elif action == "scroll":
                steps_code.append('            await page.evaluate("window.scrollBy(0, 300)")')
            elif action == "wait":
                steps_code.append("            await asyncio.sleep(2)")

        if not steps_code:
            steps_code.append("            pass  # No successful exploration steps")

        script = f'''import asyncio
from playwright.async_api import async_playwright, expect

async def test_{case.id.replace("-", "_")}():
    """Test: {case.title} (from exploration)"""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={{"width": 1920, "height": 1080}},
            locale="zh-CN"
        )
        page = await context.new_page()
        try:
{chr(10).join(steps_code)}

            await page.screenshot(path=f"verify_{case.id}.png")
            print("PASS: {case.title}")
        except Exception as e:
            print(f"FAIL: {case.title} - {{e}}")
            await page.screenshot(path=f"failure_{case.id}.png")
            raise
        finally:
            await browser.close()
'''
        return script

    def _find_selector(self, action: str, element_map: dict, module: str) -> str:
        elements = element_map.get(module, [])
        for el in elements:
            if el.get("text") and el["text"] in action:
                return el["selector"]
        if elements:
            return elements[0].get("selector", "")
        return ""

    def _build_assertions(self, expected: str) -> list[str]:
        assertions = []
        expected_lines = [e.strip() for e in expected.split("\n") if e.strip()]
        for line in expected_lines[:3]:
            assertions.append(f'    # Expected: {line}')
        return assertions

    def precheck(self, script: str) -> dict:
        errors = []
        try:
            ast.parse(script)
        except SyntaxError as e:
            errors.append(f"Syntax error: {e}")
            return {"valid": False, "errors": errors}

        required_imports = ["playwright"]
        for imp in required_imports:
            if imp not in script.lower():
                errors.append(f"Missing import: {imp}")

        if "async def test_" not in script:
            errors.append("Missing async test function")

        forbidden = ["time.sleep", "driver.", "selenium"]
        for fb in forbidden:
            if fb in script:
                errors.append(f"Uses non-Playwright API: {fb}")

        return {"valid": len(errors) == 0, "errors": errors}


class AIScriptGenerator:
    """AI 驱动的脚本生成器 — 根据探索录制数据生成 Codex 风格的结构化 Playwright 脚本"""

    def __init__(self, ai):
        self.ai = ai

    async def generate_from_recording(self, case, recording) -> str:
        """从 ExplorationRecording 生成结构化 Playwright 脚本"""
        # 1. 构建步骤详情
        steps_detail = []
        for i, step in enumerate(recording.steps):
            step_info = {
                "order": i + 1,
                "action": step.ai_action,
                "selector": step.ai_selector,
                "value": step.ai_value,
                "reasoning": step.ai_reasoning,
                "success": step.success,
                "url_before": step.url_before,
                "url_after": step.url_after,
                "page_title_before": step.page_title_before,
                "page_title_after": step.page_title_after,
                "target_element_text": step.target_element_text,
                "parent_context": step.parent_context,
                "semantic_action": step.semantic_action,
                "function_name_hint": step.function_name_hint,
            }
            steps_detail.append(step_info)

        # 2. 构建页面地图摘要
        page_maps_summary = []
        for pm in recording.page_maps:
            pm_info = {
                "page_type": pm.page_type,
                "page_url": pm.page_url,
                "page_title": pm.page_title,
                "sections": [{"name": s.name, "type": s.section_type, "count": s.element_count} for s in pm.sections],
                "key_elements": pm.key_elements,
                "summary": pm.observation_summary,
            }
            page_maps_summary.append(pm_info)

        # 3. 构建上下文
        context = {
            "case_title": recording.case_title,
            "case_module": recording.case_module,
            "case_expected": recording.case_expected,
            "steps_detail": steps_detail,
            "page_maps": page_maps_summary,
            "identified_functions": recording.identified_functions,
            "base_url": steps_detail[0]["url_before"] if steps_detail else "",
        }

        context_json = json.dumps(context, ensure_ascii=False, indent=2)

        # 4. 调用 AI 生成脚本
        system_prompt = SCRIPT_GENERATION_SYSTEM_PROMPT
        user_prompt = SCRIPT_GENERATION_TEMPLATE.format(
            case_title=recording.case_title,
            case_module=recording.case_module,
            case_expected=recording.case_expected,
            context_json=context_json,
        )

        raw_script = await self.ai.generate_structured_script(system_prompt, user_prompt)

        # 5. 后处理
        script = self._post_process(raw_script, case.id)

        # 6. 语法检查
        check = self.precheck(script)
        if not check["valid"]:
            # 语法错误时尝试修复常见问题
            script = self._try_fix_syntax(script, check["errors"])

        return script

    def _post_process(self, script: str, case_id: str) -> str:
        """后处理：清理、标准化"""
        # 确保有正确的导入
        if "from playwright.async_api" not in script and "import playwright" not in script:
            script = "import asyncio\nfrom playwright.async_api import async_playwright\n\n" + script

        # 确保有 asyncio.run
        if "asyncio.run(" not in script and "if __name__" not in script:
            script += '\n\nif __name__ == "__main__":\n    asyncio.run(main())\n'

        return script.strip()

    def _try_fix_syntax(self, script: str, errors: list[str]) -> str:
        """尝试修复常见语法问题"""
        # 如果有未闭合的字符串，尝试截断到最后一个完整语句
        lines = script.split("\n")
        for i in range(len(lines) - 1, -1, -1):
            try:
                ast.parse("\n".join(lines[:i + 1]))
                # 找到能解析的部分，加上结束代码
                fixed = "\n".join(lines[:i + 1])
                if "async def main" in fixed and "browser.close()" not in fixed:
                    fixed += '\n        finally:\n            await browser.close()\n'
                return fixed
            except SyntaxError:
                continue
        return script

    def precheck(self, script: str) -> dict:
        """语法和结构检查"""
        errors = []
        try:
            ast.parse(script)
        except SyntaxError as e:
            errors.append(f"Syntax error: {e}")
            return {"valid": False, "errors": errors}

        required_imports = ["playwright"]
        for imp in required_imports:
            if imp not in script.lower():
                errors.append(f"Missing import: {imp}")

        if "async def" not in script:
            errors.append("Missing async function")

        forbidden = ["time.sleep", "driver.", "selenium"]
        for fb in forbidden:
            if fb in script:
                errors.append(f"Uses non-Playwright API: {fb}")

        return {"valid": len(errors) == 0, "errors": errors}
