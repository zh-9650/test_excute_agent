import { useState } from "react";
import CaseUpload from "./pages/CaseUpload";
import ExecuteTest from "./pages/ExecuteTest";

type Page = "upload" | "execute";

export default function App() {
  const [page, setPage] = useState<Page>("upload");
  const [suiteId, setSuiteId] = useState("");

  return page === "upload" ? (
    <CaseUpload
      onStartTest={(id: string) => {
        setSuiteId(id);
        setPage("execute");
      }}
    />
  ) : (
    <ExecuteTest suiteId={suiteId} onBack={() => setPage("upload")} />
  );
}
