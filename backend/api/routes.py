import json
import uuid
import asyncio
import time
from fastapi import APIRouter, UploadFile, File, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from backend.engine.parser.csv_parser import CSVParser
from backend.engine.parser.enricher import CaseEnricher
from backend.config import Config
from backend.storage.database import get_db
from backend.engine.orchestrator import Orchestrator, RunState
from backend.engine.executor.executor import SmartExecutor

router = APIRouter()

# 全局 WebSocket 连接管理
_active_ws: dict[str, list[WebSocket]] = {}
# 已完成/进行中的 run 状态
_run_states: dict[str, RunState] = {}


@router.get("/health")
async def health():
    return {"status": "ok", "version": "0.1.0"}


@router.get("/config")
async def get_config():
    cfg = Config()
    return {
        "ai_provider": cfg.ai_provider,
        "ai_model": cfg.ai_model,
        "ai_base_url": cfg.ai_base_url,
        "browser_headless": cfg.browser_headless
    }


@router.patch("/config")
async def update_config(updates: dict):
    return {"status": "updated", "changes": list(updates.keys())}


@router.get("/runs")
async def list_runs():
    """获取历史运行记录"""
    db = get_db()
    rows = db.execute("SELECT * FROM test_runs ORDER BY started_at DESC LIMIT 50").fetchall()
    db.close()
    result = []
    for r in rows:
        d = dict(r)
        # 获取该 run 的用例统计
        db2 = get_db()
        stats = db2.execute(
            "SELECT status, COUNT(*) as cnt FROM case_results WHERE run_id = ? GROUP BY status",
            (d["id"],)
        ).fetchall()
        db2.close()
        summary = {s["status"]: s["cnt"] for s in stats}
        d["summary"] = {
            "total": sum(summary.values()),
            "passed": summary.get("passed", 0),
            "failed": summary.get("failed", 0),
            "blocked": summary.get("blocked", 0),
            "error": summary.get("error", 0),
        }
        result.append(d)
    return result


@router.get("/runs/{run_id}")
async def get_run_detail(run_id: str):
    """获取单次运行详情"""
    db = get_db()
    row = db.execute("SELECT * FROM test_runs WHERE id = ?", (run_id,)).fetchone()
    if not row:
        db.close()
        raise HTTPException(404, "Run not found")
    d = dict(row)
    results = db.execute("SELECT * FROM case_results WHERE run_id = ?", (run_id,)).fetchall()
    d["case_results"] = [dict(r) for r in results]
    db.close()
    return d


@router.delete("/runs/{run_id}")
async def delete_run(run_id: str):
    """删除运行记录"""
    db = get_db()
    db.execute("DELETE FROM case_results WHERE run_id = ?", (run_id,))
    db.execute("DELETE FROM test_runs WHERE id = ?", (run_id,))
    db.commit()
    db.close()
    return {"status": "deleted"}


