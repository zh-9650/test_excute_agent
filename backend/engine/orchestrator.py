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
            await browser.goto(state.target_url)
            await browser.wait_for_page_ready()

            executor_log = lambda msg: self._log(state, "ai", msg)
            executor = SmartExecutor(browser=browser, ai=self.config.create_provider() if self.config.ai_api_key else None, log_callback=executor_log)

            for case in state.cases:
                if case.id not in state.scripts and case.completeness not in ("complete", "enriched"):
                    continue

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
        page_summary = await browser.get_page_summary()
        text = page_summary.get("text_snippet", "")

        login_keywords = ["login", "password", "username", "sign in"]
        is_login_page = any(kw in text.lower() for kw in login_keywords)

        if not is_login_page:
            await self._log(state, "info", "  No login form detected, skipping login")
            return

        await self._log(state, "info", "  Login form detected, collecting elements...")
        elements = await browser.collect_interactive_elements()

        username_sel, password_sel, submit_sel = None, None, None
        for el in elements:
            attrs = f"{el.tag} {el.text} {el.aria_label} {' '.join(el.classes)}".lower()
            if not username_sel and any(k in attrs for k in ["username", "email", "account"]):
                username_sel = el.selector
            if not password_sel and el.tag == "input" and "password" in attrs:
                password_sel = el.selector
            if not submit_sel and any(k in attrs for k in ["login", "sign", "submit"]):
                submit_sel = el.selector

        if not all([username_sel, password_sel, submit_sel]) and self.config.ai_api_key:
            await self._log(state, "ai", "  Using AI to identify login form...")
            try:
                ai = self.config.create_provider()
                elem_desc = [{"tag": e.tag, "text": e.text[:50], "selector": e.selector} for e in elements[:30]]
                judgment = await ai.analyze(
                    system_prompt="You are a test engineer. Identify login form elements. Return JSON: {found: bool, username_selector: str, password_selector: str, submit_selector: str, reasoning: str}",
                    user_prompt=f"Elements: {json.dumps(elem_desc, ensure_ascii=False)}"
                )
                if judgment.action.get("username_selector"):
                    username_sel = judgment.action["username_selector"]
                if judgment.action.get("password_selector"):
                    password_sel = judgment.action["password_selector"]
                if judgment.action.get("submit_selector"):
                    submit_sel = judgment.action["submit_selector"]
            except Exception as e:
                await self._log(state, "warn", f"  AI login detection failed: {e}")

        if username_sel and password_sel:
            await self._log(state, "info", f"  Filling username: {username_sel}")
            try:
                await browser.page.fill(username_sel, username)
                await self._log(state, "info", f"  Filling password: {password_sel}")
                await browser.page.fill(password_sel, password)
                if submit_sel:
                    await self._log(state, "info", f"  Clicking login: {submit_sel}")
                    await browser.page.click(submit_sel)
                    await browser.wait_for_page_ready(strategy="domcontentloaded")
                    await self._log(state, "info", "  Login completed")
                else:
                    await browser.page.keyboard.press("Enter")
                    await self._log(state, "info", "  Pressed Enter to submit")
            except Exception as e:
                await self._log(state, "error", f"  Login failed: {e}")
        else:
            await self._log(state, "warn", "  Could not identify login form elements, skipping login")

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
            executor = SmartExecutor(browser=browser, ai=self.config.create_provider() if self.config.ai_api_key else None, log_callback=executor_log)

            for case in state.cases:
                if case.completeness not in ("complete", "enriched"):
                    continue

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
        run_data = {
            "run_id": state.run_id,
            "target_url": state.target_url,
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(state.start_time)),
            "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(state.end_time)),
            "summary": state.summary(),
            "module_stats": self._build_module_stats(state),
            "failed_cases": [r for r in state.case_results if r.get("status") == "failed"],
            "blocked_cases": [r for r in state.case_results if r.get("status") == "blocked"],
            "error_cases": [r for r in state.case_results if r.get("status") == "error"],
            "ai_decisions": [r for r in state.case_results if r.get("ai_judgment")],
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
