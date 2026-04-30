import json
import uuid
import time
import asyncio
from dataclasses import dataclass, field
from backend.models.case import TestCase, CaseStatus
from backend.engine.parser.csv_parser import CSVParser
from backend.engine.parser.enricher import CaseEnricher
from backend.engine.explorer.session import SessionManager
from backend.engine.explorer.browser import BrowserController
from backend.engine.explorer.engine import ExplorationEngine
from backend.engine.generator.generator import ScriptGenerator
from backend.engine.executor.executor import SmartExecutor, ExecutionContext
from backend.engine.executor.healing import HealingStore
from backend.engine.reporter.reporter import ReportGenerator
from backend.storage.database import get_db, init_db


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
    scripts: dict[str, str] = field(default_factory=dict)
    start_time: float = 0.0
    end_time: float = 0.0
    ai_call_count: int = 0

    def log(self, level: str, message: str):
        entry = {"ts": time.time(), "level": level, "msg": message}
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

        # Phase 1: Exploration
        state.status = "exploring"
        await self._log(state, "info", "--- Phase 1: Element Exploration ---")
        exploration = await self._explore(state, target_url, credentials)
        state.exploration_result = exploration

        # 如果目标完全不可达，直接终止
        if exploration.get("error"):
            state.status = "failed"
            state.end_time = time.time()
            await self._log(state, "error", f"Target unreachable: {exploration['error']}")
            await self._log(state, "error", "Test aborted - cannot reach target URL")
            self._generate_report(state, {"bugs": [], "script_issues": [], "environment_issues": [{"reason": exploration["error"]}], "case_issues": []})
            return state

        # Phase 2: Script Generation
        state.status = "generating"
        await self._log(state, "info", "--- Phase 2: Script Generation ---")
        element_map = self._build_element_map(exploration)
        for case in state.cases:
            if case.completeness not in ("complete", "enriched"):
                await self._log(state, "warn", f"Skipping incomplete case: {case.title}")
                continue

            script = None
            if self.config.ai_api_key:
                await self._log(state, "ai", f"  [AI] Generating script for: {case.title}")
                script = await self.generator.generate_with_ai(case, element_map)

            if not script:
                script = self.generator.build_script_template(case, element_map)

            precheck = self.generator.precheck(script)
            if precheck["valid"]:
                state.scripts[case.id] = script
            else:
                await self._log(state, "warn", f"Script precheck failed [{case.title}]: {precheck['errors']}")

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
        """仅探索：加载用例 -> 打开浏览器 -> 逐页收集元素 -> 返回元素地图"""
        state.cases = self._load_cases(state.suite_id)
        await self._log(state, "info", f"Loaded {len(state.cases)} test cases")
        state.status = "exploring"
        exploration = await self._explore(state, target_url, credentials)
        state.exploration_result = exploration
        return exploration

    async def execute_only(self, state: RunState):
        """仅执行：逐步调用 Playwright 执行每个用例的步骤"""
        browser = BrowserController(headless=self.config.browser_headless)
        try:
            await browser.start()

            # 恢复登录态
            storage_state = self.session_mgr.load_storage_state(state.run_id)
            if storage_state:
                await self._log(state, "info", "Restoring saved login session...")
                await browser.page.context.add_cookies(storage_state.get("cookies", []))
                await browser.goto(state.target_url)
            else:
                await self._log(state, "info", "No saved session, navigating to target...")
                await browser.goto(state.target_url)
            await browser.wait_for_page_ready()

            executor_log = lambda msg: self._log(state, "ai", msg)
            ai_provider = self.config.create_provider() if self.config.ai_api_key else None
            backup_provider = self.config.create_backup_provider() if self.config.ai_backup_model else None
            executor = SmartExecutor(browser=browser, ai=ai_provider, backup_ai=backup_provider, log_callback=executor_log, target_url=state.target_url)

            for case in state.cases:
                if case.completeness not in ("complete", "enriched"):
                    continue

                # 熔断检查
                if executor.is_melted():
                    await self._log(state, "warn", f"MELTDOWN: {executor.melt_reason()}")
                    await self._log(state, "warn", "Stopping further execution")
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
            session = self.session_mgr.create(target_url, username, password)

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

    async def _detect_and_login(self, browser, state: RunState, username: str, password: str):
        """检测登录表单并自动登录（支持中英文）"""
        await self._log(state, "info", "  Scanning for login form...")
        elements = await browser.collect_interactive_elements()

        # 直接找 input 类型：密码框存在 = 登录页
        has_password_input = any(e.tag == "input" for e in elements)
        if not has_password_input:
            # 也检查页面文本
            page_summary = await browser.get_page_summary()
            text = page_summary.get("text_snippet", "").lower()
            login_keywords = ["login", "password", "sign in", "登 录", "登录", "密码", "用户名", "账 号", "账号"]
            if not any(kw in text for kw in login_keywords):
                await self._log(state, "info", "  No login form detected, skipping login")
                return

        await self._log(state, "info", f"  Login form detected ({len(elements)} elements), identifying fields...")

        # 找输入框：第一个 text/email 类型 = 用户名，password 类型 = 密码
        username_sel, password_sel, submit_sel = None, None, None
        for el in elements:
            attrs = f"{el.tag} {el.text} {el.aria_label} {' '.join(el.classes)}".lower()
            if not username_sel and el.tag == "input":
                # 第一个非密码输入框就是用户名
                if "password" not in attrs:
                    username_sel = el.selector
                    await self._log(state, "info", f"  Found username: {el.selector}")
            if not password_sel and el.tag == "input" and "password" in attrs:
                password_sel = el.selector
                await self._log(state, "info", f"  Found password: {el.selector}")
            if not submit_sel and el.tag == "button":
                txt = (el.text + el.aria_label).lower()
                if any(k in txt for k in ["login", "sign", "submit", "登录", "登 录", "确 认", "确认"]):
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
            # 尝试常见选择器
            username_sel = "input[type='text']" if not username_sel else username_sel
            password_sel = "input[type='password']" if not password_sel else password_sel

        try:
            await self._log(state, "info", f"  Filling username '{username}' into {username_sel}")
            await browser.page.fill(username_sel, username)
            await self._log(state, "info", f"  Filling password into {password_sel}")
            await browser.page.fill(password_sel, password)

            if submit_sel:
                await self._log(state, "info", f"  Clicking login: {submit_sel}")
                await browser.page.click(submit_sel)
            else:
                await browser.page.keyboard.press("Enter")
                await self._log(state, "info", "  Pressed Enter to submit")

            await browser.wait_for_page_ready(strategy="domcontentloaded")
            await self._log(state, "info", "  Login completed")

            # 保存登录态
            cookies = await browser.page.context.cookies()
            self.session_mgr.save_storage_state(state.run_id, {"cookies": cookies})
            await self._log(state, "info", "  Login state saved")
        except Exception as e:
            await self._log(state, "error", f"  Login failed: {e}")

    def _build_element_map(self, exploration: dict) -> dict:
        result = {}
        for page in exploration.get("pages_explored", []):
            module = page.get("module", "")
            elements = page.get("elements", [])
            result[module] = elements
        return result

    async def _execute_all(self, state: RunState, credentials: dict):
        browser = BrowserController(headless=self.config.browser_headless)

        try:
            await browser.start()
            await browser.goto(state.target_url)
            await browser.wait_for_page_ready()

            executor_log = lambda msg: self._log(state, "ai", msg)
            ai_provider = self.config.create_provider() if self.config.ai_api_key else None
            backup_provider = self.config.create_backup_provider() if self.config.ai_backup_model else None
            executor = SmartExecutor(browser=browser, ai=ai_provider, backup_ai=backup_provider, log_callback=executor_log, target_url=state.target_url)

            for case in state.cases:
                if case.completeness not in ("complete", "enriched"):
                    continue

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

        except Exception as e:
            import traceback
            await self._log(state, "error", f"Execution phase error: {e}")
            await self._log(state, "error", traceback.format_exc()[-300:])
        finally:
            await browser.stop()

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
