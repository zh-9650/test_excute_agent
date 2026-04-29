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

  const handleRun = async () => {
    if (!url) return;
    setRunning(true);
    setLogs([]);
    setResult(null);
    setReport(null);

    // 1. 启动测试
    const runResp = await fetch(`${API}/tests/run`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        suite_id: suiteId,
        target_url: url,
        credentials: { username, password },
      }),
    });
    const { run_id } = await runResp.json();
    setRunId(run_id);

    // 2. 连接 WebSocket 接收实时日志
    const ws = new WebSocket(`ws://localhost:8765/api/v1/tests/${run_id}/ws`);
    ws.onmessage = (e) => {
      const entry = JSON.parse(e.data);
      setLogs((prev) => [...prev, entry]);
    };

    // 3. 轮询状态直到完成
    const poll = setInterval(async () => {
      const stResp = await fetch(`${API}/tests/${run_id}/status`);
      const st = await stResp.json();
      if (st.status === "completed" || st.status === "failed") {
        clearInterval(poll);
        ws.close();
        setRunning(false);
        setResult(st.summary);

        // 4. 获取报告
        try {
          const rResp = await fetch(`${API}/reports/${run_id}`);
          const rData = await rResp.json();
          setReport(rData.report);
        } catch (e) {
          // 报告尚未生成
        }
      }
    }, 2000);
  };

  return (
    <div style={{ maxWidth: 800, margin: "40px auto", fontFamily: "system-ui" }}>
      <button onClick={onBack} style={{ marginBottom: 16, background: "none", border: "none", color: "#2563eb", cursor: "pointer" }}>
        &larr; 返回
      </button>

      <h1>🚀 执行测试</h1>
      <p style={{ color: "#666" }}>用例集: {suiteId}</p>

      {/* 表单 */}
      <div style={{ background: "#f9f9f9", padding: 20, borderRadius: 8, marginBottom: 20 }}>
        <label style={{ display: "block", marginBottom: 12 }}>
          测试地址：
          <input type="text" value={url} onChange={e => setUrl(e.target.value)}
            placeholder="https://example.com" disabled={running}
            style={{ width: "100%", padding: "8px 12px", marginTop: 4, borderRadius: 6, border: "1px solid #d1d5db" }} />
        </label>
        <div style={{ display: "flex", gap: 12 }}>
          <label style={{ flex: 1 }}>
            账号：
            <input type="text" value={username} onChange={e => setUsername(e.target.value)}
              placeholder="admin" disabled={running}
              style={{ width: "100%", padding: "8px 12px", marginTop: 4, borderRadius: 6, border: "1px solid #d1d5db" }} />
          </label>
          <label style={{ flex: 1 }}>
            密码：
            <input type="password" value={password} onChange={e => setPassword(e.target.value)}
              placeholder="****" disabled={running}
              style={{ width: "100%", padding: "8px 12px", marginTop: 4, borderRadius: 6, border: "1px solid #d1d5db" }} />
          </label>
        </div>
        <button onClick={handleRun} disabled={running || !url}
          style={{ marginTop: 16, padding: "10px 24px", background: running ? "#9ca3af" : "#2563eb", color: "#fff",
            border: "none", borderRadius: 6, cursor: running ? "not-allowed" : "pointer", fontSize: 16 }}>
          {running ? "⏳ 执行中..." : "▶ 开始执行"}
        </button>
      </div>

      {/* 实时日志 */}
      {logs.length > 0 && (
        <div style={{ background: "#1e1e1e", color: "#d4d4d4", padding: 16, borderRadius: 8, marginBottom: 20,
          maxHeight: 300, overflow: "auto", fontFamily: "monospace", fontSize: 13 }}>
          {logs.map((l, i) => (
            <div key={i} style={{ lineHeight: 1.8 }}>
              <span style={{ color: l.level === "error" ? "#f87171" : l.level === "warn" ? "#fbbf24" : l.level === "ai" ? "#93c5fd" : "#6ee7b7" }}>
                [{l.level === "ai" ? "🤖 AI" : l.level.toUpperCase()}]
              </span>{" "}
              {l.msg}
            </div>
          ))}
          {running && <div style={{ color: "#6ee7b7" }}>⏳ 执行中...</div>}
        </div>
      )}

      {/* 结果摘要 */}
      {result && (
        <div style={{ background: result.failed > 0 ? "#fef2f2" : "#f0fdf4", padding: 20, borderRadius: 8, marginBottom: 20 }}>
          <h3>📊 执行结果</h3>
          <div style={{ display: "flex", gap: 24, fontSize: 18 }}>
            <span>✅ {result.passed} 通过</span>
            <span>❌ {result.failed} 失败</span>
            <span>🚫 {result.blocked} 阻塞</span>
            <span>⚠️ {result.error} 错误</span>
          </div>
        </div>
      )}

      {/* 报告 */}
      {report && (
        <div style={{ background: "#fff", padding: 16, borderRadius: 8, border: "1px solid #e5e7eb" }}>
          <h3>📋 测试报告</h3>
          <pre style={{ whiteSpace: "pre-wrap", fontSize: 13, lineHeight: 1.7, overflow: "auto", maxHeight: 500 }}>
            {report}
          </pre>
        </div>
      )}
    </div>
  );
}
