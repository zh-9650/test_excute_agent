import { useState, useEffect } from "react";

const API = "http://localhost:8765/api/v1";

interface RunRecord {
  id: string;
  suite_id: string;
  target_url: string;
  status: string;
  started_at: string;
  finished_at: string;
  summary: { total: number; passed: number; failed: number; blocked: number; error: number };
}

interface Props { onBack: () => void; onViewReport: (runId: string) => void; }

export default function RunHistory({ onBack, onViewReport }: Props) {
  const [runs, setRuns] = useState<RunRecord[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchRuns();
  }, []);

  const fetchRuns = async () => {
    setLoading(true);
    try {
      const r = await fetch(`${API}/runs`);
      if (r.ok) setRuns(await r.json());
    } catch (e) {} finally {
      setLoading(false);
    }
  };

  const handleDelete = async (runId: string) => {
    if (!confirm("确定删除此运行记录？")) return;
    await fetch(`${API}/runs/${runId}`, { method: "DELETE" });
    setRuns((prev) => prev.filter((r) => r.id !== runId));
  };

  const statusColor = (status: string) => {
    if (status === "completed") return "#059669";
    if (status === "failed") return "#dc2626";
    return "#d97706";
  };

  return (
    <div style={{ maxWidth: 900, margin: "40px auto", fontFamily: "system-ui" }}>
      <button onClick={onBack} style={{ marginBottom: 16, background: "none", border: "none", color: "#2563eb", cursor: "pointer" }}>
        &larr; 返回
      </button>
      <h1>历史运行记录</h1>

      {loading ? (
        <p style={{ color: "#666" }}>加载中...</p>
      ) : runs.length === 0 ? (
        <p style={{ color: "#666", padding: 40, textAlign: "center" }}>暂无运行记录</p>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {runs.map((run) => (
            <div key={run.id} style={{
              background: "#fff", border: "1px solid #e5e7eb", borderRadius: 8, padding: 16,
              display: "flex", justifyContent: "space-between", alignItems: "center",
            }}>
              <div>
                <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
                  <code style={{ background: "#f3f4f6", padding: "2px 8px", borderRadius: 4, fontSize: 13 }}>{run.id}</code>
                  <span style={{ color: statusColor(run.status), fontWeight: 600, fontSize: 13 }}>{run.status}</span>
                </div>
                <p style={{ margin: 0, fontSize: 14, color: "#374151" }}>{run.target_url}</p>
                <p style={{ margin: 0, fontSize: 12, color: "#9ca3af" }}>
                  {run.started_at ? new Date(run.started_at).toLocaleString() : "N/A"}
                  {run.summary && ` | ${run.summary.total} cases: ${run.summary.passed}P/${run.summary.failed}F`}
                </p>
              </div>
              <div style={{ display: "flex", gap: 8 }}>
                <button onClick={() => onViewReport(run.id)}
                  style={{ padding: "6px 12px", background: "#2563eb", color: "#fff", border: "none", borderRadius: 4, cursor: "pointer", fontSize: 13 }}>
                  查看报告
                </button>
                <button onClick={() => handleDelete(run.id)}
                  style={{ padding: "6px 12px", background: "#f3f4f6", color: "#6b7280", border: "1px solid #d1d5db", borderRadius: 4, cursor: "pointer", fontSize: 13 }}>
                  删除
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
