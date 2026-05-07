import asyncio
import json
import re
import time
import os
from dataclasses import dataclass, field
from backend.models.case import TestCase, CaseStatus
from backend.engine.executor.healing import HealingStore
from backend.engine.executor.ai_guard import AIGuard


@dataclass
class ExecutionContext:
    case: TestCase
    session_id: str
    ai_call_count: int = 0
    retry_count: int = 0
    max_retries: int = 3
    step_results: list[dict] = field(default_factory=list)


class SmartExecutor:
    """逐步执行器：直接用 Playwright 按测试步骤操作，失败时 AI 实时介入"""

    def __init__(self, browser=None, ai=None, backup_ai=None, log_callback=None, ai_guard=None, target_url=""):
        self.browser = browser
        self.ai = ai
        self.backup_ai = backup_ai
        self.healing = HealingStore()
        self._log = log_callback or (lambda msg: None)
        self.guard = ai_guard or AIGuard()
        self._base_url = target_url

    async def execute_case(self, ctx: ExecutionContext) -> dict:
        case = ctx.case
        await self._log(f"[{case.title}] Starting execution ({len(case.steps)} steps)")

        all_passed = True
        for step in case.steps:
            self.guard.record_step()
            result = await self._execute_step(ctx, step)
            ctx.step_results.append(result)
            if result["status"] != "passed":
                all_passed = False
                if result.get("fatal"):
                    break

        if all_passed:
            self.guard.record_pass()
            case.transition_to(CaseStatus.PASSED)
            return {"case_id": case.id, "status": "passed", "steps": ctx.step_results}
        else:
            self.guard.record_fail()
            final_status = "failed" if any(r.get("ai_judgment") == "bug" for r in ctx.step_results) else "error"
            case.transition_to(CaseStatus.FAILED if final_status == "failed" else CaseStatus.ERROR)
            return {"case_id": case.id, "status": final_status, "steps": ctx.step_results}

    def is_melted(self) -> bool:
        return self.guard.is_melted

    def melt_reason(self) -> str:
        return self.guard.melt_reason

    async def _execute_step(self, ctx: ExecutionContext, step) -> dict:
        action = step.action
        target_url = step.enrichment.get("target_url", "") if step.enrichment else ""

        try:
            if any(kw in action for kw in ["进入", "打开", "跳转"]):
                if target_url:
                    await self.browser.goto(target_url)
                else:
                    await self.browser.goto(self._base_url)
                await self.browser.wait_for_page_ready()
                await asyncio.sleep(1)

                # 验证没有卡在登录页
                try:
                    pwd = self.browser.page.locator("input[type='password']")
                    if await pwd.count() > 0 and await pwd.first.is_visible():
                        await self._log(f"  WARNING: landed on login page after navigation!")
                        return {"step": step.order, "action": action, "status": "failed",
                                "reason": "Navigation landed on login page instead of target"}
                except Exception:
                    pass

                await self._log(f"  Navigated: {target_url or self._base_url}")
                return {"step": step.order, "action": action, "status": "passed"}

            elif "点击" in action:
                return await self._retryable_action(ctx, step, "click")

            elif "输入" in action:
                return await self._retryable_action(ctx, step, "fill")

            elif any(kw in action for kw in ["观察", "查看", "检查", "验证"]):
                # 断言型步骤：截图 + AI 判断
                screenshot_path = f"test_artifacts/{ctx.case.suite_id}/screenshots/case_{ctx.case.id}_step{step.order}.png"
                os.makedirs(os.path.dirname(screenshot_path), exist_ok=True)
                await self.browser.take_screenshot(screenshot_path)
                await self._log(f"  Screenshot: {screenshot_path}")

                if self.ai:
                    page = await self.browser.get_page_summary()
                    judgment = await self.ai.analyze(
                        system_prompt="You are a test engineer. Check if the page state matches expectations. Return JSON: {judgment: passed|bug|unclear, confidence, reasoning}",
                        user_prompt=f"Expected: {ctx.case.expected}\nCurrent page: {json.dumps(page, ensure_ascii=False)}"
                    )
                    ctx.ai_call_count += 1
                    await self._log(f"  [AI] Assertion: {judgment.judgment} (confidence: {judgment.confidence:.0%})")
                    if judgment.judgment == "bug":
                        return {"step": step.order, "action": action, "status": "failed",
                                "ai_judgment": "bug", "ai_confidence": judgment.confidence, "screenshot": screenshot_path}
                return {"step": step.order, "action": action, "status": "passed"}

            elif "选择" in action:
                return await self._retryable_action(ctx, step, "click")

            elif "删除" in action:
                return await self._retryable_action(ctx, step, "click")

            elif "确" in action:
                # 确认按钮
                return await self._retryable_action(ctx, step, "click")

            elif "保存" in action or "提交" in action:
                return await self._retryable_action(ctx, step, "click")

            else:
                await self._log(f"  Unrecognized action: {action[:60]}")
                return {"step": step.order, "action": action, "status": "error", "reason": f"Unrecognized action: {action[:80]}"}

        except Exception as e:
            await self._log(f"  Step error: {e}")
            return {"step": step.order, "action": action, "status": "error", "reason": str(e)[:200]}

    async def _retryable_action(self, ctx: ExecutionContext, step, action_type: str) -> dict:
        action = step.action
        selector = self._infer_selector(action, step)

        for attempt in range(ctx.max_retries + 1):
            try:
                if action_type == "click":
                    if selector:
                        await self.browser.page.click(selector, timeout=5000)
                    else:
                        # 尝试按文本匹配
                        text_hint = self._extract_text_hint(action)
                        await self.browser.page.click(f"text={text_hint}", timeout=5000)
                    await self.browser.wait_for_page_ready(strategy="domcontentloaded")
                    await self._log(f"  Clicked: {selector or text_hint}")
                    return {"step": step.order, "action": action, "status": "passed"}

                elif action_type == "fill":
                    value = self._extract_fill_value(action)
                    if selector:
                        await self.browser.page.fill(selector, value, timeout=5000)
                    else:
                        text_hint = self._extract_text_hint(action)
                        await self.browser.page.fill(f"input[name='{text_hint}']", value, timeout=5000)
                    await self._log(f"  Filled: {selector or text_hint} = {value}")
                    return {"step": step.order, "action": action, "status": "passed"}

            except Exception as e:
                err_str = str(e)
                await self._log(f"  Attempt {attempt+1} failed: {err_str[:100]}")

                if attempt == ctx.max_retries:
                    await self._log(f"  Retries exhausted")
                    return {"step": step.order, "action": action, "status": "failed",
                            "reason": "selector_exhausted"}

                # 尝试自愈知识库
                if selector:
                    healing = self.healing.find(selector, self.browser.page.url)
                    if healing:
                        selector = healing["healed_selector"]
                        await self._log(f"  [Healing] using '{selector}' (success={healing['success_count']})")
                        self.healing.increment_success(healing["original_selector"], healing["page_url_pattern"])
                        continue

                # 同类型去重缓存
                if selector and self.guard.get_cached(selector):
                    selector = self.guard.get_cached(selector)
                    await self._log(f"  [Cache] reusing healed selector: '{selector}'")
                    continue

                # AI 介入（通过成本控制）
                if not self.guard.can_call(ctx.case.id):
                    await self._log(f"  [Guard] AI call blocked (case limit={ctx.ai_call_count}, melted={self.guard.is_melted})")
                    return {"step": step.order, "action": action, "status": "failed", "reason": "ai_blocked"}

                ai_to_use = self.ai
                await self._log(f"  [AI] Analyzing failure (call #{self.guard.total_calls+1})...")
                try:
                    page_url = self.browser.page.url
                    page_summary = await self.browser.get_page_summary()
                    prompt = f"Action: {action}\nSelector: {selector}\nPage: {json.dumps(page_summary, ensure_ascii=False)}"
                    judgment = await ai_to_use.analyze(
                        system_prompt="You are a test engineer. Action failed. Return JSON: {judgment: selector_changed|element_missing|other, confidence, action: {new_selector}, reasoning}",
                        user_prompt=prompt
                    )
                except Exception:
                    # 降级到备用 AI
                    if self.backup_ai:
                        await self._log(f"  [Fallback] Primary AI failed, trying backup...")
                        try:
                            judgment = await self.backup_ai.analyze(
                                system_prompt="You are a test engineer. Return JSON: {judgment, confidence, action: {new_selector}, reasoning}",
                                user_prompt=prompt
                            )
                        except Exception:
                            await self._log(f"  [Fallback] Backup AI also failed")
                            return {"step": step.order, "action": action, "status": "error", "reason": "ai_unavailable"}
                    else:
                        await self._log(f"  [Error] AI unavailable, no backup configured")
                        return {"step": step.order, "action": action, "status": "error", "reason": "ai_unavailable"}

                ctx.ai_call_count += 1
                self.guard.record_call(ctx.case.id)
                await self._log(f"  [AI] {judgment.judgment} (confidence: {judgment.confidence:.0%})")

                # 置信度门禁
                if not self.guard.check_confidence(judgment.confidence):
                    await self._log(f"  [Guard] Low confidence ({judgment.confidence:.0%} < {self.guard.confidence_threshold:.0%}), need human")
                    return {"step": step.order, "action": action, "status": "blocked",
                            "ai_judgment": judgment.judgment, "ai_confidence": judgment.confidence,
                            "reason": "low_confidence"}

                if judgment.judgment == "selector_changed" and judgment.action.get("new_selector"):
                    new_sel = judgment.action["new_selector"]
                    self.healing.add(selector, new_sel, self._url_pattern(page_url))
                    self.guard.cache_selector(selector, new_sel)
                    selector = new_sel
                    await self._log(f"  [AI] Fixed: '{selector}' -> '{new_sel}'")
                    continue

                if judgment.judgment == "element_missing":
                    screenshot_path = f"test_artifacts/{ctx.case.suite_id}/screenshots/fail_{ctx.case.id}_step{step.order}.png"
                    os.makedirs(os.path.dirname(screenshot_path), exist_ok=True)
                    await self.browser.take_screenshot(screenshot_path)
                    await self._log(f"  [BUG] Element missing. Screenshot: {screenshot_path}")
                    return {"step": step.order, "action": action, "status": "failed",
                            "ai_judgment": "bug", "ai_confidence": judgment.confidence,
                            "screenshot": screenshot_path, "ai_reasoning": judgment.reasoning}

    def _infer_selector(self, action: str, step) -> str:
        """从步骤描述推断选择器"""
        if step.enrichment and step.enrichment.get("selector_hint"):
            return step.enrichment["selector_hint"]

        # 从动作描述中提取可能的文本/元素名
        text = self._extract_text_hint(action)
        if text:
            return f"text={text}"

        # 按钮关键词匹配
        btn_map = {
            "新增": "button:has-text('新增'), button:has-text('新建')",
            "保存": "button:has-text('保存')",
            "删除": "button:has-text('删除')",
            "编辑": "button:has-text('编辑')",
            "确认": "button:has-text('确认'), button:has-text('确定')",
            "取消": "button:has-text('取消')",
            "提交": "button:has-text('提交')",
            "登录": "button:has-text('登录'), button:has-text('Login')",
        }
        for key, sel in btn_map.items():
            if key in action:
                return sel

        return None

    def _extract_text_hint(self, action: str) -> str:
        """从动作中提取可能的目标文本"""
        # "点击新增按钮" -> "新增"
        # "点击保存" -> "保存"
        # "输入标题" -> "标题"
        patterns = [
            r'点击(.+?)(?:按钮|链接|标签|选项|$)',
            r'选择(.+?)(?:按钮|选项|项|$)',
            r'输入(.+?)(?:内容|信息|值|$)',
        ]
        for pattern in patterns:
            match = re.search(pattern, action)
            if match:
                return match.group(1).strip()
        return action.strip()

    def _extract_fill_value(self, action: str) -> str:
        """从动作推断填充值"""
        from backend.engine.generator.data_factory import TestDataFactory
        data = TestDataFactory.generate_from_keyword(action)
        if data and isinstance(data, str):
            return data
        return "test_data"

    def _url_pattern(self, url: str) -> str:
        return re.sub(r'/[^/]+$', '/*', url)

    def classify_results(self, case_results: list[dict]) -> dict:
        bugs, script_issues, env_issues, case_issues = [], [], [], []
        for r in case_results:
            for step in r.get("steps", []):
                judgment = step.get("ai_judgment", "")
                if judgment == "bug":
                    bugs.append(step)
                elif judgment in ("selector_changed", "script_error", "selector_exhausted"):
                    script_issues.append(step)
                elif judgment == "environment_error":
                    env_issues.append(step)
        return {"bugs": bugs, "script_issues": script_issues, "environment_issues": env_issues, "case_issues": case_issues}

    def analyze_selector_failure(self, original_selector: str, page_summary: dict, case_context: str) -> dict:
        return {"selector": original_selector, "confidence": 0.5, "action": "unknown"}
