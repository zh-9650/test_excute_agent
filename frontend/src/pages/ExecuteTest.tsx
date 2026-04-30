import { useState } from "react";
import ReactMarkdown from "react-markdown";

const API = "http://localhost:8765/api/v1";

interface Props { suiteId: string; onBack: () => void; }

export default function ExecuteTest({ suiteId, onBack }: Props) {
  const [url, setUrl] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [running, setRunning] = useState(false);
  const [runId, setRunId] = useState<string | null>(null);
  const [logs, setLogs] = useState<{ ts: number; level: string; msg: string }[]>([]);
  const [result, setResult] = useState<any>(null);
  const [report, setReport] = useState<string | null>(null);
  const [view, setView] = useState<"logs" | "report">("logs");

  const handleRun = async () => {
    if (!url) return;
    setRunning(true);
    setLogs([]);
    setResult(null);
    setReport(null);

    const runResp = await fetch(`${API}/tests/run`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ suite_id: suiteId, target_url: url, credentials: { username, password } }),
    });
    const { run_id } = await runResp.json();
    setRunId(run_id);

    const ws = new WebSocket(`ws://localhost:8765/api/v1/tests/${run_id}/ws`);
    const wsReady = new Promise<void>((resolve) => {
      ws.onopen = () => resolve();
      ws.onmessage = (e) => setLogs((prev) => [...prev, JSON.parse(e.data)]);
    });
    await wsReady;

    const poll = setInterval(async () => {
      try {
        const stResp = await fetch(`${API}/tests/${run_id}/status`);
        const st = await stResp.json();
        if (st.status === "completed" || st.status === "failed") {
          clearInterval(poll);
          ws.close();
          setRunning(false);
          setResult(st.summary);
          try {
            const rResp = await fetch(`${API}/reports/${run_id}`);
            if (rResp.ok) setReport((await rResp.json()).report);
          } catch (e) {}
        }
      } catch (e) {}
    }, 2000);
  };

  return (
    <div style={{ maxWidth: 900, margin: "40px auto", fontFamily: "system-ui" }}>
      <button onClick={onBack} style={{ marginBottom: 16, background: "none", border: "none", color: "#2563eb", cursor: "pointer" }}>
        &larr; 返回
      </button>

      <h1>执行测试</h1>
      <p style={{ color: "#666" }}>用例集: {suiteId}</p>

      <div style={{ background: "#f9f9f9", padding: 20, borderRadius: 8, marginBottom: 20 }}>
        <label style={{ display: "block", marginBottom: 12 }}>
          测试地址：
          <input type="text" value={url} onChange={(e) => setUrl(e.target.value)}
            placeholder="http://192.168.110.213:8001" disabled={running}
            style={{ width: "100%", padding: "8px 12px", marginTop: 4, borderRadius: 6, border: "1px solid #d1d5db" }} />
        </label>
        <div style={{ display: "flex", gap: 12 }}>
          <label style={{ flex: 1 }}>账号：<input type="text" value={username} onChange={(e) => setUsername(e.target.value)}
            placeholder="zhanghong" disabled={running}
            style={{ width: "100%", padding: "8px 12px", marginTop: 4, borderRadius: 6, border: "1px solid #d1d5db" }} /></label>
          <label style={{ flex: 1 }}>密码：<input type="password" value={password} onChange={(e) => setPassword(e.target.value)}
            placeholder="****" disabled={running}
            style={{ width: "100%", padding: "8px 12px", marginTop: 4, borderRadius: 6, border: "1px solid #d1d5db" }} /></label>
        </div>
        <button onClick={handleRun} disabled={running || !url}
          style={{ marginTop: 16, padding: "10px 24px", background: running ? "#9ca3af" : "#2563eb", color: "#fff", border: "none", borderRadius: 6, cursor: running ? "not-allowed" : "pointer", fontSize: 16 }}>
          {running ? "执行中..." : "开始执行"}
        </button>
      </div>

      {/* 结果摘要 */}
      {result && (
        <div style={{
          background: result.failed > 0 || result.error > 0 ? "#fef2f2" : "#f0fdf4",
          padding: 20, borderRadius: 8, marginBottom: 20,
          border: `2px solid ${result.failed > 0 ? "#fca5a5" : "#86efac"}`
        }}>
          <h3 style={{ margin: 0, marginBottom: 12 }}>执行结果</h3>
          <div style={{ display: "flex", gap: 24, fontSize: 18, flexWrap: "wrap" }}>
            <span>总计 <b>{result.total}</b></span>
            <span style={{ color: "#059669" }}>通过 <b>{result.passed}</b></span>
            <span style={{ color: "#dc2626" }}>失败 <b>{result.failed}</b></span>
            <span style={{ color: "#d97706" }}>阻塞 <b>{result.blocked}</b></span>
            <span style={{ color: "#7c3aed" }}>错误 <b>{result.error}</b></span>
          </div>
          {runId && <p style={{ marginTop: 12, fontSize: 13, color: "#666" }}>报告目录: <code>test_artifacts/{runId}/</code></p>}
        </div>
      )}

      {/* Tab 切换: 日志 / 报告 */}
      {(logs.length > 0 || report) && (
        <div style={{ marginBottom: 16, display: "flex", gap: 8, borderBottom: "2px solid #e5e7eb" }}>
          {(["logs", "report"] as const).map((t) => (
            <button key={t} onClick={() => setView(t)}
              style={{
                padding: "8px 16px", border: "none", background: "none", cursor: "pointer",
                borderBottom: view === t ? "2px solid #2563eb" : "2px solid transparent",
                color: view === t ? "#2563eb" : "#6b7280", fontWeight: view === t ? 600 : 400, marginBottom: -2,
              }}>
              {t === "logs" ? "实时日志" : "测试报告"}
              {t === "logs" && <span style={{ marginLeft: 6, background: "#e5e7eb", borderRadius: 10, padding: "1px 8px", fontSize: 12 }}>{logs.length}</span>}
            </button>
          ))}
        </div>
      )}

      {/* 实时日志 */}
      {view === "logs" && logs.length > 0 && (
        <div style={{ background: "#1e1e1e", color: "#d4d4d4", padding: 16, borderRadius: 8, marginBottom: 20, maxHeight: 400, overflow: "auto", fontFamily: "monospace", fontSize: 13 }}>
          {logs.map((l, i) => (
            <div key={i} style={{ lineHeight: 1.8 }}>
              <span style={{ color: l.level === "error" ? "#f87171" : l.level === "warn" ? "#fbbf24" : l.level === "ai" ? "#93c5fd" : "#6ee7b7" }}>
                [{l.level === "ai" ? "AI" : l.level.toUpperCase()}]
              </span>{" "}
              {l.msg}
            </div>
          ))}
        </div>
      )}

      {/* 报告 (Markdown 渲染) */}
      {view === "report" && report && (
        <div style={{
          background: "#fff", padding: 24, borderRadius: 8, border: "1px solid #e5e7eb",
          lineHeight: 1.8, fontSize: 14,
        }}>
          <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 16 }}>
            <h3 style={{ margin: 0 }}>测试报告</h3>
            <button onClick={() => {
              const blob = new Blob([report], { type: "text/markdown" });
              const a = document.createElement("a");
              a.href = URL.createObjectURL(blob);
              a.download = `report-${runId}.md`; a.click();
            }}
              style={{ padding: "6px 12px", background: "#2563eb", color: "#fff", border: "none", borderRadius: 4, cursor: "pointer" }}>
              下载 .md
            </button>
          </div>
          <ReactMarkdown
            components={{
              img: ({ src, alt }) => (
                <img src={src} alt={alt || ""}
                  style={{ maxWidth: "100%", borderRadius: 4, border: "1px solid #e5e7eb", margin: "8px 0" }} />
              ),
              table: ({ children }) => (
                <table style={{ width: "100%", borderCollapse: "collapse", margin: "12px 0" }}>
                  {children}
                </table>
              ),
              th: ({ children }) => (
                <th style={{ border: "1px solid #d1d5db", padding: "8px 12px", background: "#f9fafb", textAlign: "left" }}>
                  {children}
                </th>
              ),
              td: ({ children }) => (
                <td style={{ border: "1px solid #d1d5db", padding: "8px 12px" }}>{children}</td>
              ),
              h1: ({ children }) => <h1 style={{ fontSize: 24, borderBottom: "2px solid #e5e7eb", paddingBottom: 8 }}>{children}</h1>,
              h2: ({ children }) => <h2 style={{ fontSize: 18, marginTop: 20 }}>{children}</h2>,
              h3: ({ children }) => <h3 style={{ fontSize: 16, marginTop: 16 }}>{children}</h3>,
              code: ({ children }) => (
                <code style={{ background: "#f3f4f6", padding: "2px 6px", borderRadius: 3, fontSize: 13 }}>
                  {children}
                </code>
              ),
              pre: ({ children }) => (
                <pre style={{ background: "#f3f4f6", padding: 12, borderRadius: 4, overflow: "auto", fontSize: 13 }}>
                  {children}
                </pre>
              ),
            }}
          >
            {report}
          </ReactMarkdown>
        </div>
      )}

      {/* 异常终止 */}
      {!result && !running && logs.length > 0 && (
        <div style={{ background: "#fef2f2", padding: 20, borderRadius: 8, border: "1px solid #fca5a5" }}>
          <h3>执行异常终止</h3>
          <pre style={{ background: "#1e1e1e", color: "#f87171", padding: 12, borderRadius: 4 }}>
            {logs[logs.length - 1]?.msg}
          </pre>
        </div>
      )}
    </div>
  );
}
