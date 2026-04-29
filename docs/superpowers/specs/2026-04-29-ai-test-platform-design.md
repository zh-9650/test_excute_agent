# AI 驱动自动化测试平台 — 设计规格

## 概述

面向测试工程师的 AI 驱动自动化测试平台。输入测试用例（CSV）和测试信息（URL、凭据），由 AI 主导完成页面探索、脚本生成、智能执行、结果分析全流程，最终输出测试报告。

## 技术选型

- **后端**：Python + FastAPI + Playwright
- **前端**：React + Vite
- **AI 层**：可配置多提供商（Qwen3.5 本地 / DeepSeek API / GPT-5.5 中转 / 其他）
- **存储**：SQLite（元数据）+ 文件系统（制品）
- **报告**：Jinja2 模板驱动，主输出 Markdown + JSON

## 架构

### 四层结构

```
表现层   React SPA          用例导入 | 执行面板 | 实时日志 | 报告查看
API层    FastAPI REST+WS    14端点 + WebSocket 实时推送
引擎层   核心模块            解析器 | 探索引擎 | 脚本生成器 | 智能执行器 | 报告生成器
基础设施  Playwright | AI Provider | 文件存储 | 日志系统
```

### 核心流程

1. **用例导入** — CSV 上传 → 编码检测 → AI 预检补全 → 用户确认 → 结构化用例对象
2. **元素探索** — 按用例步骤逐页导航（含登录）→ 收集可交互元素 → 输出探索报告
3. **脚本生成** — 用例 + 元素地图 → AI 生成 Python/Playwright 脚本 → AST 预检
4. **智能执行** — 执行脚本 → 失败时 AI 判断（选择器/Bug/其他）→ 修复或记录 → 执行后 AI 结果分析
5. **报告输出** — Markdown + JSON + 完整制品目录

## 测试用例状态机

```
PENDING → EXPLORING → GENERATING → RUNNING → PASSED / FAILED / BLOCKED / ERROR
```

| 状态 | 说明 |
|------|------|
| PENDING | 已导入，等待探索 |
| EXPLORING | 探索引擎正在收集元素 |
| GENERATING | 正在生成脚本 |
| RUNNING | 脚本执行中 |
| PASSED | 断言通过 |
| FAILED | 断言不通过 / 确认是 Bug |
| BLOCKED | 页面不可达 / 元素严重缺失 / 需人工介入 |
| ERROR | 脚本崩溃 / 环境异常 / 可重试 |

所有终态都可触发重跑：
- **快速重跑**：直接用已有脚本执行（适用 ERROR / 环境恢复后）
- **完整重跑**：重新探索+生成+执行（适用产品更新后 / 元素大量变化）

## 模块设计

### 1. 用例解析器
- 输入：禅道格式 CSV
- 自动检测编码 → 转 UTF-8
- 校验必填列 → 缺失警告 + 跳过该行
- **AI 预检补全**：导入后对每条用例做 AI 分析，评估步骤描述的完整度
  - 步骤指向明确（含具体页面/按钮名称、操作路径）→ 直接通过
  - 步骤指向模糊（如仅"点击编辑"未说明在哪里）→ 生成补全模板，标记"待补充"
  - 补全模板包含：建议的目标页面路径、可选的选择器描述、补充说明输入框
  - 用户填写补全后确认 → 进入用例库
  - 未补全的用例在探索阶段降级为 AI 导航（探索引擎自行推断）
- 输出：结构化 TestCase 对象列表（含完整度标记）

### 2. 会话管理器
- 探索阶段执行登录 → 保存 Playwright storageState
- 执行阶段恢复会话
- 检测 session 过期 → 用保存的凭据自动重登
- SSO/验证码场景 → 截屏 → 通知用户介入

### 3. 探索引擎
- 深度探索：按用例步骤逐页导航
- 导航策略：
  - 已补全的用例 → 按补全后的页面路径精确导航
  - 未补全的用例 → 从首页开始，按模块路径匹配导航层级 → AI 辅助推断目标页面
  - 所有方式失败 → 标记 SKIPPED → 探索报告中展示
- 每页收集可交互元素（tag/class/text/aria-label）
- 等待策略：networkidle → domcontentloaded → 固定兜底
- 弹窗自动处理（ESC / 点击关闭 / 点击蒙层）
- 页面不可达 → 标记 SKIPPED
- 输出探索报告：已探索页面 + SKIPPED + 元素覆盖度
- 支持用户查看报告后补充信息，只重探 SKIPPED 部分

