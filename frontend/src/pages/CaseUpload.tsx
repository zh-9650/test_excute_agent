import { useState } from "react";
import { uploadCases } from "../api";

export default function CaseUpload() {
  const [file, setFile] = useState<File | null>(null);
  const [result, setResult] = useState<any>(null);
  const [loading, setLoading] = useState(false);

  const handleUpload = async () => {
    if (!file) return;
    setLoading(true);
    try {
      const data = await uploadCases(file);
      setResult(data);
    } catch (e: any) {
      setResult({ error: e.message });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ maxWidth: 700, margin: "40px auto" }}>
      <h1>AI 自动化测试平台</h1>
      <div
        style={{
          border: "2px dashed #ccc",
          padding: 30,
          borderRadius: 8,
          marginBottom: 20,
        }}
      >
        <input
          type="file"
          accept=".csv"
          onChange={(e) => setFile(e.target.files?.[0] || null)}
        />
        <button
          onClick={handleUpload}
          disabled={!file || loading}
          style={{ marginLeft: 12 }}
        >
          {loading ? "上传中..." : "上传用例"}
        </button>
      </div>
      {result && (
        <div
          style={{
            background: "#f9f9f9",
            padding: 16,
            borderRadius: 8,
          }}
        >
          {result.error ? (
            <p style={{ color: "red" }}>错误: {result.error}</p>
          ) : (
            <>
              <p>
                用例集 ID: <b>{result.suite_id}</b>
              </p>
              <p>
                用例数: <b>{result.case_count}</b>
              </p>
              <p>可直接生成脚本: {result.enrichment?.ready || 0}</p>
              <p>需要补全: {result.enrichment?.needs_enrichment || 0}</p>
              {result.enrichment?.incomplete_cases?.length > 0 && (
                <details>
                  <summary>待补全用例</summary>
                  {result.enrichment.incomplete_cases.map(
                    (c: any, i: number) => (
                      <div
                        key={i}
                        style={{
                          margin: "8px 0",
                          padding: 8,
                          background: "#fff",
                          borderRadius: 4,
                        }}
                      >
                        <strong>{c.case_title}</strong>
                        <p>模块: {c.module}</p>
                        <p>步骤: {c.steps?.join(", ")}</p>
                      </div>
                    )
                  )}
                </details>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}
