# 探索引擎重构 — 方案三：自研 Browser Tools + MCP 风格工具调用

> 创建日期：2026-05-06
> 设计文档：`docs/superpowers/specs/2026-05-06-mcp-style-test-engine-design.md`

## Context

当前 AI 从文本列表猜 selector，脚本生成质量差。改为方案三：自研 Browser Tools 层，暴露 `snapshot`/`click`/`fill` 等工具给 AI（通过 OpenAI function calling），录制工具调用序列为 Action IR，脚本由 IR 确定性编译。不依赖外部 MCP server，底层直接用 Playwright Python。

### 测试环境

- **目标系统**：`http://192.168.31.155`（小仓写作）
- **测试账号**：`test_c` / `123456`
- **登录后**：跳转到 `/ai-talk/index`（快速写作）
- **AI API**：`mimo-v2.5-pro` @ `https://api.xiaomimimo.com/v1`
- **已知 bug**：`openai_compatible.py` 的 `analyze()` 在 `max_tokens` 太小时返回空 `content`，导致 JSONDecodeError

## 核心原则

1. AI 负责理解、规划、选择下一步
2. Playwright 负责真实浏览器操作
3. 平台负责录制、约束、状态管理、失败恢复
4. 脚本由 Action IR 编译生成，不让 AI 直接写整段脚本

## 总体架构（8 层）

```
Frontend        上传 CSV / 配置 / 实时日志 / 报告 / 脚本预览
API Layer       FastAPI REST + WebSocket
Case Layer      CSVParser / CaseEnricher / CasePlanner
Agent Layer     AI Planner / AI Explorer / AI Assertion Judge
Browser Layer   Playwright BrowserTool / LocatorEngine / SemanticSnapshot
Recording Layer Action IR / screenshots / trace / video / tool-call log
Generation Layer IR -> Playwright Python Script
Execution Layer Replay Executor / Healing / Reporter
```

## 模块设计

```
backend/
  engine/
    parser/
      csv_parser.py              # 改造：修正字段名，稳定解析
      case_normalizer.py         # 新增：用例标准化

    planner/
      case_planner.py            # 新增：AI 规划用例步骤分类
      step_classifier.py         # 新增：步骤分类（导航/输入/点击/校验/等待）
      test_data_resolver.py      # 新增：测试数据补全

    browser/
      browser_tool.py            # 新增：BrowserTools（snapshot/click/fill/navigate/...）
      semantic_snapshot.py       # 新增：页面语义快照
      locator_engine.py          # 新增：ref → Playwright locator 编译
      session_manager.py         # 已有：登录态管理
      artifact_manager.py        # 新增：资产归档（trace/video/screenshot）

    agent/
      explorer_agent.py          # 新增：多轮观察-决策-执行
      decision_schema.py         # 新增：AI 输出 JSON schema
      prompts.py                 # 新增：探索提示词
      assertion_agent.py         # 新增：断言判断

    recorder/
      action_ir.py               # 新增：ActionIR 数据结构
      run_recorder.py            # 新增：运行录制器

    generator/
      playwright_compiler.py     # 新增：IR → Playwright 脚本
      script_formatter.py        # 新增：脚本格式化

    executor/
      replay_executor.py         # 改造：回放生成的脚本
      healing.py                 # 已有：定位失败修复

    reporter/
      reporter.py                # 已有：报告生成
```

## 关键数据结构

### TestCase
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
  "priority": 1
}
```

### Semantic Snapshot
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

### AI Decision
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
- navigate, click, fill, hover, select, upload, wait
- assert_visible, assert_text, assert_url

### Action IR
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

## Locator 策略（按稳定性排序）

```
1. data-testid / data-test
2. role + accessible name
3. label
4. placeholder
5. text
6. css
7. xpath
```

脚本输出优先：
```python
page.get_by_role("button", name="查询").click()
page.get_by_placeholder("请输入文档标题").fill("自动存储")
page.get_by_text("文档中心").click()
```

避免：
```python
page.locator(".n-button").nth(3).click()  # 容易碎
```

## Explorer Agent 流程

```
当前用例步骤 + Semantic Snapshot + 已执行历史
  → AI Decision（结构化 JSON）
  → BrowserTool 执行
  → 记录结果
  → 失败则重新 snapshot → AI 修正
