import { useState } from "react";

const API = "http://localhost:8765/api/v1";

interface Props {
  suiteId: string;
  onBack: () => void;
}

export default function ExecuteTest({ suiteId, onBack }: Props) {
  const [url, setUrl] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [running, setRunning] = useState(false);
  const [runId, setRunId] = useState<string | null>(null);
  const [logs, setLogs] = useState<{ ts: number; level: string; msg: string }[]>([]);
  const [result, setResult] = useState<any>(null);
  const [report, setReport] = useState<string | null>(null);
  const [reportPath, setReportPath] = useState("");

  const handleRun = async () => {
    if (!url) return;
    setRunning(true);
    setLogs([]);
    setResult(null);
    setReport(null);
    setReportPath("");

    const runResp = await fetch(`${API}/tests/run`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ suite_id: suiteId, target_url: url, credentials: { username, password } }),
    });
    const { run_id } = await runResp.json();
    setRunId(run_id);

    // 连接 WebSocket
    const ws = new WebSocket(`ws://localhost:8765/api/v1/tests/${run_id}/ws`);
    const wsReady = new Promise<void>((resolve) => {
      ws.onopen = () => resolve();
      ws.onmessage = (e) => {
        const entry = JSON.parse(e.data);
        setLogs((prev) => [...prev, entry]);
      };
    });
    await wsReady;

    // 轮询状态
    const poll = setInterval(async () => {
      try {
        const stResp = await fetch(`${API}/tests/${run_id}/status`);
        const st = await stResp.json();
        if (st.status === "completed" || st.status === "failed") {
          clearInterval(poll);
          ws.close();
          setRunning(false);
          setResult(st.summary);
          setReportPath(`test_artifacts/${run_id}/`);

          // 获取报告
          try {
            const rResp = await fetch(`${API}/reports/${run_id}`);
            if (rResp.ok) {
              const rData = await rResp.json();
              setReport(rData.report);
            }
          } catch (e) {
            // 报告可能未生成
          }
        }
      } catch (e) {
        // 轮询异常，继续等
      }
    }, 2000);
  };

  const getStatusColor = (s: string) => {
    if (s === "failed") return "#dc2626";
    if (s === "completed") return "#059669";
    return "#6b7280";
  };

  return (
    <div style={{ maxWidth: 800, margin: "40px auto", fontFamily: "system-ui" }}>
      <button onClick={onBack} style={{ marginBottom: 16, background: "none", border: "none", color: "#2563eb", cursor: "pointer" }}>
        &larr; 返回
      </button>

      <h1>执行测试</h1>
      <p style={{ color: "#666" }}>用例集: {suiteId}</p>

      {/* 表单 */}
      <div style={{ background: "#f9f9f9", padding: 20, borderRadius: 8, marginBottom: 20 }}>
        <label style={{ display: "block", marginBottom: 12 }}>
          测试地址：
          <input type="text" value={url} onChange={(e) => setUrl(e.target.value)}
            placeholder="http://192.168.110.213:8001" disabled={running}
            style={{ width: "100%", padding: "8px 12px", marginTop: 4, borderRadius: 6, border: "1px solid #d1d5db" }} />
        </label>
        <div style={{ display: "flex", gap: 12 }}>
          <label style={{ flex: 1 }}>
            账号：
            <input type="text" value={username} onChange={(e) => setUsername(e.target.value)}
              placeholder="zhanghong" disabled={running}
              style={{ width: "100%", padding: "8px 12px", marginTop: 4, borderRadius: 6, border: "1px solid #d1d5db" }} />
          </label>
          <label style={{ flex: 1 }}>
            密码：
            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)}
              placeholder="****" disabled={running}
              style={{ width: "100%", padding: "8px 12px", marginTop: 4, borderRadius: 6, border: "1px solid #d1d5db" }} />
          </label>
        </div>
        <button onClick={handleRun} disabled={running || !url}
          style={{ marginTop: 16, padding: "10px 24px", background: running ? "#9ca3af" : "#2563eb", color: "#fff",
            border: "none", borderRadius: 6, cursor: running ? "not-allowed" : "pointer", fontSize: 16 }}>
          {running ? "执行中..." : "开始执行"}
        </button>
      </div>

      {/* 实时日志 */}
      {logs.length > 0 && (
        <div style={{ background: "#1e1e1e", color: "#d4d4d4", padding: 16, borderRadius: 8, marginBottom: 20,
          maxHeight: 300, overflow: "auto", fontFamily: "monospace", fontSize: 13 }}>
          {logs.map((l, i) => (
            <div key={i} style={{ lineHeight: 1.8 }}>
              <span style={{
                color: l.level === "error" ? "#f87171" : l.level === "warn" ? "#fbbf24" : l.level === "ai" ? "#93c5fd" : "#6ee7b7"
              }}>
                [{l.level === "ai" ? "AI" : l.level.toUpperCase()}]
              </span>{" "}
              {l.msg}
            </div>
          ))}
          {running && <div style={{ color: "#6ee7b7" }}>执行中...</div>}
        </div>
      )}

      {/* 结果摘要 */}
      {result && (
        <div style={{
          background: result.failed > 0 || result.error > 0 ? "#fef2f2" : "#f0fdf4",
          padding: 20, borderRadius: 8, marginBottom: 20, border: `2px solid ${result.failed > 0 ? "#fca5a5" : "#86efac"}`
        }}>
          <h3>执行结果</h3>
          <div style={{ display: "flex", gap: 24, fontSize: 20, flexWrap: "wrap" }}>
            <span>总计: <b>{result.total}</b></span>
            <span style={{ color: "#059669" }}>通过: <b>{result.passed}</b></span>
            <span style={{ color: "#dc2626" }}>失败: <b>{result.failed}</b></span>
            <span style={{ color: "#d97706" }}>阻塞: <b>{result.blocked}</b></span>
            <span style={{ color: "#7c3aed" }}>错误: <b>{result.error}</b></span>
          </div>
          {reportPath && (
            <p style={{ marginTop: 12, fontSize: 13, color: "#666" }}>
              报告目录: <code>{reportPath}</code>
            </p>
          )}
        </div>
      )}

      {/* 报告 */}
      {report && (
        <div style={{ background: "#fff", padding: 16, borderRadius: 8, border: "1px solid #e5e7eb" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
            <h3 style={{ margin: 0 }}>测试报告</h3>
            <button
              onClick={() => {
                const blob = new Blob([report], { type: "text/markdown" });
                const a = document.createElement("a");
                a.href = URL.createObjectURL(blob);
                a.download = `report-${runId}.md`;
                a.click();
              }}
              style={{ padding: "6px 12px", background: "#2563eb", color: "#fff", border: "none", borderRadius: 4, cursor: "pointer" }}
            >
              下载报告
            </button>
          </div>
          <pre style={{ whiteSpace: "pre-wrap", fontSize: 13, lineHeight: 1.7, overflow: "auto", maxHeight: 500, background: "#f9fafb", padding: 12, borderRadius: 4 }}>
            {report}
          </pre>
        </div>
      )}

      {/* 无结果但已完成 */}
      {!result && !running && logs.length > 0 && (
        <div style={{ background: "#fef2f2", padding: 20, borderRadius: 8, border: "1px solid #fca5a5" }}>
          <h3>执行异常终止</h3>
          <p>查看日志了解详情。最后一条:</p>
          <pre style={{ background: "#1e1e1e", color: "#f87171", padding: 12, borderRadius: 4 }}>
            {logs[logs.length - 1]?.msg}
          </pre>
        </div>
      )}
    </div>
  );
}
