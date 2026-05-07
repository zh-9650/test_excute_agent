"""AI 驱动探索引擎 — AI 在真实 UI 上逐步预执行测试用例"""
import json
import re
import asyncio
from dataclasses import dataclass, field
from backend.engine.explorer.browser import BrowserController, ElementInfo
from backend.engine.explorer.prompts import (
    EXPLORATION_SYSTEM_PROMPT, EXPLORATION_USER_TEMPLATE,
    ASSERTION_SYSTEM_PROMPT, ASSERTION_USER_TEMPLATE,
    OBSERVATION_SYSTEM_PROMPT, OBSERVATION_USER_TEMPLATE,
    PAGE_MAP_SYSTEM_PROMPT, PAGE_OBSERVATION_TEMPLATE,
    ENHANCED_EXPLORATION_SYSTEM_PROMPT, ENHANCED_EXPLORATION_TEMPLATE,
    FUNCTION_IDENTIFICATION_SYSTEM_PROMPT, FUNCTION_IDENTIFICATION_TEMPLATE,
    load_skill, build_system_prompt,
)


async def _default_log(level: str, msg: str):
    pass


@dataclass
class StepRecord:
    """单步探索记录 — 增强版"""
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
    # 页面状态快照
    url_before: str = ""
    url_after: str = ""
    page_title_before: str = ""
    page_title_after: str = ""
    # 元素上下文
    target_element_text: str = ""   # 被操作元素的文本
    target_element_role: str = ""   # 元素的 ARIA role
    parent_context: str = ""        # 父元素上下文摘要
    # DOM 变化
    dom_snapshot_before: str = ""
    dom_snapshot_after: str = ""
    dom_changes: str = ""           # AI 总结的 DOM 变化
    # 脚本生成辅助
    semantic_action: str = ""       # "navigate_to_doc_center", "fill_search_keyword"
    function_name_hint: str = ""    # "search_docs", "open_first_doc"


@dataclass
class PageSection:
    """页面的一个功能区域"""
    name: str                       # "顶部导航栏", "搜索区域", "文档列表"
    description: str = ""
    section_type: str = ""          # navigation | search | content | form | toolbar | sidebar
    element_count: int = 0


@dataclass
class PageMap:
    """AI 观察页面后的结构化地图"""
    page_type: str = ""             # login | list | detail | form | dashboard | editor
    page_url: str = ""
    page_title: str = ""
    sections: list = field(default_factory=list)        # list[PageSection]
    key_elements: dict = field(default_factory=dict)    # "search_input" -> selector
    navigation_hints: list = field(default_factory=list)
    observation_summary: str = ""


@dataclass
class CaseExplorationResult:
    """单用例探索结果"""
    case_id: str
    case_title: str
    status: str = "pending"
    steps: list = field(default_factory=list)
    total_retries: int = 0


@dataclass
class ExplorationRecording:
    """单用例的完整探索录制 — 用于 AI 脚本生成"""
    case_id: str
    case_title: str
    case_steps_text: list = field(default_factory=list)
    case_expected: str = ""
    case_module: str = ""
    status: str = "pending"
    steps: list = field(default_factory=list)           # list[StepRecord]
    page_maps: list = field(default_factory=list)       # list[PageMap]
    total_retries: int = 0
    identified_functions: list = field(default_factory=list)  # AI识别的函数划分


