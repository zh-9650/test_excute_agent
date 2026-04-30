"""AI 驱动探索引擎 — AI 在真实 UI 上逐步预执行测试用例"""
import json
import re
import asyncio
from dataclasses import dataclass, field
from backend.engine.explorer.browser import BrowserController, ElementInfo
from backend.engine.explorer.prompts import (
    EXPLORATION_SYSTEM_PROMPT, EXPLORATION_USER_TEMPLATE,
    ASSERTION_SYSTEM_PROMPT, ASSERTION_USER_TEMPLATE,
)


async def _default_log(level: str, msg: str):
    pass


@dataclass
class StepRecord:
    """单步探索记录"""
    step_num: int
    action_desc: str
    ai_action: str = ""
    ai_selector: str = ""
    ai_value: str = ""
    ai_reasoning: str = ""
    ai_confidence: float = 0.0
    executed: bool = False
    success: bool = False
    error: str = ""
    screenshot_before: str = ""
    screenshot_after: str = ""
    retry_count: int = 0


@dataclass
class CaseExplorationResult:
    """单用例探索结果"""
    case_id: str
    case_title: str
    status: str = "pending"
    steps: list = field(default_factory=list)
    total_retries: int = 0


class AIExplorer:
    def __init__(self, browser: BrowserController, ai_provider, log_callback=None, max_step_retries: int = 5):
        self.browser = browser
        self.ai = ai_provider
        self.log = log_callback or _default_log
        self._max_step_retries = max_step_retries

    async def explore_case(self, case, run_id: str) -> CaseExplorationResult:
        """探索单个用例 — AI 逐步在真实 UI 上操作"""
        result = CaseExplorationResult(case_id=case.id, case_title=case.title, status="exploring")
        await self.log("info", f"  Exploring case: {case.title} ({len(case.steps)} steps)")

        for step in case.steps:
            record = StepRecord(step_num=step.order, action_desc=step.action)
            result.steps.append(record)

            success = await self._execute_step_with_retry(case, step, record, run_id, result)
            if not success:
                result.status = "explore_failed"
                await self.log("info", f"  Case exploration failed at step {step.order}")
                return result

        result.status = "explored"
        await self.log("info", f"  Case exploration succeeded: {case.title}")
        return result

    async def _execute_step_with_retry(self, case, step, record: StepRecord, run_id: str, result: CaseExplorationResult) -> bool:
        """执行单步，最多重试 max_step_retries 次"""
        for attempt in range(self._max_step_retries):
            record.retry_count = attempt

            # 截图
            screenshot_path = f"test_artifacts/{run_id}/explore_{case.id}_s{step.order}_a{attempt}.png"
            try:
                await self.browser.take_screenshot(screenshot_path)
                record.screenshot_before = screenshot_path
            except Exception:
                pass

            # 收集元素
            elements = await self.browser.collect_interactive_elements()
            elements_text = self._format_elements(elements)

            # 发送给 AI 决策
            user_prompt = EXPLORATION_USER_TEMPLATE.format(
                case_title=case.title,
                preconditions=case.preconditions or "无",
                step_num=step.order,
                step_action=step.action,
                expected=case.expected or "无",
                elements_text=elements_text,
            )

            try:
                # 使用 explore_decide 获取完整决策（包含 selector/value）
                if hasattr(self.ai, 'explore_decide'):
                    decision = await self.ai.explore_decide(EXPLORATION_SYSTEM_PROMPT, user_prompt)
                else:
                    response = await self.ai.analyze(EXPLORATION_SYSTEM_PROMPT, user_prompt)
                    decision = self._parse_decision(response)
                record.ai_action = decision.get("action", "")
                record.ai_selector = decision.get("selector", "")
                record.ai_value = decision.get("value", "")
                record.ai_reasoning = decision.get("reasoning", "")
                record.ai_confidence = decision.get("confidence", 0)

                await self.log("info", f"    [Step {step.order}] AI: {record.ai_action} → {record.ai_selector} (conf={record.ai_confidence:.2f}, attempt={attempt+1})")

                # 执行操作
                exec_result = await self._execute_action(record.ai_action, record.ai_selector, record.ai_value)
                record.executed = True

                if exec_result["success"]:
                    record.success = True
                    await asyncio.sleep(1)
                    after_path = f"test_artifacts/{run_id}/explore_{case.id}_s{step.order}_after.png"
                    try:
                        await self.browser.take_screenshot(after_path)
                        record.screenshot_after = after_path
                    except Exception:
                        pass
                    return True
                else:
                    record.error = exec_result.get("error", "")
                    await self.log("info", f"    [Step {step.order}] 执行失败: {record.error[:100]}, 重试 {attempt+1}/{self._max_step_retries}")

            except Exception as e:
                record.error = str(e)
                await self.log("error", f"    [Step {step.order}] 异常: {e}")

            result.total_retries += 1

        return False

    async def _execute_action(self, action: str, selector: str, value: str) -> dict:
        """执行 AI 返回的操作"""
        try:
            if action == "click":
                await self.browser.page.click(selector, timeout=5000)
            elif action == "fill":
                await self.browser.page.fill(selector, value, timeout=5000)
            elif action == "select":
                await self.browser.page.select_option(selector, value, timeout=5000)
            elif action == "navigate":
                if value:
                    await self.browser.goto(value)
                else:
                    return {"success": False, "error": "navigate action missing URL"}
            elif action == "assert":
                pass
            elif action == "wait":
                await asyncio.sleep(2)
            elif action == "scroll":
                await self.browser.page.evaluate("window.scrollBy(0, 300)")
            else:
                return {"success": False, "error": f"Unknown action: {action}"}
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _format_elements(self, elements: list[ElementInfo]) -> str:
        lines = []
        for i, el in enumerate(elements[:50]):
            attrs = el.attributes or {}
            parts = [f"[{i}] <{el.tag}>"]
            if el.text:
                parts.append(f"text='{el.text}'")
            if attrs.get("type"):
                parts.append(f"type='{attrs['type']}'")
            if attrs.get("placeholder"):
                parts.append(f"placeholder='{attrs['placeholder']}'")
            if attrs.get("name"):
                parts.append(f"name='{attrs['name']}'")
            if el.aria_label:
                parts.append(f"aria='{el.aria_label}'")
            if el.selector:
                parts.append(f"selector='{el.selector}'")
            lines.append(" ".join(parts))
        return "\n".join(lines)

    def _parse_decision(self, response) -> dict:
        """解析 AI 响应为决策字典"""
        # 如果是 AIResponse 对象，直接从 action 字段提取
        if hasattr(response, "action") and hasattr(response, "confidence"):
            action = response.action
            if isinstance(action, dict):
                # action 是 dict（旧格式）
                return action
            elif isinstance(action, str) and action:
                # action 是字符串（探索格式），构建完整决策
                return {
                    "action": action,
                    "selector": getattr(response, "reasoning", ""),  # reasoning 字段可能包含 selector
                    "value": "",
                    "reasoning": getattr(response, "reasoning", ""),
                    "confidence": getattr(response, "confidence", 0),
                }
        if isinstance(response, dict):
            if "action" in response:
                return response
        try:
            parsed = json.loads(str(response))
            if isinstance(parsed, dict):
                return parsed
        except (json.JSONDecodeError, TypeError):
            pass
        try:
            match = re.search(r'\{[^{}]*\}', str(response))
            if match:
                return json.loads(match.group())
        except (json.JSONDecodeError, TypeError):
            pass
        return {}