```

失败重试（最多 3 次）：
```
第 1 次：AI 原始 locator
第 2 次：LocatorEngine 候选替代
第 3 次：AI 根据失败截图 + 新 snapshot 重新决策
仍失败：标记 blocked/error
```

## 核心流程

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

## 资产归档

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

## API 设计

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

## MVP 路线

### MVP 1：入口稳定
- 修 `CSVParser`，确保真实中文 CSV 解析成 TestCase
- 前端上传能看到用例列表
- 文件：`backend/engine/parser/csv_parser.py`

### MVP 2：语义快照
- 新增 `SemanticSnapshot`，输出页面分区、元素 role/name/placeholder/上下文、locator candidates
- 新增 `LocatorEngine`，ref → Playwright locator 编译
- 文件：`backend/engine/browser/semantic_snapshot.py`, `locator_engine.py`

### MVP 3：AI 工具决策
- 新增 `DecisionSchema`（AI 输出 JSON schema）
- 新增 `ExplorerAgent`（多轮 AI 交互 + BrowserTools）
- AI 支持 function calling（tools 参数）
- 文件：`backend/engine/agent/decision_schema.py`, `explorer_agent.py`, `prompts.py`
- 文件：`backend/ai/providers/openai_compatible.py`（新增 chat_with_tools）

### MVP 4：Action IR + 录制
- 新增 `ActionIR` 数据结构
- 每步动作写入 `action_ir.json`
- 同时保存截图、trace、video
- 文件：`backend/engine/recorder/action_ir.py`, `run_recorder.py`

### MVP 5：脚本编译和回放
- 新增 `PlaywrightCompiler`，IR → Python 脚本
- `ReplayExecutor` 回放验证
- 生成报告
- 文件：`backend/engine/generator/playwright_compiler.py`

## 成功指标

```
CSV 解析成功率：100%
每步动作都有 Action IR：100%
生成脚本语法检查通过：100%
脚本回放通过率：先达到 70%+
失败步骤有截图和原因：100%
AI 决策可追溯：每步有 reason/confidence/snapshot
```

## 测试策略

### 已有测试

```
tests/
  test_parser.py          # CSVParser 单元测试
  test_models.py          # TestCase/Step 模型测试
  test_session.py         # SessionManager 测试
  test_generator.py       # ScriptGenerator 测试
  test_healing.py         # HealingStore 测试
  test_executor.py        # SmartExecutor 测试
  test_reporter.py        # ReportGenerator 测试
  test_ai.py              # AI Provider 测试
  test_ai_explorer.py     # AIExplorer 测试
  test_api.py             # API 路由测试
  test_integration.py     # 集成测试
  e2e_v2_engine.py        # v2 引擎端到端测试
