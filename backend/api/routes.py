import json
import uuid
import asyncio
from fastapi import APIRouter, UploadFile, File, HTTPException, WebSocket, WebSocketDisconnect, BackgroundTasks
from backend.engine.parser.csv_parser import CSVParser
from backend.engine.parser.enricher import CaseEnricher
from backend.config import Config
from backend.storage.database import get_db
from backend.engine.orchestrator import Orchestrator, RunState

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


@router.post("/tests/run")
async def run_tests(payload: dict):
    """启动测试执行（异步后台任务）"""
    suite_id = payload.get("suite_id")
    target_url = payload.get("target_url")
    credentials = payload.get("credentials", {})
    enrichments = payload.get("enrichments", {})

    if not suite_id or not target_url:
        raise HTTPException(400, "suite_id and target_url are required")

    cfg = Config()
    cfg.browser_headless = True  # 服务端执行强制无头模式
    orchestrator = Orchestrator(config=cfg, log_callback=_websocket_log)

    run_id = str(uuid.uuid4())[:8]

    # 先占位，让 status API 能立即返回
    _run_states[run_id] = RunState(run_id=run_id, suite_id=suite_id, target_url=target_url, credentials=credentials, status="running")

    async def _run():
        try:
            state = await orchestrator.run(suite_id, target_url, credentials, enrichments)
            _run_states[run_id] = state
        except Exception as e:
            import traceback
            err_state = RunState(run_id=run_id, suite_id=suite_id, target_url=target_url, credentials=credentials, status="failed")
            err_state.log("error", f"执行异常: {e}\n{traceback.format_exc()[:500]}")
            _run_states[run_id] = err_state
            if run_id in _active_ws:
                for ws in _active_ws[run_id]:
                    try:
                        await ws.send_text(json.dumps({"ts": 0, "level": "error", "msg": f"执行异常: {e}"}))
                    except Exception:
                        pass

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
    """保存用户补全数据"""
    enrichments = payload.get("enrichments", {})
    db = get_db()
    enricher = CaseEnricher()
    count = 0
    for case_id, data in enrichments.items():
        row = db.execute("SELECT * FROM test_cases WHERE id = ? AND suite_id = ?", (case_id, suite_id)).fetchone()
        if row:
            db.execute("UPDATE test_cases SET completeness = ? WHERE id = ?", ("enriched", case_id))
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
