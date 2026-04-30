import { useState, useRef } from "react";
import ReactMarkdown from "react-markdown";

const API = "http://localhost:8765/api/v1";

interface Props { suiteId: string; onBack: () => void; }

export default function ExecuteTest({ suiteId, onBack }: Props) {
  const [url, setUrl] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [runId, setRunId] = useState<string | null>(null);
  const [step, setStep] = useState<"config" | "exploring" | "explored" | "generating" | "generated" | "running" | "completed" | "failed">("config");
  const [logs, setLogs] = useState<{ ts: number; level: string; msg: string }[]>([]);
  const [result, setResult] = useState<any>(null);
  const [report, setReport] = useState<string | null>(null);
  const [scripts, setScripts] = useState<Record<string, string>>({});
  const [view, setView] = useState<"logs" | "report">("logs");
  const wsRef = useRef<WebSocket | null>(null);

  const addLog = (entry: { ts: number; level: string; msg: string }) => {
    setLogs((prev) => [...prev, entry]);
  };

  const connectWS = async (rid: string) => {
    const ws = new WebSocket(`ws://localhost:8765/api/v1/tests/${rid}/ws`);
    wsRef.current = ws;
    await new Promise<void>((resolve) => {
      ws.onopen = () => resolve();
      ws.onmessage = (e) => addLog(JSON.parse(e.data));
    });
  };

  const pollUntilDone = (rid: string, targetStatus: string[]): Promise<string> => {
    return new Promise((resolve) => {
      const poll = setInterval(async () => {
        try {
          const r = await fetch(`${API}/tests/${rid}/status`);
          const st = await r.json();
          if (targetStatus.includes(st.status)) {
            clearInterval(poll);
            resolve(st.status);
          }
        } catch (e) {}
      }, 1500);
    });
  };

  // Step 1: 探索
  const handleExplore = async () => {
    if (!url) return;
    setStep("exploring");
    setLogs([]);
    setResult(null);
    setReport(null);

    const r = await fetch(`${API}/tests/explore`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ suite_id: suiteId, target_url: url, credentials: { username, password } }),
    });
    const { run_id } = await r.json();
    setRunId(run_id);
    await connectWS(run_id);

    const status = await pollUntilDone(run_id, ["explored", "failed"]);
    wsRef.current?.close();
    if (status === "explored") {
      setStep("explored");
      addLog({ ts: Date.now(), level: "info", msg: "--- Exploration done. You can now generate scripts ---" });
    } else {
      setStep("failed");
    }
  };

  // Step 2: 生成脚本
  const handleGenerate = async () => {
    if (!runId) return;
    setStep("generating");

    const r = await fetch(`${API}/tests/generate`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ run_id: runId }),
    });
    await connectWS(runId);

    const status = await pollUntilDone(runId, ["generated", "failed"]);
    wsRef.current?.close();
    if (status === "generated") {
      setStep("generated");
      addLog({ ts: Date.now(), level: "info", msg: "--- Scripts generated. You can now execute ---" });
    } else {
      setStep("failed");
    }
  };

  // Step 3: 执行
  const handleExecute = async () => {
    if (!runId) return;
    setStep("running");

    const r = await fetch(`${API}/tests/execute`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ run_id: runId }),
    });
    await connectWS(runId);

    const status = await pollUntilDone(runId, ["completed", "failed"]);
    wsRef.current?.close();
    setStep(status as "completed" | "failed");

    // 加载结果
    try {
      const stR = await fetch(`${API}/tests/${runId}/status`);
      const st = await stR.json();
      setResult(st.summary);
    } catch (e) {}
    try {
      const rpR = await fetch(`${API}/reports/${runId}`);
      if (rpR.ok) setReport((await rpR.json()).report);
    } catch (e) {}
  };

  const stepLabels = { config: 0, exploring: 1, explored: 1, generating: 2, generated: 2, running: 3, completed: 3, failed: -1 };

  return (
    <div style={{ maxWidth: 900, margin: "40px auto", fontFamily: "system-ui" }}>
      <button onClick={onBack} style={{ marginBottom: 16, background: "none", border: "none", color: "#2563eb", cursor: "pointer" }}>
        &larr; 返回
      </button>

      <h1>执行测试</h1>
      <p style={{ color: "#666" }}>用例集: {suiteId}</p>

      {/* 步骤指示器 */}
      {step !== "config" && (
        <div style={{ display: "flex", gap: 8, marginBottom: 20, fontSize: 14 }}>
          {[{ key: "explored", label: "1. 探索" }, { key: "generated", label: "2. 生成" }, { key: "completed", label: "3. 执行" }].map((s, i) => {
            const active = ["explored", "generated", "completed"].indexOf(step) >= i || ["exploring", "generating", "running"].indexOf(step) >= i;
            return (
              <span key={i} style={{ padding: "4px 12px", borderRadius: 4, background: active ? "#dbeafe" : "#f3f4f6", color: active ? "#1e40af" : "#9ca3af", fontWeight: active ? 600 : 400 }}>
                {s.label} {active && step === s.key + "ing" ? "(进行中)" : active && step !== s.key + "ing" && i <= ["explored", "generated", "completed"].indexOf(step) ? "✓" : ""}
              </span>
            );
          })}
        </div>
      )}

      {/* 表单 */}
      {step === "config" && (
        <div style={{ background: "#f9f9f9", padding: 20, borderRadius: 8, marginBottom: 20 }}>
          <label style={{ display: "block", marginBottom: 12 }}>
            测试地址：
            <input type="text" value={url} onChange={(e) => setUrl(e.target.value)}
              placeholder="http://192.168.110.213:8001"
              style={{ width: "100%", padding: "8px 12px", marginTop: 4, borderRadius: 6, border: "1px solid #d1d5db" }} />
          </label>
          <div style={{ display: "flex", gap: 12 }}>
            <label style={{ flex: 1 }}>账号：<input type="text" value={username} onChange={(e) => setUsername(e.target.value)}
              placeholder="zhanghong"
              style={{ width: "100%", padding: "8px 12px", marginTop: 4, borderRadius: 6, border: "1px solid #d1d5db" }} /></label>
            <label style={{ flex: 1 }}>密码：<input type="password" value={password} onChange={(e) => setPassword(e.target.value)}
              placeholder="****"
              style={{ width: "100%", padding: "8px 12px", marginTop: 4, borderRadius: 6, border: "1px solid #d1d5db" }} /></label>
          </div>
          <button onClick={handleExplore} disabled={!url}
            style={{ marginTop: 16, padding: "10px 24px", background: "#2563eb", color: "#fff", border: "none", borderRadius: 6, cursor: "pointer", fontSize: 16 }}>
            1. 开始探索
          </button>
        </div>
      )}

      {/* 操作按钮 */}
      {step === "explored" && (
        <div style={{ display: "flex", gap: 12, marginBottom: 16 }}>
          <button onClick={handleGenerate} style={{ padding: "10px 24px", background: "#059669", color: "#fff", border: "none", borderRadius: 6, cursor: "pointer" }}>
            2. 生成脚本
          </button>
          <button onClick={handleExplore} style={{ padding: "10px 24px", background: "#6b7280", color: "#fff", border: "none", borderRadius: 6, cursor: "pointer" }}>
            重新探索
          </button>
        </div>
      )}
      {step === "generated" && (
        <div style={{ display: "flex", gap: 12, marginBottom: 16 }}>
          <button onClick={handleExecute} style={{ padding: "10px 24px", background: "#dc2626", color: "#fff", border: "none", borderRadius: 6, cursor: "pointer", fontSize: 16 }}>
            3. 执行测试
          </button>
          <button onClick={handleGenerate} style={{ padding: "10px 24px", background: "#6b7280", color: "#fff", border: "none", borderRadius: 6, cursor: "pointer" }}>
            重新生成
          </button>
        </div>
      )}
      {step === "failed" && (
        <div style={{ display: "flex", gap: 12, marginBottom: 16 }}>
          <button onClick={() => setStep("config")} style={{ padding: "10px 24px", background: "#6b7280", color: "#fff", border: "none", borderRadius: 6, cursor: "pointer" }}>
            返回重试
          </button>
        </div>
      )}

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
        </div>
      )}

      {/* Tab: 日志 / 报告 */}
      {(logs.length > 0 || report) && (
        <div style={{ marginBottom: 8, display: "flex", gap: 8, borderBottom: "2px solid #e5e7eb" }}>
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

      {/* 日志 */}
      {view === "logs" && logs.length > 0 && (
        <div style={{ background: "#1e1e1e", color: "#d4d4d4", padding: 16, borderRadius: 8, marginBottom: 20, maxHeight: 400, overflow: "auto", fontFamily: "monospace", fontSize: 13 }}>
          {logs.map((l, i) => (
            <div key={i} style={{ lineHeight: 1.8 }}>
              <span style={{ color: l.level === "error" ? "#f87171" : l.level === "warn" ? "#fbbf24" : l.level === "ai" ? "#93c5fd" : "#6ee7b7" }}>
                [{l.level === "ai" ? "AI" : l.level.toUpperCase()}]
              </span>{" "}{l.msg}
            </div>
          ))}
        </div>
      )}

      {/* 报告 */}
      {view === "report" && report && (
        <div style={{ background: "#fff", padding: 24, borderRadius: 8, border: "1px solid #e5e7eb", lineHeight: 1.8, fontSize: 14 }}>
          <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 16 }}>
            <h3 style={{ margin: 0 }}>测试报告</h3>
            <button onClick={() => { const blob = new Blob([report], { type: "text/markdown" }); const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = `report-${runId}.md`; a.click(); }}
              style={{ padding: "6px 12px", background: "#2563eb", color: "#fff", border: "none", borderRadius: 4, cursor: "pointer" }}>下载 .md</button>
          </div>
          <ReactMarkdown
            components={{
              img: ({ src, alt }) => <img src={src} alt={alt || ""} style={{ maxWidth: "100%", borderRadius: 4, border: "1px solid #e5e7eb", margin: "8px 0" }} />,
              table: ({ children }) => <table style={{ width: "100%", borderCollapse: "collapse", margin: "12px 0" }}>{children}</table>,
              th: ({ children }) => <th style={{ border: "1px solid #d1d5db", padding: "8px 12px", background: "#f9fafb", textAlign: "left" }}>{children}</th>,
              td: ({ children }) => <td style={{ border: "1px solid #d1d5db", padding: "8px 12px" }}>{children}</td>,
              h1: ({ children }) => <h1 style={{ fontSize: 24, borderBottom: "2px solid #e5e7eb", paddingBottom: 8 }}>{children}</h1>,
              h2: ({ children }) => <h2 style={{ fontSize: 18, marginTop: 20 }}>{children}</h2>,
              code: ({ children }) => <code style={{ background: "#f3f4f6", padding: "2px 6px", borderRadius: 3, fontSize: 13 }}>{children}</code>,
              pre: ({ children }) => <pre style={{ background: "#f3f4f6", padding: 12, borderRadius: 4, overflow: "auto", fontSize: 13 }}>{children}</pre>,
            }}>
            {report}
          </ReactMarkdown>
        </div>
      )}
    </div>
  );
}
