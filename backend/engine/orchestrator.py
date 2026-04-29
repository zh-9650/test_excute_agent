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
from backend.engine.generator.data_factory import TestDataFactory
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
    status: str = "pending"  # pending | exploring | generating | running | analyzing | completed | failed
    logs: list[dict] = field(default_factory=list)
    cases: list[TestCase] = field(default_factory=list)
    case_results: list[dict] = field(default_factory=list)
    exploration_result: dict = field(default_factory=dict)
    scripts: dict[str, str] = field(default_factory=dict)  # case_id -> script
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
    """主流程编排器：协调所有模块完成端到端测试执行"""

    def __init__(self, config, log_callback=None):
        self.config = config
        self.log_callback = log_callback  # async callback for WebSocket broadcast
        self.session_mgr = SessionManager()
        self.generator = ScriptGenerator(ai=config.create_provider() if config.ai_api_key else None)
        self.healing = HealingStore()

    async def _log(self, state: RunState, level: str, msg: str):
        state.log(level, msg)
        if self.log_callback:
            await self.log_callback(state.run_id, {"level": level, "msg": msg, "ts": time.time()})

    async def run(self, suite_id: str, target_url: str, credentials: dict, enrichment_data: dict = None) -> RunState:
        """主入口：执行完整测试流程"""
        run_id = str(uuid.uuid4())[:8]
        state = RunState(run_id=run_id, suite_id=suite_id, target_url=target_url, credentials=credentials)
        state.start_time = time.time()

        await self._log(state, "info", f"=== 测试开始 (run_id={run_id}) ===")
        await self._log(state, "info", f"目标: {target_url}, 用例集: {suite_id}")

        # 1. 加载用例
        state.cases = self._load_cases(suite_id)
        await self._log(state, "info", f"加载 {len(state.cases)} 条用例")

        # 应用用户补全数据
        if enrichment_data:
            await self._log(state, "info", "应用用户补全数据...")
            enricher = CaseEnricher()
            for case in state.cases:
                if case.id in enrichment_data:
                    enricher.apply_enrichment(case, enrichment_data[case.id])

        # 2. 元素探索
        await self._log(state, "info", "--- 阶段1: 元素探索 ---")
        exploration = await self._explore(state, target_url, credentials)
        state.exploration_result = exploration

        # 3. 脚本生成
        await self._log(state, "info", "--- 阶段2: 脚本生成 ---")
        element_map = self._build_element_map(exploration)
        for case in state.cases:
            if case.completeness in ("complete", "enriched"):
                script = self.generator.build_script_template(case, element_map)
                precheck = self.generator.precheck(script)
                if precheck["valid"]:
                    state.scripts[case.id] = script
                else:
                    await self._log(state, "warn", f"脚本预检失败 [{case.title}]: {precheck['errors']}")
            else:
                await self._log(state, "warn", f"跳过未补全用例: {case.title}")

        await self._log(state, "info", f"生成 {len(state.scripts)} 个脚本")

        # 4. 智能执行
        await self._log(state, "info", "--- 阶段3: 智能执行 ---")
        await self._execute_all(state, credentials)

        # 5. 结果分析
        await self._log(state, "info", "--- 阶段4: 结果分析 ---")
        executor = SmartExecutor()
        analysis = executor.classify_results(state.case_results)

        # 6. 生成报告
        await self._log(state, "info", "--- 阶段5: 报告生成 ---")
        report = self._generate_report(state, analysis)

        state.end_time = time.time()
        duration = state.end_time - state.start_time
        await self._log(state, "info", f"=== 测试完成 ({duration:.0f}s) ===")
        await self._log(state, "info", f"通过: {state.summary()['passed']}, 失败: {state.summary()['failed']}, 阻塞: {state.summary()['blocked']}")

        # 持久化
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
            steps = [Step(order=s.get("order", 0), action=s.get("action", "")) for s in steps_data]
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

    async def _explore(self, state: RunState, target_url: str, credentials: dict) -> dict:
        browser = BrowserController(headless=self.config.browser_headless)
        try:
            await self._log(state, "info", "启动浏览器...")
            await browser.start()

            # 会话管理
            session = self.session_mgr.create(target_url, credentials.get("username", ""), credentials.get("password", ""))
            await self._log(state, "info", "执行登录...")
            await browser.goto(target_url)
            await browser.wait_for_page_ready(strategy="domcontentloaded")

            engine = ExplorationEngine(browser=browser, ai=self.config.create_provider() if self.config.ai_api_key else None)
            result = await engine.explore(state.cases, session, target_url)

            report = engine.generate_exploration_report(result)
            await self._log(state, "info", report)

            return {
                "pages_explored": result.pages_explored,
                "pages_skipped": result.pages_skipped,
                "total_elements": result.total_elements,
                "coverage": result.coverage_score,
            }
        except Exception as e:
            await self._log(state, "error", f"探索失败: {e}")
            return {"error": str(e), "pages_explored": [], "pages_skipped": []}
        finally:
            await browser.stop()

    def _build_element_map(self, exploration: dict) -> dict:
        result = {}
        for page in exploration.get("pages_explored", []):
            module = page.get("module", "")
            elements = page.get("elements", [])
            result[module] = elements
        return result

    async def _execute_all(self, state: RunState, credentials: dict):
        ai_provider = self.config.create_provider() if self.config.ai_api_key else None
        browser = BrowserController(headless=self.config.browser_headless)

        try:
            await browser.start()
            await browser.goto(state.target_url)
            await browser.wait_for_page_ready(strategy="domcontentloaded")

            executor_log = lambda msg: self._log(state, "ai", msg)
            executor = SmartExecutor(ai=ai_provider, browser_controller=browser, log_callback=executor_log)

            for case_id, script in state.scripts.items():
                case = next((c for c in state.cases if c.id == case_id), None)
                if not case:
                    continue

                await self._log(state, "info", f"执行: {case.title}")
                case.transition_to(CaseStatus.RUNNING)

                ctx = ExecutionContext(case=case, script=script, session_id="")
                result = await executor.execute_case(ctx)
                state.case_results.append(result)
                state.ai_call_count += ctx.ai_call_count

                status_icon = "✅" if result.get("status") == "passed" else "❌" if result.get("status") == "failed" else "⚠️"
                ai_info = f" [AI: {result.get('ai_judgment', 'N/A')}]" if result.get("ai_judgment") else ""
                await self._log(state, "info", f"  {status_icon} {case.title}{ai_info}")

        except Exception as e:
            await self._log(state, "error", f"执行阶段异常: {e}")
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
             "completed" if state.summary()["failed"] == 0 else "completed",
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
