import { useState } from "react";
import { uploadCases } from "../api";

interface EnrichmentCase {
  case_id: string;
  case_title: string;
  module: string;
  steps: string[];
  template: {
    target_url: string;
    target_url_hint: string;
    selector_hint: string;
    selector_hint_desc: string;
    extra_note: string;
    extra_note_desc: string;
  };
}

export default function CaseUpload() {
  const [file, setFile] = useState<File | null>(null);
  const [result, setResult] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [enrichments, setEnrichments] = useState<
    Record<string, { target_url: string; selector_hint: string; extra_note: string }>
  >({});
  const [step, setStep] = useState<"upload" | "review" | "complete">("upload");

  const handleUpload = async () => {
    if (!file) return;
    setLoading(true);
    try {
      const data = await uploadCases(file);
      setResult(data);
      setStep("review");
    } catch (e: any) {
      setResult({ error: e.message });
    } finally {
      setLoading(false);
    }
  };

  const handleEnrich = (caseId: string, field: string, value: string) => {
    setEnrichments((prev) => ({
      ...prev,
      [caseId]: { ...(prev[caseId] || {}), [field]: value },
    }));
  };

  const handleSubmitEnrichments = () => {
    const filled = Object.entries(enrichments).filter(
      ([, v]) => v.target_url || v.selector_hint
    ).length;
    alert(`已保存 ${filled} 条补全信息（后端 API 待接入完整流程）`);
    setStep("complete");
  };

  const handleReset = () => {
    setResult(null);
    setEnrichments({});
    setStep("upload");
    setFile(null);
  };

  return (
    <div style={{ maxWidth: 800, margin: "40px auto", fontFamily: "system-ui" }}>
      <h1>AI 自动化测试平台</h1>

      {/* ---- Step indicator ---- */}
      <div
        style={{
          display: "flex",
          gap: 24,
          marginBottom: 32,
          padding: "12px 16px",
          background: "#f0f4ff",
          borderRadius: 8,
          fontSize: 14,
        }}
      >
        {["上传 CSV", "补全用例", "探索 & 执行"].map((label, i) => (
          <span
            key={i}
            style={{
              color:
                (i === 0 && step !== "upload") ||
                (i === 1 && step === "complete")
                  ? "#888"
                  : i === 0
                  ? "#2563eb"
                  : "#333",
              fontWeight: i <= (step === "upload" ? 0 : step === "review" ? 1 : 2) ? 600 : 400,
            }}
          >
            {i > 0 && <span style={{ marginRight: 8 }}>→</span>}
            {label}
          </span>
        ))}
      </div>

      {/* ---- Step 1: Upload ---- */}
      <div
        style={{
          border: "2px dashed #ccc",
          padding: 30,
          borderRadius: 8,
          marginBottom: 20,
          opacity: step !== "upload" ? 0.5 : 1,
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
        <p style={{ fontSize: 13, color: "#666", marginTop: 8 }}>
          支持禅道导出的 CSV，含「所属模块」「测试点/用例标题」「步骤」「预期」等列
        </p>
      </div>

      {/* ---- Step 2: Review & Enrich ---- */}
      {step === "review" && result && !result.error && (
        <>
          {/* Completeness criteria */}
          <div
            style={{
              background: "#fefce8",
              border: "1px solid #fde047",
              padding: 16,
              borderRadius: 8,
              marginBottom: 20,
              fontSize: 14,
            }}
          >
            <h3 style={{ margin: 0, marginBottom: 8 }}>🔍 用例完整度判断标准</h3>
            <p style={{ margin: 0 }}>
              <b>完整用例</b>：步骤同时包含<b>导航</b>（进入/打开 XX 页面）和<b>操作</b>（点击/输入/选择/删除）。
              <br />
              <b>待补全用例</b>：仅有操作但缺少目标页面路径。需要补充<b>目标页面 URL</b>和<b>元素选择器</b>。
            </p>
          </div>

          {/* Stats */}
          <div
            style={{
              background: "#f9f9f9",
              padding: 16,
              borderRadius: 8,
              marginBottom: 20,
            }}
          >
            <p>
              用例集 ID: <b>{result.suite_id}</b> | 总用例: <b>{result.case_count}</b>
            </p>
            <p>
              ✅ 可直接生成脚本: <b>{result.enrichment?.ready || 0}</b>
              {" | "}
              ⚠️ 需要补全: <b>{result.enrichment?.needs_enrichment || 0}</b>
            </p>
          </div>

          {/* Enrichment forms */}
          {result.enrichment?.incomplete_cases?.length > 0 && (
            <>
              <h3>待补全用例（{result.enrichment.incomplete_cases.length} 条）</h3>
              {result.enrichment.incomplete_cases.map((c: EnrichmentCase, i: number) => (
                <div
                  key={c.case_id}
                  style={{
                    margin: "12px 0",
                    padding: 16,
                    background: "#fff",
                    border: "1px solid #e5e7eb",
                    borderRadius: 8,
                  }}
                >
                  <strong>
                    #{i + 1} {c.case_title}
                  </strong>
                  <p style={{ fontSize: 13, color: "#666", margin: "4px 0" }}>
                    模块: {c.module} | 步骤: {c.steps?.join(" → ")}
                  </p>

                  <div style={{ marginTop: 12, display: "flex", flexDirection: "column", gap: 8 }}>
                    <label style={{ fontSize: 13 }}>
                      {c.template.target_url_hint}：
                      <input
                        type="text"
                        placeholder={c.template.target_url || "/模块路径"}
                        value={enrichments[c.case_id]?.target_url || ""}
                        onChange={(e) => handleEnrich(c.case_id, "target_url", e.target.value)}
                        style={{ width: "100%", padding: "6px 8px", marginTop: 4, borderRadius: 4, border: "1px solid #d1d5db" }}
                      />
                    </label>
                    <label style={{ fontSize: 13 }}>
                      {c.template.selector_hint_desc}：
                      <input
                        type="text"
                        placeholder="如：button.edit-btn, input[name='title']"
                        value={enrichments[c.case_id]?.selector_hint || ""}
                        onChange={(e) => handleEnrich(c.case_id, "selector_hint", e.target.value)}
                        style={{ width: "100%", padding: "6px 8px", marginTop: 4, borderRadius: 4, border: "1px solid #d1d5db" }}
                      />
                    </label>
                    <label style={{ fontSize: 13 }}>
                      {c.template.extra_note_desc}：
                      <input
                        type="text"
                        placeholder="选填"
                        value={enrichments[c.case_id]?.extra_note || ""}
                        onChange={(e) => handleEnrich(c.case_id, "extra_note", e.target.value)}
                        style={{ width: "100%", padding: "6px 8px", marginTop: 4, borderRadius: 4, border: "1px solid #d1d5db" }}
                      />
                    </label>
                  </div>
                </div>
              ))}
              <button
                onClick={handleSubmitEnrichments}
                style={{
                  marginTop: 16,
                  padding: "10px 24px",
                  background: "#2563eb",
                  color: "#fff",
                  border: "none",
                  borderRadius: 6,
                  cursor: "pointer",
                  fontSize: 16,
                }}
              >
                保存补全信息 →
              </button>
            </>
          )}

          {result.enrichment?.needs_enrichment === 0 && result.case_count > 0 && (
            <div style={{ textAlign: "center", padding: 20 }}>
              <p>🎉 所有用例均完整，可直接进入下一步！</p>
              <button
                onClick={() => setStep("complete")}
                style={{
                  padding: "10px 24px",
                  background: "#2563eb",
                  color: "#fff",
                  border: "none",
                  borderRadius: 6,
                  cursor: "pointer",
                  fontSize: 16,
                }}
              >
                进入探索 & 执行 →
              </button>
            </div>
          )}
        </>
      )}

      {/* ---- Step 3: Next steps (placeholder for now) ---- */}
      {step === "complete" && (
        <div
          style={{
            background: "#f0fdf4",
            border: "1px solid #86efac",
            padding: 24,
            borderRadius: 8,
            marginTop: 20,
          }}
        >
          <h3>📋 后续流程（即将接入）</h3>
          <ol style={{ lineHeight: 2 }}>
            <li>
              <b>元素探索</b>：提供测试地址和账号密码 → 智能体用 Playwright 逐页收集可交互元素
            </li>
            <li>
              <b>脚本生成</b>：用例 + 元素地图 → AI 生成 Python/Playwright 脚本
            </li>
            <li>
              <b>智能执行</b>：执行脚本 → 遇到问题 AI 判断（选择器/Bug/环境）→ 自愈或记录
            </li>
            <li>
              <b>报告输出</b>：Markdown + JSON 测试报告，含截图和 AI 决策记录
            </li>
          </ol>

          <div style={{ marginTop: 16, display: "flex", gap: 12 }}>
            <button
              style={{
                padding: "10px 24px",
                background: "#059669",
                color: "#fff",
                border: "none",
                borderRadius: 6,
                cursor: "pointer",
              }}
            >
              🚀 开始探索（待接入）
            </button>
            <button
              onClick={handleReset}
              style={{
                padding: "10px 24px",
                background: "#6b7280",
                color: "#fff",
                border: "none",
                borderRadius: 6,
                cursor: "pointer",
              }}
            >
              上传新用例
            </button>
          </div>
        </div>
      )}

      {/* ---- Error ---- */}
      {result?.error && (
        <div style={{ background: "#fef2f2", border: "1px solid #fca5a5", padding: 16, borderRadius: 8, color: "#dc2626" }}>
          错误: {result.error}
        </div>
      )}
    </div>
  );
}
