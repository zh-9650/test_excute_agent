# AI 自动化测试平台 — MCP 风格工具调用架构设计

## 1. 背景与问题

当前探索引擎存在根本性设计问题：

- AI 从扁平文本列表猜 CSS selector，经常选错（如把"返回"猜成"菜单"）
- 脚本生成由 AI 直接输出代码，质量不可控（编造 selector、混用 API、忘记等待）
- 录制数据没有统一中间表示（IR），链路散乱

## 2. 设计目标

平台最终形态不是"AI 帮我写脚本"，而是：

```
上传测试用例 → AI 理解用例 → AI 调用浏览器工具探索系统
→ 平台记录真实动作 → 平台生成结构化脚本 → 平台回放验证
→ 输出报告和可维护资产
```

核心原则：
1. AI 负责理解、规划、选择下一步
2. Playwright 负责真实浏览器操作
3. 平台负责录制、约束、状态管理、失败恢复
4. 脚本由 Action IR 编译生成，不让 AI 直接写整段脚本

## 3. 技术选型

- **方案**：方案三 — 自研 Browser Tools，MCP 风格工具调用
- **不依赖外部 MCP server**，底层直接用 Playwright Python
- **AI 调用机制**：OpenAI function calling（tools 参数）
- **未来可扩展**：工具层可包装为 MCP Server 协议

## 4. 总体架构（8 层）

```
Frontend        上传 CSV / 配置目标站点 / 实时日志 / 报告 / 脚本预览
API Layer       FastAPI REST + WebSocket
Case Layer      CSVParser / CaseEnricher / CasePlanner
Agent Layer     AI Planner / AI Explorer / AI Assertion Judge
Browser Layer   Playwright BrowserTool / LocatorEngine / SemanticSnapshot
Recording Layer Action IR / screenshots / trace / video / tool-call log
Generation Layer IR -> Playwright Python Script
Execution Layer Replay Executor / Healing / Reporter
```

## 5. 模块设计

```
backend/
  engine/
    parser/
      csv_parser.py              # CSV → TestCase
      case_normalizer.py         # 用例标准化

    planner/
      case_planner.py            # AI 规划用例步骤分类
      step_classifier.py         # 步骤分类（导航/输入/点击/校验/等待）
      test_data_resolver.py      # 测试数据补全

    browser/
      browser_tool.py            # BrowserTools（snapshot/click/fill/navigate/...）
      semantic_snapshot.py       # 页面语义快照
      locator_engine.py          # ref → Playwright locator 编译
      session_manager.py         # 登录态管理
      artifact_manager.py        # 资产归档（trace/video/screenshot）

    agent/
      explorer_agent.py          # 多轮观察-决策-执行
      decision_schema.py         # AI 输出 JSON schema
      prompts.py                 # 探索提示词
      assertion_agent.py         # 断言判断

    recorder/
      action_ir.py               # ActionIR 数据结构
      run_recorder.py            # 运行录制器

    generator/
      playwright_compiler.py     # IR → Playwright 脚本
      script_formatter.py        # 脚本格式化

    executor/
      replay_executor.py         # 回放生成的脚本
      healing.py                 # 定位失败修复

    reporter/
      reporter.py                # 报告生成
```

## 6. 关键数据结构

### 6.1 TestCase

CSV 解析后的统一用例格式：

```json
{
  "id": "case_001",
  "module": "文档中心",
  "title": "文档搜索功能正常",
  "preconditions": "已登录系统，已进入文档中心",
  "steps": [
    {"order": 1, "text": "在搜索框输入文档标题关键字"},
    {"order": 2, "text": "点击查询按钮"}
  ],
  "expected": "列表只显示匹配的文档",
  "priority": 1,
  "keywords": ["搜索", "查询"]
}
```

### 6.2 Semantic Snapshot

替代"扁平 DOM 列表"的页面语义快照：

