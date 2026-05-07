"""ExplorerAgent — 多轮 AI 交互 + BrowserTools 驱动的用例探索

流程：
1. 对每个测试步骤：
   a. 采集 Semantic Snapshot
   b. 调用 AI（带 tools）→ AI 返回 tool_calls
   c. 执行 tool_calls
   d. 记录结果到 Action IR
   e. 失败则重试（最多 3 次）
"""

import json
import re
import logging
from dataclasses import dataclass, field

from backend.engine.browser.browser_tool import BrowserTools, ToolResult
from backend.engine.browser.semantic_snapshot import SemanticSnapshot
from backend.engine.agent.prompts import (
    EXPLORER_SYSTEM_PROMPT,
    build_explorer_prompt,
    format_snapshot_for_prompt,
    format_history_for_prompt,
)
from backend.engine.agent.decision_schema import BROWSER_TOOLS, validate_decision

logger = logging.getLogger(__name__)


@dataclass
class StepResult:
    step_num: int
    natural_step: str
    actions: list[dict] = field(default_factory=list)  # 执行的 tool calls
    success: bool = False
    message: str = ""
    snapshot_before: dict = field(default_factory=dict)
    url_before: str = ""
    url_after: str = ""
    screenshot_before: str = ""
    screenshot_after: str = ""


@dataclass
class CaseExplorationResult:
    case_id: str
    case_title: str
    status: str = "pending"    # passed / failed / blocked / error
    steps: list[StepResult] = field(default_factory=list)
    total_ai_calls: int = 0
    total_retries: int = 0