### 4. 脚本生成器
- 输入：用例 + 元素地图
- AI 生成 Python/Playwright 脚本
- **预检环节**：Python AST 语法检查 + 基础规则（导入检查、API 拼写等）
- 未通过 → 退回 AI 修复（最多 2 次）→ 仍失败 → 标记 ERROR
- 特殊场景处理：文件上传（测试数据工厂）、拖拽排序、多 Tab、文件下载

### 5. 测试数据工厂
- 按用例关键词预生成测试数据
- 如："10MB 文件" → 生成指定大小文件
- "51 字符名称" → 生成指定长度字符串
- "Emoji 输入" → 提供 Emoji 测试数据集

### 6. 智能执行器（核心）

#### 执行流程
每一用例的每个步骤：
1. Playwright 执行操作
2. 成功 → 执行断言 → 记录结果
3. 失败 → 进入 AI 决策

#### AI 决策三场景

**选择器定位失败**（TimeoutError）
	- 先查自愈知识库（第 7 节）→ 命中直接复用 → 未命中再调 AI
	- 截图 + DOM 摘要 → AI 判断 selector_changed / element_missing
	- selector_changed → AI 给新选择器 → 重试成功写入知识库（同一选择器 ≤ 3 次）
	- element_missing → 记录 Bug → 标记 FAILED

**断言失败**
- 实际结果 vs 预期结果 + 截图 → AI 判断 bug / expected_changed / assertion_inaccurate
- bug → 标记 FAILED；expected_changed → 标记 PASSED(预期变更)；assertion_inaccurate → 标记 ERROR

**脚本异常**
- 错误堆栈 + 截图 + 控制台日志 + 网络状态 → AI 分类 script_error / env_error / system_error
- script_error → 尝试修复（限 1 次）；env_error → 暂停或跳过；system_error → 标记 FAILED

#### 异常状态处理
- 单用例超时 5min → 强制终止 → 标记超时 → 继续
- 浏览器崩溃 → 重启 → 恢复登录态 → 从该用例步骤 1 重跑（标记"崩溃重试"）→ 同一用例崩溃 2 次则跳过标记 ERROR
- 连续失败熔断：min(3, 用例总数×20%) → 暂停 → AI 全局分析
  - AI 判定环境问题 → 终止，通知用户检查环境
  - AI 判定脚本问题 → 批量修复脚本 → 继续执行
  - 无法判定 → 暂停，等待用户决定

#### 执行后结果分析
全部用例执行完成后，AI 汇总所有失败/错误/阻塞，进行分类：
- **系统 Bug**：断言失败 + AI 判定 bug → 需开发修复
- **脚本问题**：选择器自愈失败 + 脚本崩溃 → 需优化脚本/选择器
- **环境问题**：网络超时 + 服务不可达 → 需检查环境
- **用例问题**：预期变更 + 用例步骤不完整 → 需更新测试用例

### 7. 选择器自愈机制

选择器失败时，在调用 AI 之前先查自愈知识库，减少重复 AI 调用，实现越跑越智能。

#### 自愈知识库（healing_records 表）
- `original_selector` — 原始选择器
- `healed_selector` — 修复后的选择器
- `page_url_pattern` — 页面 URL 模式（用于匹配同类页面）
- `context_signature` — 周围 DOM 结构摘要（辅助精准匹配）
- `strategy` — 修复策略（text_match / role_match / css_stable / xpath_fallback / compound）
- `success_count` / `fail_count` — 质量跟踪
- 查询排序：success_count DESC, last_used_at DESC
- 自动淘汰：fail_count ≥ 3 删除记录

#### 选择器失败决策流程
```
选择器定位失败 → 查知识库（按 original_selector + URL 模式）
  ├─ 命中 → 用修复选择器重试
  │    ├─ 成功 → success_count++ → 继续
  │    └─ 失败 → fail_count++ → 超过 3 次删除 → 调 AI
  └─ 未命中 → 调 AI 判断
       ├─ selector_changed → new_selector 重试成功 → 写入知识库
       └─ element_missing → 记录 Bug
```

#### 回归加速效果
第 1 次执行选择器失败 → AI 修复 → 写入知识库；第 N 次回归同样问题直接命中，零 AI 调用。

### 8. AI 成本控制
| 策略 | 规则 |
|------|------|
| 同类型去重 | 同一选择器连续失败，后续用缓存 |
| 阶段限制 | 探索：按页面调用；执行：每用例上限 5 次 AI 调用 |
| 批量模式 | N 条连续失败 → 批量发送 1 次 AI 调用全局分析 |
| 降级链路 | 主 AI → 备用 AI → 规则引擎（Levenshtein 选择器匹配） |
| 置信度门禁 | < 0.5 不自动操作，标记"待人工确认" |
| 全局熔断 | 全用例 AI 调用 > 总步骤数×2 → 停止，改规则引擎 |