class AIExplorer:
    def __init__(self, browser: BrowserController, ai_provider, log_callback=None, max_step_retries: int = 5, skill_path: str = ""):
        self.browser = browser
        self.ai = ai_provider
        self.log = log_callback or _default_log
        self._max_step_retries = max_step_retries
        self._skill_content = load_skill(skill_path)

    async def explore_case(self, case, run_id: str) -> CaseExplorationResult:
        """探索单个用例 — AI 先观察理解页面，再逐步操作"""
        result = CaseExplorationResult(case_id=case.id, case_title=case.title, status="exploring")
        if self._skill_content:
            await self.log("info", f"  Skill loaded: {len(self._skill_content)} chars")
        await self.log("info", f"  Exploring case: {case.title} ({len(case.steps)} steps)")

        # 检查页面状态：如果当前页面可能不对，先回到首页
        await self._ensure_on_start_page(case)

        # 阶段1：观察页面，理解用例上下文
        observation = await self._observe_page(case, run_id)
        await self.log("info", f"  AI observation: {observation[:150]}...")

        # 阶段2：逐步执行，带着观察上下文
        for step in case.steps:
            record = StepRecord(step_num=step.order, action_desc=step.action)
            result.steps.append(record)

            success = await self._execute_step_with_retry(case, step, record, run_id, result, observation)
            if not success:
                result.status = "explore_failed"
                await self.log("info", f"  Case exploration failed at step {step.order}")
                return result

        result.status = "explored"
        await self.log("info", f"  Case exploration succeeded: {case.title}")
        return result

    async def explore_case_v2(self, case, run_id: str) -> ExplorationRecording:
        """探索单个用例 — v2: 观察 → 逐步执行(带PageMap) → 函数划分"""
        recording = ExplorationRecording(
            case_id=case.id, case_title=case.title,
            case_steps_text=[s.action for s in case.steps],
            case_expected=case.expected if hasattr(case, 'expected') else "",
            case_module=case.module,
            status="exploring",
        )
        if self._skill_content:
            await self.log("info", f"  Skill loaded: {len(self._skill_content)} chars")
        await self.log("info", f"  [v2] Exploring case: {case.title} ({len(case.steps)} steps)")

        await self._ensure_on_start_page(case)

        # Phase 1: 页面观察 — AI 输出结构化 PageMap
        page_map = await self._observe_page_structured(case, run_id)
        recording.page_maps.append(page_map)
        await self.log("info", f"  [v2] Page: {page_map.page_type}, {len(page_map.sections)} sections")

        # Phase 2: 逐步执行 — 带着 PageMap 上下文
        for step in case.steps:
            record = StepRecord(step_num=step.order, action_desc=step.action)

            # 记录操作前状态
            record.url_before = self.browser.page.url
            record.page_title_before = await self.browser.page.title()

            success = await self._execute_step_v2(case, step, record, run_id, recording, page_map)

            if not success:
                recording.status = "explore_failed"
                await self.log("info", f"  [v2] Case failed at step {step.order}")
                return recording

            # 记录操作后状态
            record.url_after = self.browser.page.url
            record.page_title_after = await self.browser.page.title()

            # URL 变化时更新 PageMap
            if record.url_before != record.url_after:
                new_page_map = await self._observe_page_structured(case, run_id)
                recording.page_maps.append(new_page_map)
                page_map = new_page_map
                await self.log("info", f"  [v2] Page changed, new map: {page_map.page_type}")

            recording.steps.append(record)

        # Phase 3: AI 识别函数划分
        recording.identified_functions = await self._identify_functions(case, recording)
        recording.status = "explored"
        await self.log("info", f"  [v2] Case explored: {case.title}, {len(recording.identified_functions)} functions")
        return recording

    async def _execute_step_v2(self, case, step, record: StepRecord, run_id: str,
                                recording: ExplorationRecording, page_map: PageMap) -> bool:
        """执行单步 — v2: 使用 PageMap 增强 AI 决策"""
        for attempt in range(self._max_step_retries):
            record.retry_count = attempt

            # 截图
            screenshot_path = f"test_artifacts/{run_id}/explore_{case.id}_s{step.order}_a{attempt}.png"
            try:
                await self.browser.take_screenshot(screenshot_path)
                record.screenshot_before = screenshot_path
            except Exception:
                pass

            # 收集元素（使用增强版层级收集）
            elements = await self.browser.collect_dom_hierarchy()
            elements_text = self.browser.format_elements_hierarchical(elements)

            # 页面地图摘要
            page_map_summary = self.summarize_page_map(page_map)

            # 已完成步骤
            previous_steps = self._format_previous_steps(recording.steps)

            user_prompt = ENHANCED_EXPLORATION_TEMPLATE.format(
                case_title=case.title,
                step_action=step.action,
                page_url=self.browser.page.url,
                page_title=await self.browser.page.title(),
                page_map_summary=page_map_summary,
                elements_text=elements_text,
                previous_steps=previous_steps,
            )

            try:
                if hasattr(self.ai, 'explore_decide'):
                    decision = await self.ai.explore_decide(
                        build_system_prompt(ENHANCED_EXPLORATION_SYSTEM_PROMPT, self._skill_content),
                        user_prompt
                    )
                else:
                    response = await self.ai.analyze(
                        build_system_prompt(ENHANCED_EXPLORATION_SYSTEM_PROMPT, self._skill_content),
                        user_prompt
                    )
                    decision = self._parse_decision(response)

                record.ai_action = decision.get("action", "")
                record.ai_selector = decision.get("selector", "")
                record.ai_value = decision.get("value", "")
                record.ai_reasoning = decision.get("reasoning", "")
                record.ai_confidence = decision.get("confidence", 0)
                record.semantic_action = decision.get("semantic_action", "")
                record.function_name_hint = decision.get("function_hint", "")

                await self.log("info", f"    [Step {step.order}] AI: {record.ai_action} -> {record.ai_selector} (conf={record.ai_confidence:.2f}, attempt={attempt+1})")

                # 记录被操作元素的上下文
                target_el = self._find_element_by_selector(elements, record.ai_selector)
                if target_el:
                    record.target_element_text = target_el.text
                    record.target_element_role = target_el.role or target_el.tag
                    record.parent_context = f"{target_el.parent_tag}.{'.'.join(target_el.parent_classes[:2])}"

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

            recording.total_retries += 1
            backoff = min(2 ** attempt, 8)
            await asyncio.sleep(backoff)

        return False

    def _find_element_by_selector(self, elements: list[ElementInfo], selector: str) -> ElementInfo | None:
        """根据 selector 找到对应的 ElementInfo"""
        if not selector:
            return None
        for el in elements:
            if el.selector == selector:
                return el
        # 模糊匹配
        for el in elements:
            if selector in el.selector or el.selector in selector:
                return el
        return None

    def _format_previous_steps(self, steps: list[StepRecord]) -> str:
        """格式化已完成的步骤，供 AI 参考"""
        if not steps:
            return "（无）"
        lines = []
        for s in steps:
            status = "成功" if s.success else "失败"
            lines.append(f"步骤{s.step_num}: {s.action_desc} -> {s.ai_action}({s.ai_selector}) [{status}]")
        return "\n".join(lines)

    async def _identify_functions(self, case, recording: ExplorationRecording) -> list[dict]:
        """AI 分析探索录制，识别出函数划分"""
        steps_summary = []
        for step in recording.steps:
            if not step.success:
                continue
            steps_summary.append({
                "step": step.step_num,
                "action": step.action_desc,
                "ai_action": step.ai_action,
                "target": step.target_element_text,
                "url_before": step.url_before,
                "url_after": step.url_after,
                "semantic": step.semantic_action,
                "function_hint": step.function_name_hint,
            })

        try:
            prompt = FUNCTION_IDENTIFICATION_TEMPLATE.format(
                case_title=case.title,
                case_expected=case.expected if hasattr(case, 'expected') else "",
                steps_json=json.dumps(steps_summary, ensure_ascii=False, indent=2),
            )
            response = await self.ai.analyze(
                build_system_prompt(FUNCTION_IDENTIFICATION_SYSTEM_PROMPT, self._skill_content),
                prompt
            )
            parsed = self._parse_page_map_response(response)
            return parsed.get("functions", [])
        except Exception as e:
            await self.log("info", f"  Function identification failed: {e}")
            return []

    async def _execute_step_with_retry(self, case, step, record: StepRecord, run_id: str, result: CaseExplorationResult, observation: str = "") -> bool:
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

            # 获取当前页面信息
            try:
                page_url = self.browser.page.url
                page_title = await self.browser.page.title()
            except Exception:
                page_url = "unknown"
                page_title = "unknown"

            # 检测登录状态
            has_password = any(
                e.attributes.get("type") == "password" for e in elements
            )
            login_status = "当前是登录页，需要执行登录操作" if has_password else "当前已登录，页面已跳转到系统内部"

            # 构建提示词
            user_prompt = EXPLORATION_USER_TEMPLATE.format(
                case_title=case.title,
                step_action=step.action,
                page_url=page_url,
                page_title=page_title,
                elements_text=elements_text,
            )
            # 附加登录状态和观察上下文
            context_parts = [login_status]
            if observation:
                context_parts.append(f"页面观察结果：{observation[:500]}")
            user_prompt = "\n\n".join(context_parts) + "\n\n" + user_prompt

            try:
                # 使用 explore_decide 获取完整决策（包含 selector/value）
                if hasattr(self.ai, 'explore_decide'):
                    decision = await self.ai.explore_decide(build_system_prompt(EXPLORATION_SYSTEM_PROMPT, self._skill_content), user_prompt)
                else:
                    response = await self.ai.analyze(build_system_prompt(EXPLORATION_SYSTEM_PROMPT, self._skill_content), user_prompt)
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
            # 指数退避等待（来自 lackeyjb playwright-skill retryWithBackoff）
            backoff = min(2 ** attempt, 8)  # 最大 8 秒
            await asyncio.sleep(backoff)

        return False

    async def _execute_action(self, action: str, selector: str, value: str) -> dict:
        """执行 AI 返回的操作 — 使用 safeClick/safeType 模式 + 控制台错误检查"""
        try:
            # 记录操作前的控制台日志位置
            log_before = self.browser.console_log_count()

            if action == "click":
                await self._safe_click(selector)
            elif action == "fill":
                await self._safe_type(selector, value)
            elif action == "select":
                await self.browser.page.wait_for_selector(selector, state="visible", timeout=5000)
                await self.browser.page.select_option(selector, value, timeout=5000)
            elif action == "hover":
                await self.browser.page.wait_for_selector(selector, state="visible", timeout=5000)
                await self.browser.page.hover(selector, timeout=5000)
                await asyncio.sleep(0.8)
            elif action == "assert":
                pass
            elif action == "wait":
                await asyncio.sleep(2)
            elif action == "drag":
                # drag: selector=源元素, value=目标元素
                await self.browser.page.wait_for_selector(selector, state="visible", timeout=5000)
                await self.browser.page.drag_and_drop(selector, value, timeout=5000)
                await asyncio.sleep(0.5)
            elif action == "scroll":
                await self.browser.page.evaluate("window.scrollBy(0, 300)")
            else:
                return {"success": False, "error": f"Unknown action: {action}"}

            # 操作后检查控制台是否有新错误
            console_errors = self.browser.get_console_errors(since=log_before)
            if console_errors:
                error_summary = "; ".join(console_errors[:3])
                return {"success": True, "console_errors": error_summary}

            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _safe_click(self, selector: str, retries: int = 3, timeout: int = 5000):
        """安全点击 — 等待可见 + 重试（来自 lackeyjb playwright-skill）"""
        for i in range(retries):
            try:
                await self.browser.page.wait_for_selector(selector, state="visible", timeout=timeout)
                await self.browser.page.click(selector, timeout=timeout)
                return
            except Exception:
                if i == retries - 1:
                    raise
                await asyncio.sleep(1 * (2 ** i))  # 指数退避

    async def _safe_type(self, selector: str, value: str, retries: int = 3):
        """安全输入 — 等待 + 清空 + type（Vue/Naive UI 兼容）"""
        for i in range(retries):
            try:
                await self.browser.page.wait_for_selector(selector, state="visible", timeout=5000)
                await self.browser.page.click(selector, timeout=3000)
                await self.browser.page.fill(selector, "", timeout=3000)
                await self.browser.page.type(selector, value, delay=50, timeout=5000)
                return
            except Exception:
                if i == retries - 1:
                    raise
                await asyncio.sleep(1 * (2 ** i))

    async def _observe_page(self, case, run_id: str) -> str:
        """观察页面，理解用例上下文 — AI 先看懂页面再操作"""
        try:
            elements = await self.browser.collect_interactive_elements()
            elements_text = self._format_elements(elements)
            page_url = self.browser.page.url
            page_title = await self.browser.page.title()

            # 截图记录观察阶段
            screenshot_path = f"test_artifacts/{run_id}/explore_{case.id}_observe.png"
            try:
                await self.browser.take_screenshot(screenshot_path)
            except Exception:
                pass

            user_prompt = OBSERVATION_USER_TEMPLATE.format(
                case_title=case.title,
                case_steps="\n".join(f"{s.order}. {s.action}" for s in case.steps),
                expected=case.expected if hasattr(case, 'expected') else "",
                page_url=page_url,
                page_title=page_title,
                elements_text=elements_text,
            )

            if hasattr(self.ai, 'observe'):
                response = await self.ai.observe(build_system_prompt(OBSERVATION_SYSTEM_PROMPT, self._skill_content), user_prompt)
                return response if response else ""
            else:
                response = await self.ai.analyze(build_system_prompt(OBSERVATION_SYSTEM_PROMPT, self._skill_content), user_prompt)
                return str(response) if response else ""
        except Exception as e:
            await self.log("info", f"  Observation failed: {e}")
            return ""

    async def _observe_page_structured(self, case, run_id: str) -> PageMap:
        """观察页面，输出结构化 PageMap — v2 版本"""
        try:
            elements = await self.browser.collect_dom_hierarchy()
            elements_text = self.browser.format_elements_hierarchical(elements)
            page_url = self.browser.page.url
            page_title = await self.browser.page.title()

            screenshot_path = f"test_artifacts/{run_id}/explore_{case.id}_observe.png"
            try:
                await self.browser.take_screenshot(screenshot_path)
            except Exception:
                pass

            user_prompt = PAGE_OBSERVATION_TEMPLATE.format(
                case_title=case.title,
                case_steps="\n".join(f"{s.order}. {s.action}" for s in case.steps),
                expected=case.expected if hasattr(case, 'expected') else "",
                page_url=page_url,
                page_title=page_title,
                elements_text=elements_text,
            )

            # 使用 observe 获取原始文本（analyze 返回 AIResponse 对象，不适合结构化解析）
            if hasattr(self.ai, 'observe'):
                raw_text = await self.ai.observe(
                    build_system_prompt(PAGE_MAP_SYSTEM_PROMPT, self._skill_content),
                    user_prompt
                )
            else:
                resp = await self.ai.analyze(
                    build_system_prompt(PAGE_MAP_SYSTEM_PROMPT, self._skill_content),
                    user_prompt
                )
                raw_text = resp.reasoning if hasattr(resp, 'reasoning') else str(resp)

            # 解析 AI 响应为 PageMap
            parsed = self._parse_page_map_response(raw_text)
            page_map = PageMap(
                page_type=parsed.get("page_type", "unknown"),
                page_url=page_url,
                page_title=page_title,
                sections=[PageSection(
                    name=s.get("name", ""),
                    description=s.get("description", ""),
                    section_type=s.get("type", ""),
                    element_count=s.get("element_count", 0),
                ) for s in parsed.get("sections", [])],
                key_elements=parsed.get("key_elements", {}),
                navigation_hints=parsed.get("navigation_hints", []),
                observation_summary=parsed.get("summary", ""),
            )
            return page_map
        except Exception as e:
            await self.log("info", f"  Structured observation failed: {e}")
            return PageMap(page_type="unknown", observation_summary=f"Observation failed: {e}")

    def _parse_page_map_response(self, response) -> dict:
        """解析 AI 的 PageMap 响应"""
        if isinstance(response, dict):
            return response
        try:
            parsed = json.loads(str(response))
            if isinstance(parsed, dict):
                return parsed
        except (json.JSONDecodeError, TypeError):
            pass
        try:
            match = re.search(r'\{[\s\S]*\}', str(response))
            if match:
                return json.loads(match.group())
        except (json.JSONDecodeError, TypeError):
            pass
        return {}

    def summarize_page_map(self, page_map: PageMap) -> str:
        """将 PageMap 摘要为文本，供后续步骤的 AI 参考"""
        parts = [f"页面类型: {page_map.page_type}"]
        if page_map.observation_summary:
            parts.append(f"页面概述: {page_map.observation_summary}")
        if page_map.sections:
            sections_desc = ", ".join(f"{s.name}({s.section_type})" for s in page_map.sections)
            parts.append(f"页面区域: {sections_desc}")
        if page_map.key_elements:
            elems = ", ".join(f"{k}={v}" for k, v in list(page_map.key_elements.items())[:10])
            parts.append(f"关键元素: {elems}")
        if page_map.navigation_hints:
            parts.append(f"导航提示: {'; '.join(page_map.navigation_hints[:3])}")
        return "\n".join(parts)

    async def _ensure_on_start_page(self, case):
        """确保探索用例前浏览器在合适的起始页面"""
        try:
            current_url = self.browser.page.url
            # 如果当前在编辑/详情页面，需要先回到首页
            detail_indicators = ["word-container", "editor", "detail", "docId="]
            if any(ind in current_url for ind in detail_indicators):
                await self.log("info", f"    Current page is detail page, navigating back...")
                # 通过点击菜单回到文档中心
                try:
                    menu = self.browser.page.locator('[role="menuitem"]').first
                    if await menu.count() > 0:
                        await menu.click()
                        await asyncio.sleep(2)
                except Exception:
                    pass
        except Exception:
            pass

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
            if attrs.get("title"):
                parts.append(f"title='{attrs['title']}'")
            if attrs.get("data-testid"):
                parts.append(f"testid='{attrs['data-testid']}'")
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