class ExplorerAgent:
    def __init__(self, browser_tools: BrowserTools, ai_provider, log_callback=None, credentials: dict | None = None):
        self.tools = browser_tools
        self.ai = ai_provider
        self._log = log_callback or (lambda level, msg: None)
        self.credentials = credentials or {}

    def _try_rule_based_action(self, step_action: str, snapshot_data: dict) -> dict | None:
        """尝试用规则匹配步骤，返回第一个匹配的 tool_call dict 或 None"""
        results = self._try_rule_based_actions(step_action, snapshot_data)
        return results[0] if results else None

    def _try_rule_based_actions(self, step_action: str, snapshot_data: dict) -> list[dict]:
        """尝试用规则匹配步骤，返回所有匹配的 tool_call 列表

        支持复合步骤如 "输入用户名密码点击登录" → [fill用户名, fill密码, click登录]
        """
        sections = snapshot_data.get("sections", [])
        all_elements = []
        for section in sections:
            all_elements.extend(section.get("elements", []))

        results = []

        # 匹配所有 fill: "在XX输入框输入YY" 或 "输入(正确的)(用户名/密码)(YY)"
        # 模式1: "在XX输入框/框输入/填写 YY"
        for m in re.finditer(r'在(.{2,20}?)(?:输入框|框|输入栏|文本框)(?:中)?(?:输入|填写|填入)\s*(\S+)', step_action):
            keyword = m.group(1).strip()
            value = m.group(2).strip()
            tc = self._match_fill_element(all_elements, keyword, value)
            if tc:
                results.append(tc)

        # 模式2: "输入正确的用户名密码" → 找到用户名和密码输入框
        if not results:
            # 检查是否包含 "用户名" + "密码" 关键词
            has_username = "用户名" in step_action
            has_password = "密码" in step_action
            if has_username and has_password:
                # 从快照中找用户名和密码输入框
                username_el = None
                password_el = None
                for el in all_elements:
                    if el.get("role") in ("textbox", "input", "searchbox") or el.get("tag") in ("input", "textarea"):
                        name = (el.get("name", "") or "").lower()
                        placeholder = (el.get("placeholder", "") or "").lower()
                        if "用户名" in name or "用户名" in placeholder or "账号" in name or "账号" in placeholder:
                            username_el = el
                        elif "密码" in name or "密码" in placeholder:
                            password_el = el

                if username_el:
                    ref = username_el.get("ref", "")
                    locator = username_el.get("locator_candidates", [{}])[0] if username_el.get("locator_candidates") else {}
                    username_value = (self.credentials.get("username") or "admin").strip()
                    self._log("info", f"[规则匹配] fill用户名: ref={ref}")
                    results.append({
                        "function": {
                            "name": "fill",
                            "arguments": json.dumps({"ref": ref, "value": username_value, "locator": locator}, ensure_ascii=False)
                        }
                    })

                if password_el:
                    ref = password_el.get("ref", "")
                    locator = password_el.get("locator_candidates", [{}])[0] if password_el.get("locator_candidates") else {}
                    password_value = (self.credentials.get("password") or "123456").strip()
                    self._log("info", f"[规则匹配] fill密码: ref={ref}")
                    results.append({
                        "function": {
                            "name": "fill",
                            "arguments": json.dumps({"ref": ref, "value": password_value, "locator": locator}, ensure_ascii=False)
                        }
                    })

        # 匹配 navigate: "打开XX页面/系统" — 跳过（浏览器已在目标页面）
        if re.search(r'(?:打开|进入|导航到?|跳转到?).{2,30}', step_action) and not results:
            self._log("info", f"[规则匹配] navigate: 跳过（已在目标页面）")
            # 返回空列表，让 AI 处理导航类步骤

        # 匹配所有 click: "点击XX按钮/链接/菜单"
        for m in re.finditer(r'点击(.{2,30}?)(?:按钮|链接|菜单|图标|选项)?(?=[，,。；;]|$)', step_action):
            keyword = m.group(1).strip()
            tc = self._match_click_element(all_elements, keyword)
            if tc:
                results.append(tc)

        # 匹配 select: "选择XX"
        for m in re.finditer(r'选择(.{2,20}?)(?=[，,。；;]|$)', step_action):
            keyword = m.group(1).strip()
            for el in all_elements:
                if el.get("role") in ("combobox", "listbox", "select"):
                    name = el.get("name", "") or ""
                    text = el.get("text", "") or ""
                    if keyword in name or keyword in text:
                        ref = el.get("ref", "")
                        locator = el.get("locator_candidates", [{}])[0] if el.get("locator_candidates") else {}
                        self._log("info", f"[规则匹配] select_option: ref={ref}, value={keyword}")
                        results.append({
                            "function": {
                                "name": "select_option",
                                "arguments": json.dumps({"ref": ref, "value": keyword, "locator": locator}, ensure_ascii=False)
                            }
                        })
                        break

        return results

    def _match_fill_element(self, all_elements: list, keyword: str, value: str) -> dict | None:
        """在快照元素中查找匹配的输入框，返回 tool_call"""
        for el in all_elements:
            if el.get("role") in ("textbox", "input", "searchbox") or el.get("tag") in ("input", "textarea"):
                name = el.get("name", "") or ""
                placeholder = el.get("placeholder", "") or ""
                text = el.get("text", "") or ""
                if keyword in name or keyword in placeholder or keyword in text:
                    ref = el.get("ref", "")
                    locator = el.get("locator_candidates", [{}])[0] if el.get("locator_candidates") else {}
                    self._log("info", f"[规则匹配] fill: ref={ref}, value={value}, keyword={keyword}")
                    return {
                        "function": {
                            "name": "fill",
                            "arguments": json.dumps({"ref": ref, "value": value, "locator": locator}, ensure_ascii=False)
                        }
                    }
        return None

    def _match_click_element(self, all_elements: list, keyword: str) -> dict | None:
        """在快照元素中查找匹配的可点击元素，返回 tool_call"""
        for el in all_elements:
            name = el.get("name", "") or ""
            text = el.get("text", "") or ""
            if keyword in name or keyword in text:
                ref = el.get("ref", "")
                locator = el.get("locator_candidates", [{}])[0] if el.get("locator_candidates") else {}
                self._log("info", f"[规则匹配] click: ref={ref}, keyword={keyword}")
                return {
                    "function": {
                        "name": "click",
                        "arguments": json.dumps({"ref": ref, "locator": locator}, ensure_ascii=False)
                    }
                }
        return None

    async def explore_case(self, case, run_id: str) -> CaseExplorationResult:
        """探索一个测试用例的所有步骤"""
        result = CaseExplorationResult(
            case_id=case.id,
            case_title=case.title,
        )

        self._log("info", f"开始探索用例: {case.title} (共 {len(case.steps)} 步)")

        for step in case.steps:
            step_result = await self._execute_step(
                case=case,
                step_num=step.order,
                step_action=step.action,
                steps_history=result.steps,
            )
            result.steps.append(step_result)
            result.total_ai_calls += step_result.actions.__len__()

            if not step_result.success:
                # 单步失败不中断，继续下一步（记录状态）
                self._log("warning", f"步骤 {step.order} 失败: {step_result.message}")

        # 判断用例整体状态
        failed_steps = [s for s in result.steps if not s.success]
        if not failed_steps:
            result.status = "passed"
        elif len(failed_steps) == len(result.steps):
            result.status = "failed"
        else:
            result.status = "partial"  # 部分通过

        self._log("info", f"用例探索完成: {case.title}, 状态={result.status}")
        return result

    async def _execute_step(self, case, step_num: int, step_action: str, steps_history: list) -> StepResult:
        """执行单个步骤，带重试"""
        step_result = StepResult(step_num=step_num, natural_step=step_action)
        max_retries = 3

        # 跳过纯导航步骤（"打开XX页面/系统"，没有其他操作）
        if re.search(r'^(?:打开|进入|导航到?|跳转到?).{2,30}(?:页面|系统|网址)?$', step_action.strip()):
            if not re.search(r'(?:点击|输入|选择|填写|上传|删除|勾选)', step_action):
                self._log("info", f"步骤 {step_num} 纯导航步骤，跳过: {step_action}")
                step_result.success = True
                step_result.message = "导航步骤，无需操作"
                return step_result

        for attempt in range(max_retries):
            try:
                # 1. 采集快照
                snapshot_result = await self.tools.snapshot()
                if not snapshot_result.success:
                    step_result.message = f"快照失败: {snapshot_result.message}"
                    continue

                snapshot_data = snapshot_result.data
                step_result.snapshot_before = snapshot_data
                step_result.url_before = snapshot_data.get("url", "")

                # 2. 先尝试规则匹配（支持复合步骤返回多个动作）
                rule_tcs = self._try_rule_based_actions(step_action, snapshot_data)
                if rule_tcs:
                    tool_calls = rule_tcs
                else:
                    # 3. 规则不匹配，调用 AI
                    snapshot_text = format_snapshot_for_prompt(
                        self.tools.get_last_snapshot()
                    ) if self.tools.get_last_snapshot() else json.dumps(snapshot_data, ensure_ascii=False, indent=2)

                    history_text = format_history_for_prompt(
                        [{"action": s.natural_step, "success": s.success, "message": s.message} for s in steps_history]
                    )

                    user_prompt = build_explorer_prompt(
                        case=case,
                        step_num=step_num,
                        step_action=step_action,
                        snapshot_text=snapshot_text,
                        history=history_text,
                    )

                    self._log("info", f"步骤 {step_num} 第 {attempt+1} 次尝试，调用 AI...")
                    ai_response = await self._call_ai_with_tools(user_prompt)
                    tool_calls = ai_response.get("tool_calls", [])

                step_result.actions.extend(tool_calls)

                # 4. 执行 tool calls
                if not tool_calls:
                    content = ""
                    step_result.message = "未找到匹配的操作"
                    continue

                all_success = True
                for idx, tc in enumerate(tool_calls):
                    tc_result = await self._execute_tool_call(tc)
                    action_idx = len(step_result.actions) - len(tool_calls) + idx
                    if 0 <= action_idx < len(step_result.actions):
                        step_result.actions[action_idx]["result"] = tc_result.to_dict()

                    if not tc_result.success:
                        all_success = False
                        step_result.message = tc_result.message
                        break
                    else:
                        step_result.message = tc_result.message
                        # 多动作场景：fill 后重新采集快照，确保后续动作的元素有效
                        func_name = tc.get("function", {}).get("name", "")
                        if func_name == "fill" and idx < len(tool_calls) - 1:
                            await self.tools.snapshot()

                if all_success:
                    # 5. 基于页面状态做"最小正确性校验"（避免只执行了动作就判定通过）
                    # 等待页面稳定后再检查（SPA 路由跳转需要时间）
                    try:
                        await self.tools.page.wait_for_load_state("networkidle", timeout=5000)
                    except Exception:
                        pass
                    await self.tools.page.wait_for_timeout(1000)

                    # 登录相关：点击登录后仍停留在登录页 → 认为失败并触发重试
                    try:
                        post_snap = await self.tools.snapshot()
                        if post_snap.success:
                            step_result.url_after = post_snap.data.get("url", self.tools.page.url)
                            page_type = (post_snap.data.get("page_type") or "").lower()
                        else:
                            step_result.url_after = self.tools.page.url
                            page_type = ""
                    except Exception:
                        step_result.url_after = self.tools.page.url
                        page_type = ""

                    is_login_step = ("登录" in step_action) or ("login" in step_action.lower())
                    if is_login_step and page_type == "login":
                        all_success = False
                        step_result.success = False
                        step_result.message = "仍停留在登录页（可能未填写密码/登录失败）"
                        continue

                    # 复合登录输入步骤：要求同时填了用户名和密码
                    if ("用户名" in step_action and "密码" in step_action):
                        fills = [tc for tc in tool_calls if tc.get("function", {}).get("name") == "fill"]
                        if len(fills) < 2:
                            step_result.success = False
                            step_result.message = "步骤包含用户名+密码，但未完成两次输入"
                            continue

                    step_result.success = True
                    break  # 成功，跳出重试循环

            except Exception as e:
                step_result.message = f"执行异常: {type(e).__name__}: {e}"
                logger.exception(f"步骤 {step_num} 执行异常")
                continue

        return step_result

    async def _call_ai_with_tools(self, user_prompt: str) -> dict:
        """调用 AI，传入 tools 定义，返回 tool_calls"""
        messages = [
            {"role": "system", "content": EXPLORER_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        try:
            result = await self.ai.chat_with_tools(messages=messages, tools=BROWSER_TOOLS)
            return result
        except Exception as e:
            logger.error(f"AI 调用失败: {e}")
            return {"tool_calls": [], "content": f"AI 调用失败: {e}"}

    async def _execute_tool_call(self, tool_call: dict) -> ToolResult:
        """执行单个 tool call"""
        func_name = tool_call.get("function", {}).get("name", "")
        args_str = tool_call.get("function", {}).get("arguments", "{}")

        try:
            args = json.loads(args_str) if isinstance(args_str, str) else args_str
        except json.JSONDecodeError:
            return ToolResult(success=False, tool=func_name, message=f"参数解析失败: {args_str}")

        self._log("info", f"执行工具: {func_name}({json.dumps(args, ensure_ascii=False)[:100]})")

        dispatch = {
            "snapshot": lambda: self.tools.snapshot(),
            "click": lambda: self.tools.click(ref=args.get("ref", ""), locator=args.get("locator")),
            "fill": lambda: self.tools.fill(ref=args.get("ref", ""), value=args.get("value", ""), locator=args.get("locator")),
            "hover": lambda: self.tools.hover(ref=args.get("ref", ""), locator=args.get("locator")),
            "select_option": lambda: self.tools.select_option(ref=args.get("ref", ""), value=args.get("value", ""), locator=args.get("locator")),
            "navigate": lambda: self.tools.navigate(url=args.get("url", "")),
            "press_key": lambda: self.tools.press_key(key=args.get("key", "")),
            "wait": lambda: self.tools.wait(ms=args.get("ms", 1000)),
            "screenshot": lambda: self.tools.screenshot(path=args.get("path", "")),
            "expect_visible": lambda: self.tools.expect_visible(ref=args.get("ref", ""), locator=args.get("locator")),
            "expect_text": lambda: self.tools.expect_text(text=args.get("text", "")),
            "expect_url": lambda: self.tools.expect_url(url_pattern=args.get("url_pattern", "")),
        }

        handler = dispatch.get(func_name)
        if handler is None:
            return ToolResult(success=False, tool=func_name, message=f"未知工具: {func_name}")

        result = await handler()
        # fill 后等待 Vue/React 重渲染完成
        if func_name == "fill" and result.success:
            try:
                await self.tools.page.wait_for_load_state("networkidle", timeout=3000)
            except Exception:
                pass
        return result