```

### 各 MVP 新增测试

**MVP 1 — CSVParser**
- 已有 `test_parser.py`，补充边界用例：
  - 空行跳过、列名别名、GBK 编码、步骤格式异常
- 文件：`tests/test_parser.py`（修改）

**MVP 2 — 语义快照**
- `tests/test_semantic_snapshot.py`
  - 测试 SemanticSnapshot 从 mock DOM 生成正确的 sections/elements/ref
  - 测试 LocatorEngine 按优先级选择 locator 策略
  - 测试 ref 解析：ref → Playwright locator
  - 测试空页面、纯文本页面、复杂表单页面

**MVP 3 — AI 工具决策**
- `tests/test_decision_schema.py`
  - 测试 DecisionSchema JSON 校验：合法/非法 action、缺失字段、未知 ref
- `tests/test_explorer_agent.py`
  - mock AI 返回固定 Decision，验证 BrowserTools 被正确调用
  - 测试多轮交互：snapshot → decision → execute → next step
  - 测试失败重试：locator 失败 → 候选替代 → AI 重新决策
  - 测试 3 次重试后标记 blocked/error
- `tests/test_browser_tool.py`
  - 测试 BrowserTools 各方法（click/fill/navigate/hover/select/wait）
  - 测试 ref 不存在时的错误处理
  - 测试 snapshot 返回结构正确的 SemanticSnapshot

**MVP 4 — Action IR**
- `tests/test_action_ir.py`
  - 测试 ActionIR 数据结构的序列化/反序列化
  - 测试 RunRecorder 录制每步动作
  - 测试截图路径生成、URL 记录
- `tests/test_run_recorder.py`
  - 测试完整用例录制流程
  - 测试 IR 文件写入/读取

**MVP 5 — 脚本编译**
- `tests/test_playwright_compiler.py`
  - 测试 IR → Playwright 脚本编译：fill/click/navigate/assert
  - 测试 locator 策略优先级：role > placeholder > text > css
  - 测试生成脚本的 AST 语法检查通过
  - 测试边界：空 IR、单步、多步、失败步骤跳过

### 集成测试

- `tests/test_v3_pipeline.py`
  - 端到端流程（mock AI + mock browser）：
    1. 上传 CSV → 解析 TestCase
    2. ExplorerAgent 探索 → 生成 ActionIR
    3. PlaywrightCompiler 编译 → 生成脚本
    4. 验证脚本语法正确
  - 测试 v3 链路在 orchestrator 中的切换

### E2E 测试（AI 使用 Playwright MCP 验收）

E2E 测试由 AI 通过 Playwright MCP 工具执行，不是自动化脚本。AI 作为测试人员操作浏览器访问平台页面，验证完整流程。

**执行方式**：AI 调用 Playwright MCP 的 `browser_navigate`/`browser_click`/`browser_fill`/`browser_snapshot`/`browser_screenshot` 等工具。

**验收流程**：

1. **启动平台** — 确认后端 + 前端服务已运行
2. **上传用例** — MCP 打开前端页面 → 点击上传 → 选择 CSV → 验证用例列表显示正确
3. **配置目标** — 填写被测系统 URL + 凭据
4. **触发运行** — 点击"一键运行" → 轮询状态直到完成
5. **验证结果**：
   - 检查 Action IR 是否生成（每步有 action/locator/status）
   - 检查生成脚本是否语法正确（`ast.parse`）
   - 检查脚本是否使用语义选择器（`get_by_role`/`get_by_placeholder`，而非 `.nth()`）
   - 检查截图是否生成
   - 检查报告是否包含用例结果
6. **回放验证** — 下载生成的脚本 → 在独立浏览器中执行 → 验证通过

**验证检查点**：

```
□ CSV 上传后用例数正确
□ 探索状态从 EXPLORING 变为 EXPLORED
□ action_ir.json 存在且结构完整
□ 每个 step 有 before/after 截图
□ 生成脚本使用语义 locator（无 .nth()、无硬编码 xpath）
□ 生成脚本 AST 语法检查通过
□ 报告包含 pass/fail 状态
□ 脚本独立回放通过
```

### 测试运行方式

```bash
# 单元测试
pytest tests/test_semantic_snapshot.py tests/test_locator_engine.py -v

# 集成测试
pytest tests/test_v3_pipeline.py -v

# E2E 测试 — 由 AI 通过 Playwright MCP 执行（见上方流程）

# 全量单元测试
pytest tests/ -v --ignore=tests/e2e_*.py
```

## 现有代码分析与改造策略

### 保留不动的模块

| 文件 | 说明 |
|---|---|
| `engine/parser/enricher.py` | 用例补全逻辑，继续使用 |
| `engine/explorer/browser.py` | BrowserController 保留，BrowserTools 包装它 |
| `engine/explorer/session.py` | 登录态管理不变 |
| `engine/explorer/engine.py` | 旧 ExplorationEngine，过渡期保留 |
| `engine/explorer/ai_explorer.py` | 旧 v1/v2 探索器，过渡期保留不删 |
| `engine/generator/generator.py` | 旧 ScriptGenerator/AIScriptGenerator，过渡期保留不删 |
| `engine/executor/executor.py` | SmartExecutor 用于回放阶段 |
| `engine/executor/healing.py` | 选择器自愈逻辑复用 |
| `engine/executor/ai_guard.py` | AI 成本控制复用 |
| `engine/reporter/reporter.py` | 报告生成不变 |
| `models/case.py` | TestCase/Step 结构不变 |
| `models/run.py`, `ai_record.py`, `healing.py` | 数据模型不变 |

### 需要小改的模块

| 文件 | 改动 |
|---|---|
| `engine/parser/csv_parser.py` | 已验证可用，微调字段映射即可 |
| `config.py` | 新增 `use_v3_engine: bool = False` 开关，切换新旧链路 |
| `storage/database.py` | 可能新增 `action_ir` 表存储 IR 数据 |

### 需要扩展的模块

| 文件 | 改动 |
|---|---|
| `ai/base.py` | AIProvider 协议新增 `chat_with_tools(messages, tools) -> dict` 方法 |
| `ai/providers/openai_compatible.py` | 新增 `chat_with_tools()` 实现，调用 OpenAI function calling（tools 参数） |
| `engine/explorer/prompts.py` | 新增 v3 探索提示词常量（DecisionSchema 相关），旧 prompt 保留 |
| `engine/orchestrator.py` | **最大改动**：新增 `_explore_ai_v3()` 方法，串联 BrowserTools → ExplorerAgent → ActionIR → PlaywrightCompiler |

### 新建模块

```
MVP 2: 语义快照
  engine/browser/semantic_snapshot.py    # 页面语义快照，page.evaluate() 收集
  engine/browser/locator_engine.py       # ref → Playwright locator 编译

