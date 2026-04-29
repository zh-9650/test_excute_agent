import json
import uuid
from fastapi import APIRouter, UploadFile, File, HTTPException, WebSocket
from backend.engine.parser.csv_parser import CSVParser
from backend.engine.parser.enricher import CaseEnricher
from backend.config import Config
from backend.storage.database import get_db

router = APIRouter()


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
