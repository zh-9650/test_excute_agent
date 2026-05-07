import os
import json
import uuid
import time
import asyncio
from dataclasses import dataclass, field
from typing import Optional
from backend.models.case import TestCase, CaseStatus
from backend.engine.parser.csv_parser import CSVParser
from backend.engine.parser.enricher import CaseEnricher
from backend.engine.explorer.session import SessionManager
from backend.engine.explorer.browser import BrowserController
from backend.engine.explorer.engine import ExplorationEngine
from backend.engine.explorer.ai_explorer import AIExplorer, ExplorationRecording
from backend.engine.generator.generator import ScriptGenerator, AIScriptGenerator
from backend.engine.executor.executor import SmartExecutor, ExecutionContext
from backend.engine.executor.healing import HealingStore
from backend.engine.reporter.reporter import ReportGenerator
from backend.storage.database import get_db, init_db

# v3 engine imports
from backend.engine.browser.browser_tool import BrowserTools
from backend.engine.browser.semantic_snapshot import SemanticSnapshot
from backend.engine.agent.explorer_agent import ExplorerAgent
from backend.engine.recorder.action_ir import ActionIR
from backend.engine.recorder.run_recorder import RunRecorder
from backend.engine.generator.playwright_compiler import PlaywrightCompiler


@dataclass
class RunState:
    run_id: str
    suite_id: str
    target_url: str
    credentials: dict
    status: str = "pending"
    logs: list[dict] = field(default_factory=list)
    cases: list[TestCase] = field(default_factory=list)
    case_results: list[dict] = field(default_factory=list)
    exploration_result: dict = field(default_factory=dict)
    exploration_results: dict = field(default_factory=dict)  # case_id -> CaseExplorationResult
    exploration_recordings: dict = field(default_factory=dict)  # case_id -> ExplorationRecording (v2)
    action_irs: dict = field(default_factory=dict)  # case_id -> ActionIR (v3)
    scripts: dict[str, str] = field(default_factory=dict)
    start_time: float = 0.0
    end_time: float = 0.0
    ai_call_count: int = 0
    stop_requested: bool = False
    _pause_event: Optional[asyncio.Event] = field(default=None, repr=False)
    current_case_index: int = 0

    def __post_init__(self):
        if self._pause_event is None:
            self._pause_event = asyncio.Event()
            self._pause_event.set()  # 默认非暂停

    @property
    def pause_event(self) -> asyncio.Event:
        if self._pause_event is None:
            self._pause_event = asyncio.Event()
            self._pause_event.set()
        return self._pause_event

    @pause_event.setter
    def pause_event(self, value: asyncio.Event):
        self._pause_event = value

    def log(self, level: str, message: str):
        # Sanitize surrogate pairs that break JSON serialization
        clean = message.encode("utf-8", errors="replace").decode("utf-8", errors="replace")
        entry = {"ts": time.time(), "level": level, "msg": clean}
        self.logs.append(entry)

    def summary(self) -> dict:
        passed = sum(1 for r in self.case_results if r.get("status") == "passed")
        failed = sum(1 for r in self.case_results if r.get("status") == "failed")
        blocked = sum(1 for r in self.case_results if r.get("status") == "blocked")
        error = sum(1 for r in self.case_results if r.get("status") == "error")
        return {"total": len(self.case_results), "passed": passed, "failed": failed, "blocked": blocked, "error": error}