@router.post("/cases/upload")
async def upload_cases(file: UploadFile = File(...)):
    if not file.filename.endswith(".csv"):
        raise HTTPException(400, "Only CSV files are accepted")

    content = await file.read()
    parser = CSVParser()
    cases = parser.parse(content)

    if not cases:
        raise HTTPException(400, "No valid test cases found in CSV")

    suite_id = str(uuid.uuid4())[:8]
    db = get_db()
    db.execute("INSERT INTO test_suites (id, name, file_name, case_count) VALUES (?, ?, ?, ?)",
               (suite_id, file.filename.rsplit(".", 1)[0], file.filename, len(cases)))
    for case in cases:
        case.suite_id = suite_id
        db.execute(
            """INSERT INTO test_cases (id, suite_id, module, title, preconditions, steps, expected,
               keywords, priority, test_type, stage, status, completeness)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (case.id, suite_id, case.module, case.title, case.preconditions,
             json.dumps([{"order": s.order, "action": s.action} for s in case.steps], ensure_ascii=False),
             case.expected, case.keywords, case.priority, case.test_type, case.stage,
             case.status.value, case.completeness)
        )
    db.commit()
    db.close()

    enricher = CaseEnricher()
    enrichment = enricher.batch_evaluate(cases)

    return {
        "suite_id": suite_id,
        "case_count": len(cases),
        "enrichment": {
            "ready": len(enrichment["ready"]),
            "needs_enrichment": len(enrichment["needs_enrichment"]),
            "incomplete_cases": enrichment["needs_enrichment"]
        }
    }


@router.get("/cases/{suite_id}")
async def get_cases(suite_id: str):
    db = get_db()
    rows = db.execute("SELECT * FROM test_cases WHERE suite_id = ?", (suite_id,)).fetchall()
    db.close()
    return [dict(r) for r in rows]


@router.delete("/cases/{suite_id}")
async def delete_cases(suite_id: str):
    db = get_db()
    db.execute("DELETE FROM test_cases WHERE suite_id = ?", (suite_id,))
    db.execute("DELETE FROM test_suites WHERE id = ?", (suite_id,))
    db.commit()
    db.close()
    return {"status": "deleted"}


@router.get("/healing")
async def get_healing_records():
    from backend.engine.executor.healing import HealingStore
    store = HealingStore()
    return store.list_all()


@router.delete("/healing/{record_id}")
async def delete_healing_record(record_id: str):
    db = get_db()
    db.execute("DELETE FROM healing_records WHERE id = ?", (record_id,))
    db.commit()
    db.close()
    return {"status": "deleted"}


@router.post("/healing/clear")
async def clear_healing():
    from backend.engine.executor.healing import HealingStore
    store = HealingStore()
    store.clear()
    return {"status": "cleared"}


# ========== 测试执行 + WebSocket 日志 ==========

async def _websocket_log(run_id: str, message: dict):
    """将日志推送到所有连接的 WebSocket"""
    if run_id not in _active_ws:
        return
    dead = []
    for ws in _active_ws[run_id]:
        try:
            await ws.send_text(json.dumps(message))
        except Exception:
            dead.append(ws)
    for ws in dead:
        _active_ws[run_id].remove(ws)


@router.websocket("/tests/{run_id}/ws")
async def test_logs_websocket(ws: WebSocket, run_id: str):
    await ws.accept()
    if run_id not in _active_ws:
        _active_ws[run_id] = []
    _active_ws[run_id].append(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        _active_ws[run_id].remove(ws)


# ========== 分步执行 API ==========

@router.post("/tests/explore")
async def start_exploration(payload: dict):
    """Step 1: 仅探索 — 打开浏览器、收集元素"""
    suite_id = payload.get("suite_id")
    target_url = payload.get("target_url")
    credentials = payload.get("credentials", {})

    if not suite_id or not target_url:
        raise HTTPException(400, "suite_id and target_url required")

    cfg = Config()
    orch = Orchestrator(config=cfg, log_callback=_websocket_log)
    run_id = str(uuid.uuid4())[:8]
    state = RunState(run_id=run_id, suite_id=suite_id, target_url=target_url, credentials=credentials, status="exploring", start_time=time.time())
    _run_states[run_id] = state

    async def _run():
        try:
            exploration = await orch.explore_only(state, target_url, credentials)
            state.exploration_result = exploration
            if exploration.get("error"):
                state.status = "failed"
            else:
                state.status = "explored"
                state.log("info", f"Exploration complete: {exploration.get('total_elements', 0)} elements found")
        except Exception as e:
            state.status = "failed"
            state.log("error", f"Exploration failed: {e}")

    asyncio.create_task(_run())
    return {"run_id": run_id, "status": "exploring"}


@router.post("/tests/generate")
async def start_generation(payload: dict):
    """Step 2: 生成脚本 — 基于探索结果"""
    run_id = payload.get("run_id")
    state = _run_states.get(run_id)
    if not state:
        raise HTTPException(404, "Run not found")

    state.status = "generating"
    cfg = Config()
    orch = Orchestrator(config=cfg, log_callback=_websocket_log)

    async def _run():
        try:
            for case in state.cases:
                # 优先从探索记录生成（新架构）
                if case.id in state.exploration_results:
                    exp_result = state.exploration_results[case.id]
                    if exp_result.status == "explored":
                        script = orch.generator.generate_from_exploration(case, exp_result)
                        if orch.generator.precheck(script)["valid"]:
                            state.scripts[case.id] = script
                            state.log("info", f"Script from exploration: {case.title}")
                            continue

                # 回退到旧的模板生成
                if case.completeness not in ("complete", "enriched"):
                    continue
                element_map = orch._build_element_map(state.exploration_result)
                script = orch.generator.build_script_template(case, element_map)
                if orch.generator.precheck(script)["valid"]:
                    state.scripts[case.id] = script
                    state.log("info", f"Script from template: {case.title}")

            state.status = "generated"
            state.log("info", f"Done: {len(state.scripts)} scripts ready")
        except Exception as e:
            state.status = "failed"
            state.log("error", f"Generation failed: {e}")

    asyncio.create_task(_run())
    return {"run_id": run_id, "status": "generating"}


@router.post("/tests/execute")
async def start_execution(payload: dict):
    """Step 3: 执行脚本"""
    run_id = payload.get("run_id")
    state = _run_states.get(run_id)
    if not state:
        raise HTTPException(404, "Run not found")

    state.status = "running"
    cfg = Config()
    orch = Orchestrator(config=cfg, log_callback=_websocket_log)

    async def _run():
        try:
            await orch.execute_only(state)
            executor = SmartExecutor()
            analysis = executor.classify_results(state.case_results)
            orch._generate_report(state, analysis)
            orch._persist_results(state)
            state.status = "completed"
            state.end_time = time.time()
            state.log("info", f"Done: {state.summary()['passed']}P/{state.summary()['failed']}F")
        except Exception as e:
            state.status = "failed"
            state.log("error", f"Execution failed: {e}")

    asyncio.create_task(_run())
    return {"run_id": run_id, "status": "running"}


@router.post("/tests/run")
async def run_all(payload: dict):
    """一键执行全部（兼容旧接口）"""
    suite_id = payload.get("suite_id")
    target_url = payload.get("target_url")
    credentials = payload.get("credentials", {})

    cfg = Config()
    orch = Orchestrator(config=cfg, log_callback=_websocket_log)
    run_id = str(uuid.uuid4())[:8]
    state = RunState(run_id=run_id, suite_id=suite_id, target_url=target_url, credentials=credentials, status="running")
    _run_states[run_id] = state

    async def _run():
        try:
            await orch.run(suite_id, target_url, credentials, state=state)
        except Exception as e:
            state.status = "failed"
            state.log("error", f"Run failed: {e}")

    asyncio.create_task(_run())
    return {"run_id": run_id, "status": "started"}


@router.get("/tests/{run_id}/status")
async def get_test_status(run_id: str):
    state = _run_states.get(run_id)
    if not state:
        return {"status": "pending", "message": "Run not started or not found"}

    summary = state.summary()
    return {
        "run_id": run_id,
        "status": state.status,
        "summary": summary,
        "logs_count": len(state.logs),
        "current_case_index": state.current_case_index,
        "total_cases": len(state.cases),
    }


@router.post("/tests/{run_id}/pause")
async def pause_test(run_id: str):
    state = _run_states.get(run_id)
    if not state:
        raise HTTPException(404, "Run not found")
    if hasattr(state.pause_event, 'clear'):
        state.pause_event.clear()
    state.status = "paused"
    return {"status": "paused"}


@router.post("/tests/{run_id}/resume")
async def resume_test(run_id: str):
    state = _run_states.get(run_id)
    if not state:
        raise HTTPException(404, "Run not found")
    if hasattr(state.pause_event, 'set'):
        state.pause_event.set()
    state.status = "running"
    return {"status": "running"}


@router.post("/tests/{run_id}/stop")
async def stop_test(run_id: str):
    state = _run_states.get(run_id)
    if not state:
        raise HTTPException(404, "Run not found")
    state.stop_requested = True
    # 如果在暂停中，也需要解除暂停以便循环能退出
    if hasattr(state.pause_event, 'set'):
        state.pause_event.set()
    return {"status": "stopping"}


@router.get("/tests/{run_id}/scripts")
async def get_scripts(run_id: str):
    """获取生成的脚本列表"""
    state = _run_states.get(run_id)
    if not state:
        raise HTTPException(404, "Run not found")
    return {
        "run_id": run_id,
        "script_count": len(state.scripts),
        "scripts": {case_id: script for case_id, script in state.scripts.items()}
    }


@router.get("/tests/{run_id}/logs")
async def get_test_logs(run_id: str):
    state = _run_states.get(run_id)
    if not state:
        raise HTTPException(404, "Run not found")
    return state.logs


# ========== 用例补全 ==========

@router.post("/cases/{suite_id}/enrich")
async def enrich_cases(suite_id: str, payload: dict):
    """保存用户补全数据到用例步骤中"""
    enrichments = payload.get("enrichments", {})
    db = get_db()
    count = 0
    for case_id, data in enrichments.items():
        row = db.execute("SELECT steps FROM test_cases WHERE id = ? AND suite_id = ?", (case_id, suite_id)).fetchone()
        if row:
            steps = json.loads(row["steps"])
            for step in steps:
                step["enrichment"] = {
                    "target_url": data.get("target_url", ""),
                    "selector_hint": data.get("selector_hint", "")
                }
            db.execute("UPDATE test_cases SET steps = ?, completeness = ? WHERE id = ?",
                       (json.dumps(steps, ensure_ascii=False), "enriched", case_id))
            count += 1
    db.commit()
    db.close()
    return {"status": "saved", "enriched_count": count}


# ========== 报告 ==========

@router.get("/reports/{run_id}")
async def get_report(run_id: str):
    import os
    path = f"test_artifacts/{run_id}/report.md"
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return {"report": f.read()}
    raise HTTPException(404, "Report not found")


@router.get("/reports/{run_id}/json")
async def get_report_json(run_id: str):
    import os
    path = f"test_artifacts/{run_id}/report.json"
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.loads(f.read())
    raise HTTPException(404, "Report not found")


@router.get("/reports/{run_id}/artifacts/{filename}")
async def get_artifact(run_id: str, filename: str):
    import os
    path = f"test_artifacts/{run_id}/{filename}"
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return {"content": f.read()}
    raise HTTPException(404, "Artifact not found")


@router.get("/screenshots/{path:path}")
async def serve_screenshot(path: str):
    """直接提供截图文件"""
    import os
    # 直接路径
    if os.path.exists(path):
        return FileResponse(path, media_type="image/png")
    # 尝试 test_artifacts 下（处理不带 test_artifacts 前缀的路径）
    alt_path = f"test_artifacts/{path}" if not path.startswith("test_artifacts/") else path
    if os.path.exists(alt_path):
        return FileResponse(alt_path, media_type="image/png")
    # 尝试去掉 test_artifacts/ 前缀（处理路径重复的情况）
    if path.startswith("test_artifacts/"):
        stripped = path[len("test_artifacts/"):]
        alt_path2 = f"test_artifacts/{stripped}"
        if os.path.exists(alt_path2):
            return FileResponse(alt_path2, media_type="image/png")
    raise HTTPException(404, f"Screenshot not found: {path}")