### 9. 报告生成器
- Jinja2 模板驱动，章节可插拔
- 章节：概览 / 失败用例 / 阻塞用例 / 错误用例 / 模块统计 / AI 决策摘要 / 环境信息
- 主输出 Markdown + JSON（CI/CD 消费）
- 模板独立于代码，非开发人员可修改
- 未来可扩展 HTML 格式

## API 设计

### REST 端点

```
用例管理
  POST   /api/v1/cases/upload
  GET    /api/v1/cases/{suite_id}
  DELETE /api/v1/cases/{suite_id}

测试执行
  POST   /api/v1/tests/run
  GET    /api/v1/tests/{run_id}/status
  WS     /api/v1/tests/{run_id}/logs
  POST   /api/v1/tests/{run_id}/pause
  POST   /api/v1/tests/{run_id}/resume
  POST   /api/v1/tests/{run_id}/stop

探索
  POST   /api/v1/explore/start
  GET    /api/v1/explore/{id}/report
  POST   /api/v1/explore/{id}/retry

报告
  GET    /api/v1/reports/{run_id}
  GET    /api/v1/reports/{run_id}/json
  GET    /api/v1/reports/{run_id}/artifacts/{filename}

健康 & 配置
  GET    /api/v1/health
  GET    /api/v1/config
  PATCH  /api/v1/config
```

### CI/CD 调用模式
```
上传用例 → 启动测试 → 轮询状态 → 拉取报告
```
所有操作通过 API 调用，凭据支持环境变量注入，浏览器支持 headless 模式。

### 并发策略
V1 阶段：串行执行队列。同一时间只允许一个测试任务运行，避免 Playwright 实例冲突和 SQLite 写入竞争。SQLite 启用 WAL 模式保证读写并发安全。后续版本再引入任务队列实现并行执行。

### 补充端点
```
GET    /api/v1/healing              ← 查看自愈知识库
DELETE /api/v1/healing/{id}         ← 删除失效记录
POST   /api/v1/healing/clear        ← 清空知识库
```

## 数据存储

### SQLite（8 张表）
- `test_suites` — 用例集元数据
- `test_cases` — 每条用例（步骤、预期、状态、优先级）
- `test_runs` — 执行记录
- `case_results` — 用例执行结果（状态、AI 判断、耗时）
- `ai_calls` — AI 调用记录（场景、prompt、response、模型）
- `element_map` — 元素地图
- `exploration_logs` — 探索日志
- `healing_records` — 选择器自愈知识库（原始选择器、修复选择器、URL 模式、策略、成败计数）

### 文件系统（制品目录）
```
test_artifacts/{run_id}/
├── report.md / report.json
├── logs/ (execution.log / ai_decisions.jsonl / playwright.log)
├── screenshots/ ({case_id}_step{N}.png / {case_id}_failure.png)
├── videos/ ({case_id}.webm)
├── scripts/ ({case_id}_test.py)
└── exploration/ (element_map.json / exploration_report.md)
```

## 报告结构（Markdown）

- 执行概况（总览表）
- 失败用例详情（预期 vs 实际 vs AI 判定 + 截图/视频链接）
- 阻塞用例（原因 + 建议）
- 错误用例（原因 + 建议）
- 模块维度统计
- AI 决策摘要表
- 环境信息

## 凭据管理

三种方式可混用：
1. Web 页面手动输入（不持久化）
2. 配置文件（加密存储）
3. 环境变量（CI/CD 模式）

## 待量化参数

| 参数 | 默认值 |
|------|--------|
| 元素等待超时 | 3s |
| 页面加载超时 | 30s |
| 单用例执行超时 | 5min |
| 全局超时 | 用例数 × 5min × 0.7 |
| 选择器修复重试 | 3 次/选择器 |
| 脚本 AI 修复重试 | 2 次 |
| 连续失败熔断 | min(3, 总数×20%) |
| AI 置信度低 | < 0.7 |
| AI 置信度拒动 | < 0.5 |
| 探索等待策略 | networkidle → domcontentloaded → 10s 兜底 |

## 目录结构（规划）

```
test_platform/
├── backend/
│   ├── api/           # FastAPI 路由
│   ├── engine/        # 核心引擎
│   │   ├── parser/    # 用例解析器
│   │   ├── explorer/  # 探索引擎
│   │   ├── generator/ # 脚本生成器
│   │   ├── executor/  # 智能执行器
│   │   └── reporter/  # 报告生成器
│   ├── ai/            # AI 提供商适配层
│   ├── models/        # 数据模型
│   ├── storage/       # 存储层
│   └── templates/     # 报告模板
├── frontend/          # React SPA
├── tests/             # 平台自身测试
└── docs/
```
