import ast
import json
from backend.models.case import TestCase


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
            selector = step_record.ai_selector
            value = step_record.ai_value

            if action == "navigate":
                steps_code.append(f'            await page.goto("{value}")')
            elif action == "click":
                steps_code.append(f"            await page.click('{selector}')")
            elif action == "fill":
                value_escaped = value.replace("'", "\\'")
                steps_code.append(f"            await page.fill('{selector}', '{value_escaped}')")
            elif action == "select":
                steps_code.append(f"            await page.select_option('{selector}', '{value}')")
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
