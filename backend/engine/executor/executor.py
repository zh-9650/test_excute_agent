import subprocess
import tempfile
import os
import json
import re
from dataclasses import dataclass, field
from backend.models.case import TestCase, CaseStatus
from backend.engine.executor.healing import HealingStore


@dataclass
class ExecutionContext:
    case: TestCase
    script: str
    session_id: str
    ai_call_count: int = 0
    retry_count: int = 0
    max_retries: int = 3
    result: dict = field(default_factory=dict)


class SmartExecutor:
    def __init__(self, ai=None, browser_controller=None, log_callback=None):
        self.ai = ai
        self.browser = browser_controller
        self.healing = HealingStore()
        self._log = log_callback or (lambda msg: None)

    async def execute_case(self, ctx: ExecutionContext) -> dict:
        script_path = self._write_script(ctx)
        try:
            proc = await self._run_script(script_path)
            if proc.returncode == 0:
                ctx.case.transition_to(CaseStatus.PASSED)
                return {"case_id": ctx.case.id, "status": "passed", "output": proc.stdout}
            else:
                return await self._handle_failure(ctx, proc)
        except Exception as e:
            return {"case_id": ctx.case.id, "status": "error", "reason": str(e)}
        finally:
            if os.path.exists(script_path):
                os.unlink(script_path)

    def _write_script(self, ctx: ExecutionContext) -> str:
        path = os.path.join(tempfile.gettempdir(), f"test_{ctx.case.id}.py")
        with open(path, "w", encoding="utf-8") as f:
            f.write(ctx.script)
        return path

    async def _run_script(self, script_path: str):
        return subprocess.run(["python", script_path], capture_output=True, text=True, timeout=300)

    async def _handle_failure(self, ctx: ExecutionContext, proc) -> dict:
        stderr = proc.stderr
        await self._log(f"脚本执行失败 [{ctx.case.title}]")
        await self._log(f"  错误输出: {stderr[:200]}")

        if "TimeoutError" in stderr and "selector" in stderr.lower():
            return await self._handle_selector_timeout(ctx, stderr)
        if "AssertionError" in stderr or "expect(" in stderr:
            return await self._handle_assertion_failure(ctx, stderr)
        return await self._handle_script_error(ctx, stderr)

    async def _handle_selector_timeout(self, ctx: ExecutionContext, stderr: str) -> dict:
        selector = self._extract_selector(stderr)
        await self._log(f"  🔍 选择器定位失败: '{selector}'")
        healing = self.healing.find(selector, self.browser.page.url if self.browser else "")

        if healing:
            await self._log(f"  💾 命中自愈知识库 → 使用修复选择器: '{healing['healed_selector']}' (成功{healing['success_count']}次)")
            ctx.script = ctx.script.replace(selector, healing["healed_selector"])
            self.healing.increment_success(selector, healing["page_url_pattern"])
            ctx.retry_count += 1
            if ctx.retry_count < ctx.max_retries:
                await self._log(f"  🔄 重试 ({ctx.retry_count}/{ctx.max_retries})...")
                return await self.execute_case(ctx)

        if self.ai and ctx.ai_call_count < 5:
            page_summary = await self.browser.get_page_summary() if self.browser else {}
            await self._log(f"  🤖 调用 AI 分析选择器问题...")
            judgment = await self.ai.analyze(
                system_prompt="你是一个测试工程师。分析选择器定位失败的原因。返回 JSON: {judgment, confidence, action: {type, new_selector}, reasoning}",
                user_prompt=f"选择器 {selector} 定位失败。页面：{json.dumps(page_summary, ensure_ascii=False)}。用例：{ctx.case.title}"
            )
            ctx.ai_call_count += 1
            await self._log(f"  📝 AI 判断: {judgment.judgment} (置信度: {judgment.confidence:.0%})")
            await self._log(f"  💬 AI 推理: {judgment.reasoning[:200]}")

            if judgment.judgment == "selector_changed" and judgment.action.get("new_selector"):
                new_sel = judgment.action["new_selector"]
                await self._log(f"  ✏️ AI 修复: '{selector}' → '{new_sel}'")
                ctx.script = ctx.script.replace(selector, new_sel)
                self.healing.add(selector, new_sel, "*/" + ctx.case.module.lstrip("/") + "/*",
                                 strategy=judgment.action.get("strategy", "text_match"))
                ctx.retry_count += 1
                await self._log(f"  💾 已存入自愈知识库（下次自动复用）")
                if ctx.retry_count < ctx.max_retries:
                    await self._log(f"  🔄 重试 ({ctx.retry_count}/{ctx.max_retries})...")
                    return await self.execute_case(ctx)

            if judgment.judgment == "element_missing":
                await self._log(f"  🐛 判定为 Bug: 元素不存在")
                ctx.case.transition_to(CaseStatus.FAILED)
                return {"case_id": ctx.case.id, "status": "failed",
                        "reason": "element_missing", "ai_judgment": judgment.judgment,
                        "ai_confidence": judgment.confidence}

        await self._log(f"  ❌ 选择器修复耗尽（重试 {ctx.retry_count} 次）")
        ctx.case.transition_to(CaseStatus.FAILED)
        return {"case_id": ctx.case.id, "status": "failed", "reason": "selector_exhausted"}

    async def _handle_assertion_failure(self, ctx: ExecutionContext, stderr: str) -> dict:
        await self._log(f"  ❌ 断言失败")
        await self._log(f"  预期: {ctx.case.expected[:200]}")
        await self._log(f"  实际: {stderr[:200]}")

        if self.ai and ctx.ai_call_count < 5:
            await self._log(f"  🤖 调用 AI 分析断言结果...")
            judgment = await self.ai.analyze(
                system_prompt="你是一个测试工程师。分析断言失败的原因。返回 JSON: {judgment: bug|expected_changed|assertion_inaccurate, confidence, reasoning}",
                user_prompt=f"预期：{ctx.case.expected}\n实际错误：{stderr}\n步骤：{[s.action for s in ctx.case.steps]}"
            )
            ctx.ai_call_count += 1
            await self._log(f"  📝 AI 判断: {judgment.judgment} (置信度: {judgment.confidence:.0%})")
            await self._log(f"  💬 AI 推理: {judgment.reasoning[:200]}")

            if judgment.judgment == "bug":
                await self._log(f"  🐛 确认为 Bug，已记录")
            elif judgment.judgment == "expected_changed":
                await self._log(f"  📋 预期已变更，建议更新用例")
            elif judgment.judgment == "assertion_inaccurate":
                await self._log(f"  ⚠️ 断言不准确，需要修正断言逻辑")

            ctx.case.transition_to(CaseStatus.FAILED)
            return {"case_id": ctx.case.id, "status": "failed",
                    "ai_judgment": judgment.judgment, "ai_confidence": judgment.confidence}

        ctx.case.transition_to(CaseStatus.FAILED)
        return {"case_id": ctx.case.id, "status": "failed", "reason": "assertion_failed"}

    async def _handle_script_error(self, ctx: ExecutionContext, stderr: str) -> dict:
        await self._log(f"  ⚠️ 脚本异常: {stderr[:200]}")

        if self.ai and ctx.ai_call_count < 3:
            await self._log(f"  🤖 调用 AI 分析异常类型...")
            judgment = await self.ai.analyze(
                system_prompt="分类脚本异常：script_error | env_error | system_error。返回 JSON: {judgment, confidence, reasoning}",
                user_prompt=f"错误：{stderr}"
            )
            ctx.ai_call_count += 1
            await self._log(f"  📝 AI 分类: {judgment.judgment} (置信度: {judgment.confidence:.0%})")

            if judgment.judgment == "env_error":
                await self._log(f"  🌐 环境问题，跳过此用例")
                return {"case_id": ctx.case.id, "status": "blocked", "reason": "environment_error"}
            if judgment.judgment == "script_error" and ctx.retry_count < 1:
                ctx.retry_count += 1
                await self._log(f"  🔧 尝试修复脚本重试...")
                return await self.execute_case(ctx)

        ctx.case.transition_to(CaseStatus.ERROR)
        return {"case_id": ctx.case.id, "status": "error", "reason": stderr[:200]}

    def _extract_selector(self, stderr: str) -> str:
        match = re.search(r"['\"]([^'\"]+)['\"]", stderr)
        return match.group(1) if match else "unknown"

    def classify_results(self, case_results: list[dict]) -> dict:
        bugs, script_issues, env_issues, case_issues = [], [], [], []
        for r in case_results:
            judgment = r.get("ai_judgment", "")
            if judgment == "bug":
                bugs.append(r)
            elif judgment in ("selector_changed", "script_error", "selector_exhausted"):
                script_issues.append(r)
            elif judgment == "environment_error":
                env_issues.append(r)
            elif judgment == "expected_changed":
                case_issues.append(r)
            elif r.get("status") == "blocked":
                env_issues.append(r)
            elif r.get("status") in ("error", "failed") and not judgment:
                script_issues.append(r)
        return {"bugs": bugs, "script_issues": script_issues, "environment_issues": env_issues, "case_issues": case_issues}

    def analyze_selector_failure(self, original_selector: str, page_summary: dict, case_context: str) -> dict:
        return {"selector": original_selector, "confidence": 0.5, "action": "unknown"}
