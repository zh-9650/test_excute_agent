import { useState } from "react";
import CaseUpload from "./pages/CaseUpload";
import ExecuteTest from "./pages/ExecuteTest";
import RunHistory from "./pages/RunHistory";
import ReportViewer from "./pages/ReportViewer";

type Page = "upload" | "execute" | "history" | "report";

export default function App() {
  const [page, setPage] = useState<Page>("upload");
  const [suiteId, setSuiteId] = useState("");
  const [reportRunId, setReportRunId] = useState("");

  return (
    <div style={{ minHeight: "100vh", background: "#f5f5f5" }}>
      {/* 顶部导航栏 */}
      <nav style={{ background: "#1e293b", padding: "12px 24px", display: "flex", gap: 16, alignItems: "center" }}>
        <span style={{ color: "#fff", fontWeight: 700, fontSize: 16 }}>AI 测试平台</span>
        <button onClick={() => setPage("upload")}
          style={{ background: "none", border: "none", color: page === "upload" ? "#60a5fa" : "#94a3b8", cursor: "pointer", fontSize: 14 }}>
          用例导入
        </button>
        <button onClick={() => setPage("history")}
          style={{ background: "none", border: "none", color: page === "history" ? "#60a5fa" : "#94a3b8", cursor: "pointer", fontSize: 14 }}>
          历史记录
        </button>
      </nav>

      {page === "upload" && (
        <CaseUpload
          onStartTest={(id: string) => {
            setSuiteId(id);
            setPage("execute");
          }}
        />
      )}
      {page === "execute" && (
        <ExecuteTest suiteId={suiteId} onBack={() => setPage("upload")} />
      )}
      {page === "history" && (
        <RunHistory
          onBack={() => setPage("upload")}
          onViewReport={(runId: string) => {
            setReportRunId(runId);
            setPage("report");
          }}
        />
      )}
      {page === "report" && (
        <ReportViewer runId={reportRunId} onBack={() => setPage("history")} />
      )}
    </div>
  );
}