class Orchestrator:
    def __init__(self, config, log_callback=None):
        self.config = config
        self.log_callback = log_callback
        self.session_mgr = SessionManager()
        self.generator = ScriptGenerator(ai=config.create_provider() if config.ai_api_key else None)
        self.ai_script_generator = AIScriptGenerator(ai=config.create_provider() if config.ai_api_key else None)
        self._browser = None  # 共享浏览器实例
        self.healing = HealingStore()

    async def _log(self, state: RunState, level: str, msg: str):
        state.log(level, msg)
        if self.log_callback:
            await self.log_callback(state.run_id, {"level": level, "msg": msg, "ts": time.time()})

    async def run(self, suite_id: str, target_url: str, credentials: dict, enrichment_data: dict = None, state: RunState = None) -> RunState:
        if state is None:
            state = RunState(run_id=str(uuid.uuid4())[:8], suite_id=suite_id, target_url=target_url, credentials=credentials)

        # Give WebSocket time to connect before starting heavy work
        await asyncio.sleep(1.0)
        run_id = state.run_id
        state.start_time = time.time()

        await self._log(state, "info", f"=== Test start (run_id={run_id}) ===")
        await self._log(state, "info", f"Target: {target_url}, Suite: {suite_id}")

        state.cases = self._load_cases(suite_id)
        await self._log(state, "info", f"Loaded {len(state.cases)} test cases")

        if enrichment_data:
            await self._log(state, "info", "Applying user enrichment data...")
            enricher = CaseEnricher()
            for case in state.cases:
                if case.id in enrichment_data:
                    enricher.apply_enrichment(case, enrichment_data[case.id])

        # Phase 1: AI Exploration
        state.status = "exploring"
        use_v3 = getattr(self.config, 'use_v3_engine', False)
        use_v2 = getattr(self.config, 'use_v2_engine', False)
        if use_v3:
            await self._log(state, "info", "--- Phase 1: AI Exploration (v3 Engine - BrowserTools + Action IR) ---")
            exploration = await self._explore_ai_v3(state, target_url, credentials)
        elif use_v2:
            await self._log(state, "info", "--- Phase 1: AI Exploration (v2 Engine) ---")
            exploration = await self._explore_ai_v2(state, target_url, credentials)
        else:
            await self._log(state, "info", "--- Phase 1: AI Exploration ---")
            exploration = await self._explore_ai(state, target_url, credentials)
        state.exploration_result = exploration

        # 如果目标完全不可达，直接终止
        if exploration.get("error"):
            state.status = "failed"
            state.end_time = time.time()
            await self._log(state, "error", f"Target unreachable: {exploration['error']}")
            await self._log(state, "error", "Test aborted - cannot reach target URL")
            self._generate_report(state, {"bugs": [], "script_issues": [], "environment_issues": [{"reason": exploration["error"]}], "case_issues": []})
            return state

        # Phase 2: Script Generation (from exploration records)
        state.status = "generating"
        if use_v3 and state.action_irs:
            await self._log(state, "info", "--- Phase 2: Script Compilation (v3 - IR → Playwright) ---")
            await self._generate_scripts_v3(state)
        elif use_v2 and state.exploration_recordings:
            await self._log(state, "info", "--- Phase 2: AI Script Generation (v2) ---")
            await self._generate_scripts_v2(state)
        else:
            await self._log(state, "info", "--- Phase 2: Script Generation ---")
            await self._generate_scripts_v1(state, exploration)

        await self._log(state, "info", f"Generated {len(state.scripts)} scripts")

        # Phase 3: Execution
        state.status = "running"
        await self._log(state, "info", "--- Phase 3: Smart Execution ---")
        await self._execute_all(state, credentials)

        # Phase 4: Analysis
        state.status = "analyzing"
        await self._log(state, "info", "--- Phase 4: Result Analysis ---")
        executor = SmartExecutor()
        analysis = executor.classify_results(state.case_results)

        # Phase 5: Report
        await self._log(state, "info", "--- Phase 5: Report Generation ---")
        report = self._generate_report(state, analysis)

        state.status = "completed"
        state.end_time = time.time()
        duration = state.end_time - state.start_time
        await self._log(state, "info", f"=== Test complete ({duration:.0f}s) ===")
        await self._log(state, "info", f"Passed: {state.summary()['passed']}, Failed: {state.summary()['failed']}, Blocked: {state.summary()['blocked']}")

        self._persist_results(state)
        return state

    def _load_cases(self, suite_id: str) -> list[TestCase]:
        db = get_db()
        rows = db.execute("SELECT * FROM test_cases WHERE suite_id = ?", (suite_id,)).fetchall()
        db.close()
        from backend.models.case import Step
        cases = []
        for r in rows:
            d = dict(r)
            steps_data = json.loads(d.get("steps", "[]"))
            steps = [Step(order=s.get("order", 0), action=s.get("action", ""),
                         enrichment=s.get("enrichment")) for s in steps_data]
            case = TestCase(
                id=d["id"], suite_id=d["suite_id"], module=d.get("module", ""), title=d.get("title", ""),
                preconditions=d.get("preconditions", ""), steps=steps,
                expected=d.get("expected", ""), keywords=d.get("keywords", ""),
                priority=d.get("priority", 2), test_type=d.get("test_type", ""),
                stage=d.get("stage", ""), status=CaseStatus(d.get("status", "pending")),
                completeness=d.get("completeness", "unknown")
            )
            cases.append(case)
        return cases

    async def explore_only(self, state: RunState, target_url: str, credentials: dict):
        """Step 1: AI 探索 — 打开浏览器，AI 逐步预执行每个用例"""
        state.cases = self._load_cases(state.suite_id)
        await self._log(state, "info", f"Loaded {len(state.cases)} test cases")
        state.status = "exploring"

        use_v3 = getattr(self.config, 'use_v3_engine', False)
        use_v2 = getattr(self.config, 'use_v2_engine', False)

        if use_v3:
            await self._log(state, "info", "--- Exploration (v3 Engine - BrowserTools + Action IR) ---")
            exploration = await self._explore_ai_v3(state, target_url, credentials)
        elif use_v2:
            await self._log(state, "info", "--- Exploration (v2 Engine) ---")
            exploration = await self._explore_ai_v2(state, target_url, credentials)
        else:
            await self._log(state, "info", "--- Exploration (v1) ---")
            exploration = await self._explore_ai(state, target_url, credentials)

        state.exploration_result = exploration
        return exploration

    async def execute_only(self, state: RunState):
        """仅执行：逐步调用 Playwright 执行每个用例的步骤"""
        browser = BrowserController(headless=self.config.browser_headless)
        try:
            await browser.start()

            # 检查 IR 中是否有登录相关步骤
            has_login_in_ir = False
            if state.action_irs:
                for case_id, ir in state.action_irs.items():
                    for step in ir.steps:
                        if step.natural_step and ("登录" in step.natural_step or "用户名" in step.natural_step or "密码" in step.natural_step):
                            has_login_in_ir = True
                            break
                    if has_login_in_ir:
                        break

            if has_login_in_ir:
                # 有登录测试用例：不恢复登录态，直接访问目标URL（会被重定向到登录页）
                await self._log(state, "info", "IR 包含登录步骤，跳过自动登录，直接访问目标URL")
                await browser.goto(state.target_url, wait_until="networkidle")
                await asyncio.sleep(2)
            else:
                # 无登录用例：恢复登录态
                storage_state = self.session_mgr.load_storage_state(state.run_id)
                if storage_state:
                    await self._log(state, "info", "Restoring saved login session...")
                    await browser.page.context.add_cookies(storage_state.get("cookies", []))
                    await browser.goto(state.target_url)
                else:
                    await self._log(state, "info", "No saved session, navigating to target...")
                    await browser.goto(state.target_url)
                await browser.wait_for_page_ready()
                await asyncio.sleep(2)
                # 验证登录状态 — 如果还在登录页，重新登录
                await self._verify_and_login(browser, state)

            use_v3 = getattr(self.config, 'use_v3_engine', False)

            if use_v3 and state.action_irs:
                # v3: 用 BrowserTools 回放 ActionIR（通过规则匹配定位元素）
                await self._log(state, "info", "--- Execution (v3 - IR Replay) ---")
                from backend.engine.browser.browser_tool import BrowserTools
                from backend.engine.agent.explorer_agent import ExplorerAgent
                import re
                import json as _json
                tools = BrowserTools(browser.page)
                # 创建一个临时 agent 用于规则匹配
                agent = ExplorerAgent(tools, None, log_callback=lambda level, msg: None, credentials=state.credentials)

                for idx, case in enumerate(state.cases):
                    if case.id not in state.action_irs:
                        continue
                    if state.stop_requested:
                        await self._log(state, "info", "Stop requested, halting execution")
                        break
                    await state.pause_event.wait()

                    ir = state.action_irs[case.id]
                    result = {"case_id": case.id, "case_title": case.title, "status": "passed", "steps": [], "ai_call_count": 0}
                    await self._log(state, "info", f"Executing: {case.title}")

                    for step in ir.steps:
                        if step.status != "passed" or step.action in ("unknown", "done", "blocked"):
                            continue
                        try:
                            # 每步先采集快照，用规则匹配定位元素
                            snap_result = await tools.snapshot()
                            if not snap_result.success:
                                raise Exception(f"快照失败: {snap_result.message}")
                            snapshot_data = snap_result.data

                            # 用规则匹配从自然语言步骤描述中找到目标元素（支持多动作）
                            rule_tcs = agent._try_rule_based_actions(step.natural_step, snapshot_data)
                            if rule_tcs:
                                tool_calls_to_exec = []
                                for tc in rule_tcs:
                                    func = tc["function"]
                                    fn = func["name"]
                                    fa = _json.loads(func["arguments"]) if isinstance(func["arguments"], str) else func["arguments"]
                                    tool_calls_to_exec.append((fn, fa))
                                    await self._log(state, "info", f"  Replay: {step.natural_step} → 规则匹配 {fn}({fa})")
                            else:
                                # 规则不匹配，使用 IR 中记录的动作和 locator
                                tool_calls_to_exec = [(step.action, {"ref": step.target_ref, "value": step.value, "locator": step.locator})]
                                await self._log(state, "info", f"  Replay: {step.natural_step} → IR 回退 {step.action}")

                            for fn, fa in tool_calls_to_exec:
                                if fn == "click":
                                    r = await tools.click(ref=fa.get("ref", ""), locator=fa.get("locator"))
                                elif fn == "fill":
                                    r = await tools.fill(ref=fa.get("ref", ""), value=fa.get("value", ""), locator=fa.get("locator"))
                                elif fn == "navigate":
                                    r = await tools.navigate(fa.get("url", fa.get("value", "")))
                                elif fn == "hover":
                                    r = await tools.hover(ref=fa.get("ref", ""), locator=fa.get("locator"))
                                elif fn == "select_option":
                                    r = await tools.select_option(ref=fa.get("ref", ""), value=fa.get("value", ""), locator=fa.get("locator"))
                                elif fn == "wait":
                                    r = await tools.wait(int(fa.get("ms", 1000)))
                                else:
                                    await self._log(state, "info", f"  跳过未知动作: {fn}")
                                    continue

                                if r and not r.success:
                                    raise Exception(r.message)
                                # fill 后等待 Vue 重渲染
                                if fn == "fill":
                                    try:
                                        await browser.page.wait_for_load_state("networkidle", timeout=3000)
                                    except Exception:
                                        pass
                                    await asyncio.sleep(0.5)
                                    # 重新采集快照供后续动作使用
                                    await tools.snapshot()

                            result["steps"].append({"step": step.order, "action": step.action, "status": "passed"})
                        except Exception as e:
                            result["steps"].append({"step": step.order, "action": step.action, "status": "failed", "reason": str(e)})
                            result["status"] = "failed"
                            await self._log(state, "warn", f"  Replay failed: {e}")

                    state.case_results.append(result)
                    icon = "PASS" if result["status"] == "passed" else "FAIL"
                    await self._log(state, "info", f"  [{icon}] {case.title}")
            else:
                # v1/v2: 旧的 SmartExecutor 执行
                executor_log = lambda msg: self._log(state, "ai", msg)
                ai_provider = self.config.create_provider() if self.config.ai_api_key else None
                backup_provider = self.config.create_backup_provider() if self.config.ai_backup_model else None
                executor = SmartExecutor(browser=browser, ai=ai_provider, backup_ai=backup_provider, log_callback=executor_log, target_url=state.target_url)

                for idx, case in enumerate(state.cases):
                    if case.completeness not in ("complete", "enriched"):
                        continue
                    if state.stop_requested:
                        await self._log(state, "info", "Stop requested, halting execution")
                        break
                    await state.pause_event.wait()

                    state.current_case_index = idx
                    if executor.is_melted():
                        await self._log(state, "warn", f"MELTDOWN: {executor.melt_reason()}")
                        break

                    await self._log(state, "info", f"Executing: {case.title}")
                    case.transition_to(CaseStatus.RUNNING)
                    ctx = ExecutionContext(case=case, session_id="")
                    result = await executor.execute_case(ctx)
                    state.case_results.append(result)
                    state.ai_call_count += ctx.ai_call_count

                    icon = "PASS" if result["status"] == "passed" else "FAIL" if result["status"] == "failed" else "WARN"
                    await self._log(state, "info", f"  [{icon}] {case.title}")
        finally:
            await browser.stop()

    async def _explore(self, state: RunState, target_url: str, credentials: dict) -> dict:
        browser = BrowserController(headless=self.config.browser_headless)
        try:
            await self._log(state, "info", "Launching browser...")
            await browser.start()

            username = credentials.get("username", "")
            password = credentials.get("password", "")
            session = self.session_mgr.create(target_url, username, password, session_id=state.run_id)

            if username and password:
                await self._log(state, "info", f"Navigating to {target_url} and detecting login form...")
                goto_result = await browser.goto(target_url)
                if not goto_result["success"]:
                    await self._log(state, "error", f"Cannot reach target URL: {goto_result.get('error', 'unknown')}")
                    return {"error": f"Cannot reach {target_url}: {goto_result.get('error')}", "pages_explored": [], "pages_skipped": []}
                await browser.wait_for_page_ready(strategy="domcontentloaded")
                await self._detect_and_login(browser, state, username, password)
            else:
                await self._log(state, "info", "No credentials provided, skipping login")

            explore_log = lambda msg: self._log(state, "info", msg)
            engine = ExplorationEngine(browser=browser, ai=self.config.create_provider() if self.config.ai_api_key else None, log_callback=explore_log)
            result = await engine.explore(state.cases, session, target_url)

            return {
                "pages_explored": result.pages_explored,
                "pages_skipped": result.pages_skipped,
                "total_elements": result.total_elements,
                "coverage": result.coverage_score,
            }
        except Exception as e:
            import traceback
            await self._log(state, "error", f"Exploration failed: {e}")
            await self._log(state, "error", traceback.format_exc()[-300:])
            return {"error": str(e), "pages_explored": [], "pages_skipped": []}
        finally:
            await browser.stop()

    async def _explore_ai(self, state: RunState, target_url: str, credentials: dict) -> dict:
        """AI 驱动探索 — 打开浏览器，登录，然后让 AI 逐步预执行每个用例"""
        browser = BrowserController(headless=self.config.browser_headless)
        self._browser = browser  # 保存供执行阶段复用
        try:
            await self._log(state, "info", "Launching browser for AI exploration...")
            await browser.start()

            username = credentials.get("username", "")
            password = credentials.get("password", "")
            self.session_mgr.create(target_url, username, password, session_id=state.run_id)

            # 导航到目标站点
            goto_result = await browser.goto(target_url)
            if not goto_result["success"]:
                await self._log(state, "error", f"Cannot reach target URL: {goto_result.get('error')}")
                return {"error": f"Cannot reach {target_url}: {goto_result.get('error')}"}

            await browser.wait_for_page_ready(strategy="domcontentloaded")
            await asyncio.sleep(3)  # 等待 JS 框架渲染完成

            # 自动登录（一次）
            if username and password:
                await self._log(state, "info", "Detecting and performing login...")
                await self._detect_and_login(browser, state, username, password)
            else:
                await self._log(state, "info", "No credentials provided, skipping login")

            # 保存登录态
            try:
                cookies = await browser.page.context.cookies()
                self.session_mgr.save_storage_state(state.run_id, {"cookies": cookies})
                await self._log(state, "info", "Login state saved")
            except Exception:
                pass

            # AI 逐步探索每个用例
            ai_provider = self.config.create_provider() if self.config.ai_api_key else None
            if not ai_provider:
                await self._log(state, "error", "No AI provider configured, cannot explore")
                return {"error": "No AI provider configured"}

            async def explorer_log(level, msg):
                await self._log(state, level, msg)
            explorer = AIExplorer(browser=browser, ai_provider=ai_provider, log_callback=explorer_log)

            explored, failed = 0, 0
            for i, case in enumerate(state.cases):
                if state.stop_requested:
                    await self._log(state, "info", "Stop requested, halting exploration")
                    break

                await state.pause_event.wait()
                state.current_case_index = i

                case_result = await explorer.explore_case(case, state.run_id)
                state.exploration_results[case.id] = case_result

                if case_result.status == "explored":
                    explored += 1
                else:
                    failed += 1

            # 构建探索结果摘要
            all_steps = []
            for cr in state.exploration_results.values():
                all_steps.extend(cr.steps)

            return {
                "explored_cases": explored,
                "failed_cases": failed,
                "total_cases": len(state.cases),
                "total_steps": len(all_steps),
                "total_retries": sum(cr.total_retries for cr in state.exploration_results.values()),
                "case_results": {cid: {"status": cr.status, "steps": len(cr.steps)} for cid, cr in state.exploration_results.items()},
            }
        except Exception as e:
            import traceback
            await self._log(state, "error", f"AI Exploration failed: {e}")
            await self._log(state, "error", traceback.format_exc()[-300:])
            return {"error": str(e)}

    async def _explore_ai_v2(self, state: RunState, target_url: str, credentials: dict) -> dict:
        """v2 AI 探索 — 观察DOM + 结构化PageMap + 增强录制"""
        browser = BrowserController(headless=self.config.browser_headless)
        self._browser = browser
        try:
            await self._log(state, "info", "Launching browser for AI exploration (v2)...")
            await browser.start()

            username = credentials.get("username", "")
            password = credentials.get("password", "")
            self.session_mgr.create(target_url, username, password, session_id=state.run_id)

            goto_result = await browser.goto(target_url)
            if not goto_result["success"]:
                await self._log(state, "error", f"Cannot reach target URL: {goto_result.get('error')}")
                return {"error": f"Cannot reach {target_url}: {goto_result.get('error')}"}

            await browser.wait_for_page_ready(strategy="domcontentloaded")
            await asyncio.sleep(3)

            if username and password:
                await self._log(state, "info", "Detecting and performing login...")
                await self._detect_and_login(browser, state, username, password)
            else:
                await self._log(state, "info", "No credentials provided, skipping login")

            try:
                cookies = await browser.page.context.cookies()
                self.session_mgr.save_storage_state(state.run_id, {"cookies": cookies})
                await self._log(state, "info", "Login state saved")
            except Exception:
                pass

            ai_provider = self.config.create_provider() if self.config.ai_api_key else None
            if not ai_provider:
                await self._log(state, "error", "No AI provider configured, cannot explore")
                return {"error": "No AI provider configured"}

            async def explorer_log(level, msg):
                await self._log(state, level, msg)
            explorer = AIExplorer(browser=browser, ai_provider=ai_provider, log_callback=explorer_log)

            explored, failed = 0, 0
            for i, case in enumerate(state.cases):
                if state.stop_requested:
                    await self._log(state, "info", "Stop requested, halting exploration")
                    break

                await state.pause_event.wait()
                state.current_case_index = i

                recording = await explorer.explore_case_v2(case, state.run_id)
                state.exploration_recordings[case.id] = recording

                if recording.status == "explored":
                    explored += 1
                else:
                    failed += 1

            return {
                "explored_cases": explored,
                "failed_cases": failed,
                "total_cases": len(state.cases),
                "engine_version": "v2",
                "total_recordings": len(state.exploration_recordings),
            }
        except Exception as e:
            import traceback
            await self._log(state, "error", f"AI Exploration v2 failed: {e}")
            await self._log(state, "error", traceback.format_exc()[-300:])
            return {"error": str(e)}

    async def _generate_scripts_v1(self, state: RunState, exploration: dict):
        """v1 脚本生成 — 模板拼接 + AI 回退"""
        for case in state.cases:
            script = None
            if case.id in state.exploration_results:
                exp_result = state.exploration_results[case.id]
                if exp_result.status == "explored":
                    await self._log(state, "info", f"  Generating from exploration: {case.title}")
                    script = self.generator.generate_from_exploration(case, exp_result)
                else:
                    await self._log(state, "warn", f"Skipping case (exploration {exp_result.status}): {case.title}")
                    continue
            elif case.completeness not in ("complete", "enriched"):
                await self._log(state, "warn", f"Skipping incomplete case: {case.title}")
                continue

            if not script and self.config.ai_api_key:
                await self._log(state, "ai", f"  [AI] Generating script for: {case.title}")
                element_map = self._build_element_map(exploration)
                script = await self.generator.generate_with_ai(case, element_map)

            if not script:
                element_map = self._build_element_map(exploration)
                script = self.generator.build_script_template(case, element_map)

            precheck = self.generator.precheck(script)
            if precheck["valid"]:
                state.scripts[case.id] = script
            else:
                await self._log(state, "warn", f"Script precheck failed [{case.title}]: {precheck['errors']}")

    async def _generate_scripts_v2(self, state: RunState):
        """v2 AI 脚本生成 — 根据 ExplorationRecording 生成 Codex 风格结构化脚本"""
        for case in state.cases:
            if case.id not in state.exploration_recordings:
                await self._log(state, "warn", f"Skipping case (no recording): {case.title}")
                continue

            recording = state.exploration_recordings[case.id]
            if recording.status != "explored":
                await self._log(state, "warn", f"Skipping case (recording {recording.status}): {case.title}")
                continue

            await self._log(state, "info", f"  [AI v2] Generating structured script: {case.title}")
            try:
                script = await self.ai_script_generator.generate_from_recording(case, recording)
                if script:
                    precheck = self.ai_script_generator.precheck(script)
                    if precheck["valid"]:
                        state.scripts[case.id] = script
                        await self._log(state, "info", f"  Script generated ({len(script)} chars)")
                    else:
                        await self._log(state, "warn", f"Script precheck failed [{case.title}]: {precheck['errors']}")
                        state.scripts[case.id] = script
                else:
                    await self._log(state, "warn", f"AI returned empty script for: {case.title}")
            except Exception as e:
                import traceback
                await self._log(state, "error", f"Script generation failed [{case.title}]: {type(e).__name__}: {e}")
                await self._log(state, "error", traceback.format_exc()[-300:])

    async def _explore_ai_v3(self, state: RunState, target_url: str, credentials: dict) -> dict:
        """v3 探索 — BrowserTools + ExplorerAgent + ActionIR"""
        browser = BrowserController(headless=getattr(self.config, 'browser_headless', False))
        await browser.start()
        self._browser = browser

        try:
            # 登录
            username = credentials.get("username", "")
            password = credentials.get("password", "")
            self.session_mgr.create(target_url, username, password, session_id=state.run_id)
            await browser.goto(target_url, wait_until="networkidle")
            await asyncio.sleep(2)

            # 检查是否有用例包含登录步骤
            has_login_case = False
            for case in state.cases:
                for step in case.steps:
                    if step.action and ("登录" in step.action or "用户名" in step.action or "密码" in step.action):
                        has_login_case = True
                        break
                if has_login_case:
                    break

            # 只有在没有登录相关测试用例时才自动登录
            if not has_login_case:
                await self._log(state, "info", "未检测到登录相关步骤，执行自动登录")
                await self._detect_and_login_v3(browser, state, username, password)
            else:
                await self._log(state, "info", "检测到登录相关测试用例，跳过自动登录，由测试用例处理")

            # 初始化 v3 组件
            page = browser.page
            tools = BrowserTools(page)
            ai_provider = self.config.create_provider()
            agent = ExplorerAgent(
                tools,
                ai_provider,
                log_callback=lambda level, msg: asyncio.ensure_future(self._log(state, level, msg)),
                credentials={"username": username, "password": password},
            )
            recorder = RunRecorder(state.run_id)

            # 逐用例探索
            for i, case in enumerate(state.cases):
                if state.stop_requested:
                    await self._log(state, "info", "Stop requested, aborting exploration")
                    break

                state.current_case_index = i
                await self._log(state, "info", f"--- Exploring case {i+1}/{len(state.cases)}: {case.title} ---")

                try:
                    exploration_result = await agent.explore_case(case, state.run_id)
                    ir = recorder.record_case(case, exploration_result)

                    # 保存 IR
                    state.action_irs[case.id] = ir
                    recorder.save_ir(ir)

                    # 同时保存到 exploration_results 供 Phase 3 回放
                    state.exploration_results[case.id] = exploration_result

                    state.case_results.append({
                        "case_id": case.id,
                        "status": exploration_result.status,
                        "step_count": len(exploration_result.steps),
                        "ai_calls": exploration_result.total_ai_calls,
                    })

                    await self._log(state, "info", f"  Case result: {exploration_result.status} ({len(ir.steps)} steps)")

                except Exception as e:
                    import traceback
                    await self._log(state, "error", f"  Case exploration failed: {type(e).__name__}: {e}")
                    await self._log(state, "error", traceback.format_exc()[-300:])
                    state.case_results.append({"case_id": case.id, "status": "error", "error": str(e)})

            # 保存合并 IR 和 tool calls 日志
            all_irs = list(state.action_irs.values())
            if all_irs:
                recorder.save_all_irs(all_irs)
            recorder.save_tool_calls_log()

            return {"status": "completed", "case_count": len(state.action_irs)}

        except Exception as e:
            import traceback
            await self._log(state, "error", f"v3 exploration failed: {type(e).__name__}: {e}")
            return {"error": str(e)}
        # 注意：不在这里关闭浏览器，Phase 3 执行阶段需要复用

    async def _generate_scripts_v3(self, state: RunState):
        """v3 脚本编译 — IR → Playwright Python 脚本（确定性编译，无需 AI）"""
        compiler = PlaywrightCompiler()

        for case in state.cases:
            if case.id not in state.action_irs:
                await self._log(state, "warn", f"Skipping case (no IR): {case.title}")
                continue

            ir = state.action_irs[case.id]
            await self._log(state, "info", f"  [v3] Compiling script: {case.title}")

            script, errors = compiler.compile_with_validation(ir)
            if errors:
                await self._log(state, "warn", f"  Validation warnings: {errors}")

            if script:
                state.scripts[case.id] = script
                # 保存脚本到文件
                script_dir = os.path.join("test_artifacts", state.run_id, "scripts")
                os.makedirs(script_dir, exist_ok=True)
                from backend.engine.generator.playwright_compiler import _sanitize_identifier
                safe_id = _sanitize_identifier(case.id)
                script_path = os.path.join(script_dir, f"test_{safe_id}.py")
                with open(script_path, "w", encoding="utf-8") as f:
                    f.write(script)
                await self._log(state, "info", f"  Script compiled ({len(script)} chars) → {script_path}")
            else:
                await self._log(state, "warn", f"  Empty script for: {case.title}")

    async def _detect_and_login(self, browser, state: RunState, username: str, password: str):
        """检测登录表单并自动登录（支持中英文，支持弹窗式登录）"""
        await self._log(state, "info", "  Scanning for login form...")
        elements = await browser.collect_interactive_elements()
        await self._log(state, "info", f"  Found {len(elements)} interactive elements on page")

        # 打印所有 input 元素的属性用于调试
        for el in elements:
            if el.tag == "input":
                await self._log(state, "info", f"    INPUT: type={el.attributes.get('type','')} placeholder={el.attributes.get('placeholder','')} classes={el.classes}")

        # 检查是否有密码框（直接登录页）
        has_password_input = any(
            (e.tag == "input" and (
                e.attributes.get("type") == "password" or
                "password" in f"{e.text} {e.aria_label} {' '.join(e.classes)}".lower()
            ))
            for e in elements
        )
        await self._log(state, "info", f"  has_password_input = {has_password_input}")

        # 如果没有密码框，可能需要先点击"登录"按钮弹出登录框
        if not has_password_input:
            await self._log(state, "info", "  No password field on page, looking for login button...")
            login_btn = None
            for el in elements:
                if el.tag == "button":
                    txt = (el.text + el.aria_label).strip()
                    if any(k in txt for k in ["登录", "登 录", "Login", "Sign in", "sign in"]):
                        login_btn = el
                        break
                    # 也匹配 link 类型
                if el.tag == "a":
                    txt = (el.text + el.aria_label).strip()
                    if any(k in txt for k in ["登录", "登 录", "Login", "Sign in"]):
                        login_btn = el
                        break

            if login_btn:
                await self._log(state, "info", f"  Found login button: '{login_btn.text}', clicking...")
                try:
                    await browser.page.click(login_btn.selector)
                    await asyncio.sleep(1.5)
                    await browser.wait_for_page_ready(strategy="domcontentloaded")
                    # 重新收集元素（登录框已弹出）
                    elements = await browser.collect_interactive_elements()
                    has_password_input = any(
                        (e.tag == "input" and (
                            e.attributes.get("type") == "password" or
                            "password" in f"{e.text} {e.aria_label} {' '.join(e.classes)}".lower()
                        ))
                        for e in elements
                    )
                    if has_password_input:
                        await self._log(state, "info", f"  Login modal opened, found {len(elements)} elements")
                    else:
                        await self._log(state, "warn", "  Clicked login button but no password field appeared")
                except Exception as e:
                    await self._log(state, "warn", f"  Failed to click login button: {e}")

        if not has_password_input:
            # 最后检查页面文本
            page_summary = await browser.get_page_summary()
            text = page_summary.get("text_snippet", "").lower()
            login_keywords = ["login", "password", "sign in", "登录", "密码", "用户名", "账号"]
            if not any(kw in text for kw in login_keywords):
                await self._log(state, "info", "  No login form detected, skipping login")
                return

        await self._log(state, "info", f"  Login form detected ({len(elements)} elements), identifying fields...")

        # 找输入框：password 类型 = 密码，第一个非密码 input = 用户名
        # 使用 type 属性确保选择器唯一（避免多个 input 共享 class 导致 fill 只命中第一个）
        username_sel, password_sel, submit_sel = None, None, None
        for el in elements:
            el_type = el.attributes.get("type", "")
            el_placeholder = el.attributes.get("placeholder", "")
            attrs = f"{el.tag} {el.text} {el.aria_label} {' '.join(el.classes)} {el_type} {el_placeholder}".lower()
            if not password_sel and el.tag == "input" and (el_type == "password" or "password" in attrs):
                # 用 [type='password'] 确保唯一
                password_sel = "input[type='password']"
                await self._log(state, "info", f"  Found password: {password_sel}")
            elif not username_sel and el.tag == "input":
                if el_type not in ("hidden", "password") and "password" not in attrs:
                    # 用 [type='text'] 确保唯一
                    username_sel = "input[type='text']"
                    await self._log(state, "info", f"  Found username: {username_sel} (placeholder={el_placeholder})")
            if not submit_sel and el.tag == "button":
                txt = (el.text + el.aria_label).lower()
                if any(k in txt for k in ["login", "sign", "submit", "登录", "登 录", "确 认", "确认", "确定"]):
                    submit_sel = el.selector
                    await self._log(state, "info", f"  Found submit: {el.selector}")

        # 如果找不到 submit，用最后一个 button 或 Enter 键
        if not submit_sel:
            buttons = [e for e in elements if e.tag == "button"]
            if buttons:
                submit_sel = buttons[-1].selector
                await self._log(state, "info", f"  Using last button as submit: {submit_sel}")

        if not username_sel or not password_sel:
            await self._log(state, "warn", "  Could not identify all login fields, trying with common selectors")
            username_sel = "input[type='text']" if not username_sel else username_sel
            password_sel = "input[type='password']" if not password_sel else password_sel

        try:
            await self._log(state, "info", f"  Filling username '{username}' into {username_sel}")
            # 先清空再逐字输入，触发 UI 框架的响应式更新
            await browser.page.click(username_sel)
            await browser.page.fill(username_sel, "")
            await browser.page.type(username_sel, username, delay=50)

            await self._log(state, "info", f"  Filling password into {password_sel}")
            await browser.page.click(password_sel)
            await browser.page.fill(password_sel, "")
            await browser.page.type(password_sel, password, delay=50)

            # 记录当前URL，用于检测登录后跳转
            url_before = browser.page.url

            if submit_sel:
                await self._log(state, "info", f"  Clicking login: {submit_sel}")
                await browser.page.click(submit_sel)
            else:
                await browser.page.keyboard.press("Enter")
                await self._log(state, "info", "  Pressed Enter to submit")

            # 等待页面跳转（URL 变化）
            try:
                await browser.page.wait_for_url(lambda url: url != url_before, timeout=10000)
            except Exception:
                pass
            await browser.wait_for_page_ready(strategy="domcontentloaded")

            # 验证登录是否成功：检查是否还在登录页
            url_after = browser.page.url
            still_has_password = False
            try:
                pwd_field = browser.page.locator("input[type='password']")
                still_has_password = await pwd_field.count() > 0 and await pwd_field.first.is_visible()
            except Exception:
                pass

            if still_has_password and url_before == url_after:
                # 还在登录页，登录可能失败。重试
                await self._log(state, "warn", "  Still on login page after submit, retrying...")
                try:
                    # 重新填写（用 type 触发框架事件）
                    await browser.page.click(username_sel)
                    await browser.page.fill(username_sel, "")
                    await browser.page.type(username_sel, username, delay=50)
                    await browser.page.click(password_sel)
                    await browser.page.fill(password_sel, "")
                    await browser.page.type(password_sel, password, delay=50)
                    await asyncio.sleep(0.5)
                    # 尝试按 Enter 提交
                    await browser.page.keyboard.press("Enter")
                    try:
                        await browser.page.wait_for_url(lambda url: url != url_before, timeout=10000)
                    except Exception:
                        pass
                    await browser.wait_for_page_ready(strategy="domcontentloaded")
                except Exception as retry_e:
                    await self._log(state, "warn", f"  Retry failed: {retry_e}")

            # 再次验证
            still_has_password = False
            try:
                pwd_field = browser.page.locator("input[type='password']")
                still_has_password = await pwd_field.count() > 0 and await pwd_field.first.is_visible()
            except Exception:
                pass

            if still_has_password:
                await self._log(state, "error", "  Login FAILED - still on login page after retries")
            else:
                await self._log(state, "info", f"  Login SUCCESS - navigated to {browser.page.url}")

            # 保存登录态
            cookies = await browser.page.context.cookies()
            self.session_mgr.save_storage_state(state.run_id, {"cookies": cookies})
            await self._log(state, "info", "  Login state saved")
        except Exception as e:
            await self._log(state, "error", f"  Login failed: {e}")

    async def _detect_and_login_v3(self, browser, state: RunState, username: str, password: str):
        """v3 登录 — 使用 BrowserTools.snapshot() 检测登录表单"""
        page = browser.page
        tools = BrowserTools(page)

        await self._log(state, "info", "  [v3] Scanning for login form with snapshot...")

        # 用 v3 snapshot 检测页面
        snapshot_result = await tools.snapshot()
        if not snapshot_result.success:
            await self._log(state, "warn", "  Snapshot failed, trying old method...")
            await self._detect_and_login(browser, state, username, password)
            return

        snapshot = snapshot_result.data
        page_type = snapshot.get("page_type", "")
        await self._log(state, "info", f"  Page type: {page_type}")

        # 查找用户名、密码、提交按钮
        username_ref, password_ref, submit_ref = None, None, None
        for section in snapshot.get("sections", []):
            for el in section.get("elements", []):
                role = el.get("role", "")
                name = el.get("name", "").lower()
                placeholder = el.get("placeholder", "").lower()
                ref = el.get("ref", "")
                tag = el.get("tag", "")
                combined = f"{role} {name} {placeholder}"

                if not password_ref and ("密码" in combined or "password" in combined):
                    password_ref = ref
                    await self._log(state, "info", f"  Found password field: ref={ref}")
                elif not username_ref and tag == "input" and role == "textbox" and "密码" not in combined and "password" not in combined:
                    username_ref = ref
                    await self._log(state, "info", f"  Found username field: ref={ref}")
                if not submit_ref and ("登录" in combined or "login" in combined or "sign in" in combined):
                    if tag == "button" or role == "button":
                        submit_ref = ref
                        await self._log(state, "info", f"  Found submit button: ref={ref}")

        if not username_ref or not password_ref:
            await self._log(state, "info", "  No login form detected via snapshot, skipping login")
            return

        # 用 BrowserTools 填写登录表单
        await self._log(state, "info", f"  Filling username '{username}' into ref={username_ref}")
        r = await tools.fill(username_ref, username)
        if not r.success:
            await self._log(state, "warn", f"  Fill username failed: {r.message}")

        await self._log(state, "info", f"  Filling password into ref={password_ref}")
        r = await tools.fill(password_ref, password)
        if not r.success:
            await self._log(state, "warn", f"  Fill password failed: {r.message}")

        url_before = page.url

        if submit_ref:
            await self._log(state, "info", f"  Clicking login button: ref={submit_ref}")
            r = await tools.click(submit_ref)
            if not r.success:
                await self._log(state, "warn", f"  Click submit failed: {r.message}")
        else:
            await page.keyboard.press("Enter")
            await self._log(state, "info", "  Pressed Enter to submit")

        # 等待跳转
        try:
            await page.wait_for_url(lambda url: url != url_before, timeout=10000)
        except Exception:
            pass
        await asyncio.sleep(1)

        # 验证登录
        url_after = page.url
        still_on_login = "login" in url_after.lower()
        if still_on_login:
            await self._log(state, "warn", "  Still on login page, login may have failed")
        else:
            await self._log(state, "info", f"  Login SUCCESS - navigated to {url_after}")

        # 保存登录态
        cookies = await page.context.cookies()
        self.session_mgr.save_storage_state(state.run_id, {"cookies": cookies})
        await self._log(state, "info", "  Login state saved")

    async def _verify_and_login(self, browser, state: RunState):
        """验证登录状态 — 如果在登录页就重新登录"""
        try:
            # 检查是否有密码框（说明在登录页）
            pwd = browser.page.locator("input[type='password']")
            if await pwd.count() > 0 and await pwd.first.is_visible():
                await self._log(state, "warn", "  Still on login page, re-logging in...")
                username = state.credentials.get("username", "")
                password = state.credentials.get("password", "")
                if username and password:
                    await self._detect_and_login(browser, state, username, password)
                else:
                    await self._log(state, "error", "  No credentials available for re-login")
                return

            # 二次检查：页面文本中是否包含登录关键词
            page_summary = await browser.get_page_summary()
            text = page_summary.get("text_snippet", "").lower()
            login_keywords = ["login", "password", "sign in", "登录", "密码", "用户名"]
            if any(kw in text for kw in login_keywords):
                # 可能是登录页但没有标准密码框
                has_pwd_input = any(
                    (e.tag == "input" and e.attributes.get("type") == "password")
                    for e in await browser.collect_interactive_elements()
                )
                if has_pwd_input:
                    await self._log(state, "warn", "  Login page detected via text, re-logging in...")
                    username = state.credentials.get("username", "")
                    password = state.credentials.get("password", "")
                    if username and password:
                        await self._detect_and_login(browser, state, username, password)
                    return

            await self._log(state, "info", f"  Login verified, current URL: {browser.page.url}")
        except Exception as e:
            await self._log(state, "warn", f"  Login verification error: {e}")

    def _build_element_map(self, exploration: dict) -> dict:
        result = {}
        for page in exploration.get("pages_explored", []):
            module = page.get("module", "")
            elements = page.get("elements", [])
            result[module] = elements
        return result

    async def _execute_all(self, state: RunState, credentials: dict):
        # 复用探索阶段的浏览器（已登录，已导航）
        browser = self._browser
        if not browser:
            await self._log(state, "error", "No browser available for execution")
            return

        # 验证登录状态
        await self._verify_and_login(browser, state)

        try:
            for case in state.cases:
                if case.completeness not in ("complete", "enriched"):
                    continue

                # 停止检查
                if state.stop_requested:
                    await self._log(state, "info", "Stop requested, halting execution")
                    break

                # 暂停检查
                await state.pause_event.wait()

                await self._log(state, "info", f"Executing: {case.title}")
                case.transition_to(CaseStatus.RUNNING)

                # 回放探索记录的操作
                result = await self._replay_exploration(state, case, browser)
                state.case_results.append(result)

                icon = "PASS" if result["status"] == "passed" else "FAIL" if result["status"] == "failed" else "WARN"
                await self._log(state, "info", f"  [{icon}] {case.title}")

        except Exception as e:
            import traceback
            await self._log(state, "error", f"Execution phase error: {e}")
            await self._log(state, "error", traceback.format_exc()[-300:])
        finally:
            await browser.stop()

    async def _replay_exploration(self, state: RunState, case, browser: BrowserController) -> dict:
        """回放探索阶段记录的操作"""
        from backend.engine.explorer.ai_explorer import StepRecord
        result = {"case_id": case.id, "case_title": case.title, "status": "passed", "steps": [], "ai_call_count": 0}

        # 检查 IR 中是否有登录步骤
        has_login_in_ir = False
        if case.id in state.action_irs:
            ir = state.action_irs[case.id]
            for step in ir.steps:
                if step.natural_step and ("登录" in step.natural_step or "用户名" in step.natural_step or "密码" in step.natural_step):
                    has_login_in_ir = True
                    break

        # 先导航回目标页面（探索阶段可能在其他页面）
        try:
            await browser.goto(state.target_url)
            await browser.wait_for_page_ready()
            await asyncio.sleep(2)
        except Exception as e:
            await self._log(state, "warn", f"  Navigation failed: {e}")

        # 只有在没有登录步骤时才验证登录状态
        if not has_login_in_ir:
            await self._verify_and_login(browser, state)
        else:
            await self._log(state, "info", "  IR 包含登录步骤，跳过自动登录")

        # 如果有探索记录，回放操作
        if case.id in state.action_irs:
            # v3: 用 ActionIR 回放（通过规则匹配定位元素）
            ir = state.action_irs[case.id]
            from backend.engine.browser.browser_tool import BrowserTools
            from backend.engine.agent.explorer_agent import ExplorerAgent
            import re
            import json as _json
            tools = BrowserTools(browser.page)
            agent = ExplorerAgent(tools, None, log_callback=lambda level, msg: None, credentials=state.credentials)

            for step in ir.steps:
                if step.status != "passed":
                    continue
                if step.action in ("unknown", "done", "blocked"):
                    continue
                try:
                    # 每步先采集快照，用规则匹配定位元素
                    snap_result = await tools.snapshot()
                    if not snap_result.success:
                        raise Exception(f"快照失败: {snap_result.message}")
                    snapshot_data = snap_result.data

                    # 用规则匹配从自然语言步骤描述中找到目标元素（支持多动作）
                    rule_tcs = agent._try_rule_based_actions(step.natural_step, snapshot_data)
                    if rule_tcs:
                        tool_calls_to_exec = []
                        for tc in rule_tcs:
                            func = tc["function"]
                            fn = func["name"]
                            fa = _json.loads(func["arguments"]) if isinstance(func["arguments"], str) else func["arguments"]
                            tool_calls_to_exec.append((fn, fa))
                            await self._log(state, "info", f"  Replay: {step.natural_step} → 规则匹配 {fn}({fa})")
                    else:
                        tool_calls_to_exec = [(step.action, {"ref": step.target_ref, "value": step.value, "locator": step.locator})]
                        await self._log(state, "info", f"  Replay: {step.natural_step} → IR 回退 {step.action}")

                    for fn, fa in tool_calls_to_exec:
                        if fn == "click":
                            r = await tools.click(ref=fa.get("ref", ""), locator=fa.get("locator"))
                            if not r.success:
                                raise Exception(r.message)
                        elif fn == "fill":
                            r = await tools.fill(ref=fa.get("ref", ""), value=fa.get("value", ""), locator=fa.get("locator"))
                            if not r.success:
                                raise Exception(r.message)
                            try:
                                await browser.page.wait_for_load_state("networkidle", timeout=3000)
                            except Exception:
                                pass
                            await asyncio.sleep(0.5)
                            await tools.snapshot()
                        elif fn == "navigate":
                            await browser.goto(fa.get("url", fa.get("value", "")))
                        elif fn == "hover":
                            r = await tools.hover(ref=fa.get("ref", ""), locator=fa.get("locator"))
                            if not r.success:
                                raise Exception(r.message)
                        elif fn == "select_option":
                            r = await tools.select_option(ref=fa.get("ref", ""), value=fa.get("value", ""), locator=fa.get("locator"))
                            if not r.success:
                                raise Exception(r.message)
                        elif fn == "wait":
                            await asyncio.sleep(int(fa.get("ms", 1000)) / 1000)

                    await asyncio.sleep(0.5)
                    result["steps"].append({"step": step.order, "action": step.action, "status": "passed"})
                except Exception as e:
                    result["steps"].append({"step": step.order, "action": step.action, "status": "failed", "reason": str(e)})
                    result["status"] = "failed"
                    await self._log(state, "warn", f"  Replay failed: {e}")

        elif case.id in state.exploration_results:
            # v2: 用 ExplorationRecording 回放
            exp_result = state.exploration_results[case.id]
            for step_record in exp_result.steps:
                if not step_record.success:
                    continue
                try:
                    action = step_record.ai_action
                    selector = step_record.ai_selector
                    value = step_record.ai_value
                    await self._log(state, "info", f"  Replay: {action} → {selector}")

                    if action == "click":
                        await browser.page.click(selector, timeout=10000)
                    elif action == "fill":
                        await browser.page.click(selector, timeout=5000)
                        await browser.page.fill(selector, "", timeout=5000)
                        await browser.page.type(selector, value, delay=50, timeout=10000)
                    elif action == "select":
                        await browser.page.select_option(selector, value, timeout=10000)
                    elif action == "hover":
                        await browser.page.hover(selector, timeout=10000)
                    elif action == "scroll":
                        await browser.page.evaluate("window.scrollBy(0, 300)")
                    elif action == "wait":
                        await asyncio.sleep(2)

                    await asyncio.sleep(1)
                    result["steps"].append({"step": step_record.step_num, "action": action, "status": "passed"})
                except Exception as e:
                    result["steps"].append({"step": step_record.step_num, "action": action, "status": "failed", "reason": str(e)})
                    result["status"] = "failed"
                    await self._log(state, "warn", f"  Replay failed: {e}")
        else:
            # 没有探索记录，回退到脚本执行
            script = state.scripts.get(case.id)
            if script:
                try:
                    exec(script, {"__builtins__": __builtins__})
                    result["steps"].append({"step": 1, "action": "script", "status": "passed"})
                except Exception as e:
                    result["steps"].append({"step": 1, "action": "script", "status": "failed", "reason": str(e)})
                    result["status"] = "failed"

        # 截图记录
        try:
            screenshot_path = f"test_artifacts/{state.run_id}/exec_{case.id}.png"
            await browser.take_screenshot(screenshot_path)
            result["screenshot"] = screenshot_path
        except Exception:
            pass

        return result

    def _generate_report(self, state: RunState, analysis: dict) -> str:
        gen = ReportGenerator()
        # 将步骤级结果展平为用例级失败详情
        failed_detail, blocked_detail, error_detail, ai_decisions = [], [], [], []
        for r in state.case_results:
            case = next((c for c in state.cases if c.id == r.get("case_id")), None)
            case_title = case.title if case else r.get("case_id", "?")
            case_module = case.module if case else "?"
            for step in r.get("steps", []):
                if step.get("ai_judgment"):
                    ai_decisions.append({
                        "case_id": r.get("case_id", ""), "case_title": case_title,
                        "step": step.get("step", 0), "scenario": step.get("action", ""),
                        "judgment": step["ai_judgment"], "confidence": step.get("ai_confidence", 0),
                        "screenshot": step.get("screenshot", ""), "reasoning": step.get("ai_reasoning", ""),
                    })
                if step.get("status") == "failed":
                    failed_detail.append({
                        "case_id": r.get("case_id"), "case_title": case_title,
                        "module": case_module, "step": step.get("step"),
                        "action": step.get("action", ""), "reason": step.get("reason", ""),
                        "ai_judgment": step.get("ai_judgment", ""), "ai_confidence": step.get("ai_confidence", 0),
                        "screenshot": step.get("screenshot", ""), "ai_reasoning": step.get("ai_reasoning", ""),
                    })
                elif step.get("status") == "blocked":
                    blocked_detail.append({"case_title": case_title, "reason": step.get("reason", "")})
                elif step.get("status") == "error":
                    error_detail.append({"case_title": case_title, "reason": step.get("reason", "")})

        run_data = {
            "run_id": state.run_id,
            "target_url": state.target_url,
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(state.start_time or time.time())),
            "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(state.end_time or time.time())),
            "summary": state.summary(),
            "module_stats": self._build_module_stats(state),
            "failed_cases": failed_detail,
            "blocked_cases": blocked_detail,
            "error_cases": error_detail,
            "ai_decisions": ai_decisions,
            "ai_call_count": state.ai_call_count,
            "exploration_screenshots": self._collect_screenshots(state.exploration_result),
            "env_info": {"playwright": "1.52", "browser": "Chromium", "ai_model": self.config.ai_model},
        }
        md_report = gen.generate_markdown(run_data)
        json_report = gen.generate_json(run_data)

        import os
        artifacts_dir = f"test_artifacts/{state.run_id}"
        os.makedirs(artifacts_dir, exist_ok=True)
        with open(f"{artifacts_dir}/report.md", "w", encoding="utf-8") as f:
            f.write(md_report)
        with open(f"{artifacts_dir}/report.json", "w", encoding="utf-8") as f:
            f.write(json_report)

        return md_report

    def _collect_screenshots(self, exploration: dict) -> list[dict]:
        screenshots = []
        for page in exploration.get("pages_explored", []):
            if page.get("screenshot"):
                screenshots.append({"page": page.get("module", ""), "path": page["screenshot"]})
        return screenshots

    def _build_module_stats(self, state: RunState) -> list[dict]:
        stats = {}
        for r in state.case_results:
            case = next((c for c in state.cases if c.id == r.get("case_id")), None)
            if not case:
                continue
            m = case.module
            if m not in stats:
                stats[m] = {"module": m, "total": 0, "passed": 0, "failed": 0, "blocked": 0, "error": 0}
            stats[m]["total"] += 1
            status = r.get("status", "error")
            if status in stats[m]:
                stats[m][status] += 1
        return list(stats.values())

    def _persist_results(self, state: RunState):
        db = get_db()
        db.execute(
            """INSERT OR REPLACE INTO test_runs (id, suite_id, target_url, credentials, status, started_at, finished_at, config)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (state.run_id, state.suite_id, state.target_url, json.dumps(state.credentials),
             "completed",
             time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(state.start_time)),
             time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(state.end_time)),
             "{}")
        )
        for r in state.case_results:
            db.execute(
                """INSERT OR REPLACE INTO case_results (id, run_id, case_id, status, ai_judgment, ai_confidence, retry_count, duration_ms)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (str(uuid.uuid4()), state.run_id, r.get("case_id", ""), r.get("status", ""),
                 r.get("ai_judgment", ""), r.get("ai_confidence", 0), 0, 0)
            )
        db.commit()
        db.close()
