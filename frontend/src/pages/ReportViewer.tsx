import { useState, useEffect } from "react";
import ReactMarkdown from "react-markdown";

const API = "http://localhost:8765/api/v1";

interface Props { runId: string; onBack: () => void; }

export default function ReportViewer({ runId, onBack }: Props) {
  const [report, setReport] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchReport();
  }, [runId]);

  const fetchReport = async () => {
    setLoading(true);
    try {
      const r = await fetch(`${API}/reports/${runId}`);
      if (r.ok) setReport((await r.json()).report);
    } catch (e) {} finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ maxWidth: 900, margin: "40px auto", fontFamily: "system-ui" }}>
      <button onClick={onBack} style={{ marginBottom: 16, background: "none", border: "none", color: "#2563eb", cursor: "pointer" }}>
        &larr; 返回
      </button>

      {loading ? (
        <p style={{ color: "#666" }}>加载中...</p>
      ) : report ? (
        <div style={{ background: "#fff", padding: 24, borderRadius: 8, border: "1px solid #e5e7eb", lineHeight: 1.8, fontSize: 14 }}>
          <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 16 }}>
            <h2 style={{ margin: 0 }}>测试报告</h2>
            <button onClick={() => {
              const blob = new Blob([report], { type: "text/markdown" });
              const a = document.createElement("a");
              a.href = URL.createObjectURL(blob);
              a.download = `report-${runId}.md`;
              a.click();
            }}
              style={{ padding: "6px 12px", background: "#2563eb", color: "#fff", border: "none", borderRadius: 4, cursor: "pointer" }}>
              下载 .md
            </button>
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
      ) : (
        <p style={{ color: "#666" }}>报告未找到</p>
      )}
    </div>
  );
}