```json
{
  "url": "http://.../document-center/index",
  "title": "文档中心",
  "page_type": "document_list",
  "sections": [
    {
      "name": "顶部导航",
      "type": "navigation",
      "elements": [
        {
          "ref": "el_001",
          "role": "menuitem",
          "name": "文档中心",
          "text": "文档中心",
          "visible": true,
          "locator_candidates": [
            {"strategy": "role", "role": "menuitem", "name": "文档中心"},
            {"strategy": "text", "value": "文档中心"}
          ]
        }
      ]
    },
    {
      "name": "搜索区",
      "type": "search",
      "elements": [
        {
          "ref": "el_010",
          "role": "textbox",
          "name": "请输入文档标题",
          "placeholder": "请输入文档标题",
          "visible": true
        }
      ]
    }
  ]
}
```

每个元素有：
- `ref`：唯一标识，AI 用 ref 引用元素
- `role`：语义角色（button/menuitem/textbox/...）
- `name`：可访问名称（aria-label / text / placeholder）
- `locator_candidates`：预计算的定位候选，按稳定性排序

### 6.3 AI Decision

AI 每次只允许返回固定 JSON：

```json
{
  "action": "fill",
  "target_ref": "el_010",
  "locator": {"strategy": "placeholder", "value": "请输入文档标题"},
  "value": "自动存储",
  "reason": "该步骤要求在文档标题搜索框输入关键字",
  "confidence": 0.86
}
```

支持的动作类型（MVP）：
- `navigate` — 导航到 URL
- `click` — 点击元素
- `fill` — 填写输入框
- `hover` — 悬停元素
- `select` — 选择下拉框
- `upload` — 上传文件
- `wait` — 等待
- `assert_visible` — 断言元素可见
- `assert_text` — 断言文本内容
- `assert_url` — 断言 URL

### 6.4 Action IR

脚本生成的唯一来源：

```json
{
  "run_id": "run_001",
  "case_id": "case_003",
  "case_title": "文档搜索功能正常",
  "steps": [
    {
      "order": 1,
      "natural_step": "在搜索框输入文档标题关键字",
      "action": "fill",
      "locator": {"strategy": "placeholder", "value": "请输入文档标题"},
      "value": "自动存储",
      "before_url": ".../document-center/index",
      "after_url": ".../document-center/index",
      "screenshot_before": "screenshots/case_003_step_1_before.png",
      "screenshot_after": "screenshots/case_003_step_1_after.png",
      "status": "passed"
    }
  ]
}
```

trace/video 是证据，Action IR 才是脚本资产。

## 7. Locator 策略

LocatorEngine 按稳定性排序：

```
1. data-testid / data-test     → page.get_by_test_id("xxx")
2. role + accessible name      → page.get_by_role("button", name="查询")
3. label                       → page.get_by_label("xxx")
4. placeholder                 → page.get_by_placeholder("请输入文档标题")
5. text                        → page.get_by_text("文档中心")
6. css                         → page.locator(".class-name")
7. xpath                       → page.locator("//xpath")
```

脚本输出应优先使用语义选择器，避免 `.nth(3)` 等脆弱定位。

## 8. BrowserTools 接口

```python
class BrowserTools:
    def __init__(self, page): ...

    async def snapshot(self) -> dict:
        """页面语义快照 — 用 page.evaluate() 收集可交互元素"""

    async def click(self, ref: str) -> dict:
        """点击元素 — ref 来自 snapshot"""

    async def fill(self, ref: str, value: str) -> dict:
        """填写输入框"""

    async def hover(self, ref: str) -> dict:
        """悬停元素"""

    async def navigate(self, url: str) -> dict:
        """导航到 URL"""

    async def select_option(self, ref: str, value: str) -> dict:
        """选择下拉框"""

    async def press_key(self, key: str) -> dict:
        """按键"""

    async def wait(self, ms: int = 1000) -> dict:
        """等待"""

    async def screenshot(self, path: str) -> dict:
        """截图"""

    async def expect(self, assertion: dict) -> dict:
        """断言验证"""
```