MVP 3: AI 工具决策
  engine/browser/browser_tool.py         # BrowserTools 封装层（包装 BrowserController）
  engine/agent/decision_schema.py        # AI Decision JSON schema
  engine/agent/explorer_agent.py         # 多轮 AI 交互 + BrowserTools
  engine/agent/prompts.py                # v3 探索提示词

MVP 4: Action IR + 录制
  engine/recorder/action_ir.py           # ActionIR 数据结构
  engine/recorder/run_recorder.py        # 运行录制器

MVP 5: 脚本编译和回放
  engine/generator/playwright_compiler.py # IR → Playwright 脚本
```

### Orchestrator 改造细节

现有 v2 链路（保留）：
```
_explore_ai_v2() → AIExplorer.explore_case_v2() → ExplorationRecording
_generate_scripts_v2() → AIScriptGenerator.generate_from_recording()
```

新增 v3 链路：
```
_explore_ai_v3() → ExplorerAgent.run() → ActionIR
_generate_scripts_v3() → PlaywrightCompiler.compile()
```

通过 `config.use_v3_engine` 切换。v1/v2 链路代码不删，确保回退能力。

### AI Provider 改造细节

`openai_compatible.py` 新增方法：
```python
async def chat_with_tools(self, messages: list, tools: list) -> dict:
    """OpenAI function calling
    返回: {"tool_calls": [...], "content": "..."}
    """
```

`base.py` AIProvider 协议扩展：
```python
async def chat_with_tools(self, messages: list, tools: list) -> dict
```

### BrowserTools 与 BrowserController 的关系

```
BrowserController (现有，不改)
  ├── start/stop/goto/take_screenshot
  ├── collect_interactive_elements()
  ├── collect_dom_hierarchy()
  └── format_elements_hierarchical()

BrowserTools (新增，包装层)
  ├── __init__(page: Page)  # 直接用 Playwright Page
  ├── snapshot() → SemanticSnapshot  # 调用 semantic_snapshot.py
  ├── click(ref)  # 通过 locator_engine 解析 ref
  ├── fill(ref, value)
  ├── navigate(url)
  ├── select_option(ref, value)
  ├── hover(ref)
  ├── wait(ms)
  ├── screenshot(path)
  └── expect(assertion)
```

BrowserTools 不继承 BrowserController，而是组合使用。底层直接操作 Playwright Page 对象。

## 文件优先级（含改造）

```
# 改造
1. backend/ai/base.py                          # 扩展 AIProvider 协议
2. backend/ai/providers/openai_compatible.py   # 新增 chat_with_tools
3. backend/config.py                           # 新增 use_v3_engine

# 新建 MVP 2
4. backend/engine/browser/semantic_snapshot.py
5. backend/engine/browser/locator_engine.py

# 新建 MVP 3
6. backend/engine/browser/browser_tool.py
7. backend/engine/agent/decision_schema.py
8. backend/engine/agent/explorer_agent.py
9. backend/engine/agent/prompts.py

# 新建 MVP 4
10. backend/engine/recorder/action_ir.py
11. backend/engine/recorder/run_recorder.py

# 新建 MVP 5
12. backend/engine/generator/playwright_compiler.py

# 改造（最后）
13. backend/engine/orchestrator.py             # 新增 v3 链路
```

## 过渡策略

- 现有 `ai_explorer.py`、`generator.py`、`executor.py` 保留不删
- MVP 新链路跑通后，逐步替换旧探索器
- 旧链路通过 `config.use_v3_engine = False` 回退
- v1 (`use_v2_engine=False`)：模板探索 + 模板生成
- v2 (`use_v2_engine=True`)：AI 探索 + AI 生成
- v3 (`use_v3_engine=True`)：BrowserTools + Action IR + 编译生成
