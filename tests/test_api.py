from fastapi.testclient import TestClient
from backend.main import app

client = TestClient(app)


def test_health_check():
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_get_config():
    resp = client.get("/api/v1/config")
    assert resp.status_code == 200
    data = resp.json()
    assert "ai_provider" in data


def test_upload_cases():
    csv_content = "所属模块,测试点,前置条件,步骤,预期,关键词,优先级,测试类型,适用阶段\n/test,测试1,条件,1. 步骤1,1. 预期,key,1,功能测试,系统测试阶段"
    resp = client.post("/api/v1/cases/upload",
                       files={"file": ("test.csv", csv_content.encode("utf-8"), "text/csv")})
    assert resp.status_code == 200
    data = resp.json()
    assert "suite_id" in data
    assert data["case_count"] == 1


def test_upload_invalid_file():
    resp = client.post("/api/v1/cases/upload",
                       files={"file": ("test.txt", b"not csv", "text/plain")})
    assert resp.status_code == 400


def test_get_cases_after_upload():
    csv_content = "所属模块,测试点,前置条件,步骤,预期,关键词,优先级,测试类型,适用阶段\n/test,测试1,,1. 步骤1,1. 预期,,1,功能测试,系统测试阶段"
    upload_resp = client.post("/api/v1/cases/upload",
                               files={"file": ("test.csv", csv_content.encode("utf-8"), "text/csv")})
    suite_id = upload_resp.json()["suite_id"]
    resp = client.get(f"/api/v1/cases/{suite_id}")
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_delete_cases():
    csv_content = "所属模块,测试点,前置条件,步骤,预期,关键词,优先级,测试类型,适用阶段\n/test,测试1,,1. 步骤1,1. 预期,,1,功能测试,系统测试阶段"
    upload_resp = client.post("/api/v1/cases/upload",
                               files={"file": ("test.csv", csv_content.encode("utf-8"), "text/csv")})
    suite_id = upload_resp.json()["suite_id"]
    resp = client.delete(f"/api/v1/cases/{suite_id}")
    assert resp.status_code == 200


def test_get_healing():
    resp = client.get("/api/v1/healing")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_clear_healing():
    resp = client.post("/api/v1/healing/clear")
    assert resp.status_code == 200


def test_list_runs_empty():
    resp = client.get("/api/v1/runs")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_get_run_not_found():
    resp = client.get("/api/v1/runs/nonexistent")
    assert resp.status_code == 404


def test_pause_resume_stop_not_found():
    assert client.post("/api/v1/tests/nonexistent/pause").status_code == 404
    assert client.post("/api/v1/tests/nonexistent/resume").status_code == 404
    assert client.post("/api/v1/tests/nonexistent/stop").status_code == 404