`_resolve_ref(ref)` 方法：从 ref_map 查找元素，按优先级选择 locator 策略。

## 9. Explorer Agent 流程

```
输入：测试步骤 + Semantic Snapshot + 已执行历史
  → AI Decision（结构化 JSON）
  → BrowserTool 执行
  → 记录结果
  → 失败则重新 snapshot → AI 修正
```

多轮交互：每步最多 3 轮 AI 调用（snapshot → 决策 → 验证）。

失败重试（最多 3 次）：
```
第 1 次：AI 原始 locator
第 2 次：LocatorEngine 候选替代
第 3 次：AI 根据失败截图 + 新 snapshot 重新决策
仍失败：标记 blocked/error
```

## 10. 核心流程

```
1. 上传 CSV → 解析为 TestCase
2. AI/规则补全用例步骤
3. 创建 run_id，启动有头浏览器
4. 开启 trace/video
5. 登录并保存 storage_state
6. 对每条用例逐步探索：
   a. 采集 Semantic Snapshot
   b. AI 返回结构化 Decision
   c. BrowserTool 执行动作
   d. 执行后截图、记录 URL、DOM 摘要、结果
   e. 失败则自愈重试
   f. 写入 Action IR
7. IR 编译为 Playwright Python 脚本
8. 回放脚本验证
9. 生成 report.md / report.json
```

## 11. 资产归档

```
test_artifacts/{run_id}/
  action_ir.json               # 结构化录制
  tool_calls.jsonl             # AI 工具调用日志
  trace.zip                    # Playwright trace
  report.md                    # Markdown 报告
  report.json                  # JSON 报告
  screenshots/
    case_001_step_1_before.png
    case_001_step_1_after.png
  videos/
    run.webm
  scripts/
    test_case_001.py
    test_case_002.py
```

## 12. API 设计

```
POST /api/v1/cases/upload          # 上传 CSV
GET  /api/v1/cases/{suite_id}      # 查看用例

POST /api/v1/tests/explore         # 探索
POST /api/v1/tests/generate        # 生成脚本
POST /api/v1/tests/execute         # 执行
POST /api/v1/tests/run             # 一键运行

GET  /api/v1/tests/{run_id}/status
GET  /api/v1/tests/{run_id}/logs
GET  /api/v1/tests/{run_id}/ir
GET  /api/v1/tests/{run_id}/scripts
GET  /api/v1/reports/{run_id}
```

## 13. MVP 路线

### MVP 1：入口稳定
- 修 CSVParser，确保真实中文 CSV 解析成 TestCase
- 前端上传能看到用例列表

### MVP 2：语义快照
- 新增 SemanticSnapshot，输出页面分区、元素 role/name/placeholder/locator candidates
- 新增 LocatorEngine，ref → Playwright locator 编译

### MVP 3：AI 工具决策
- 新增 DecisionSchema（AI 输出 JSON schema）
- 新增 ExplorerAgent（多轮 AI 交互 + BrowserTools）
- AI 支持 function calling（tools 参数）

### MVP 4：Action IR + 录制
- 新增 ActionIR 数据结构
- 每步动作写入 action_ir.json
- 同时保存截图、trace、video

### MVP 5：脚本编译和回放
- 新增 PlaywrightCompiler，IR → Python 脚本
- ReplayExecutor 回放验证
- 生成报告

## 14. 成功指标

```
CSV 解析成功率：100%
每步动作都有 Action IR：100%
生成脚本语法检查通过：100%
脚本回放通过率：先达到 70%+
失败步骤有截图和原因：100%
AI 决策可追溯：每步有 reason/confidence/snapshot
```

## 15. 过渡策略

现有 ai_explorer.py、generator.py 暂时保留不删。MVP 新链路跑通后，逐步替换旧探索器。旧链路通过 config.use_v2_engine 切换。
