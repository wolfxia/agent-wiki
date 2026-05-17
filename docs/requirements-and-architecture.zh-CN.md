# Agent Wiki 需求与架构

> 状态：已与当前 Phase 1 实现基线对齐的需求基线  
> 日期：2026-05-16  
> 推荐架构：以协议为中心的 Knowledge Agent  
> 说明：本文档是需求与架构摘要，不是实现计划。

---

## 1. 项目背景与目标

Agent Wiki 是一个通用的、Agent 无关的知识系统，目标是让多个具备不同能力边界的 AI Agent 使用同一套知识资产。

核心问题不只是“文档存在哪里”。真正的问题是构建一个同时具备以下特性的知识系统：

- 可编译
- 可检索
- 可审计
- 可演进
- 可被多个 Agent 长期复用

### 1.1 核心参考来源

本项目主要受两类思路影响：

1. LLM 知识系统思路：
   - `Raw Sources → Wiki → Schema`
   - 通过粗筛 + 分层展示实现混合检索
   - 以技能/工作流驱动知识维护
2. `nashsu/llm_wiki`：
   - 两步式摄入
   - 面向图谱的维护灵感
   - `purpose.md` 与 review 驱动的维护机制

### 1.2 目标 Agent

Phase 1 面向五类 Agent：

| Agent | Tier | 关键能力 | 主要限制 |
|---|---|---|---|
| Hermes | T1 Full | cron、丰富工具、消息通道 | 知识仍需持久化在仓库/文件中 |
| OpenClaw | T1 Full | cron、skill prompt、消息通道 | 执行模型更受限 |
| Claude Code | T2 Standard | 代码推理、workspace 持久化、shell 工具 | 无内建调度器或向量记忆 |
| Codex | T3 Minimal | 基于 CLI 的短时执行 | 无持久状态 |
| OpenCode | T3 Minimal | 基于 CLI 的 provider-agnostic 执行 | 无持久状态 |

### 1.3 Phase 1 目标

Phase 1 的硬目标是形成完整的个人多 Agent 知识闭环：

```text
capture_raw → compile_update → query → lint → sync → weekly-review
```

Phase 1 还需要覆盖以下 smoke path：

- 多 wiki 管理
- shared wiki 行为
- cross-wiki 检索
- principle 写入的 C 级 proposal / approval

---

## 2. 设计原则

### 2.1 从终局设计，分阶段落地

架构从 Phase 2 终局形态出发选择，但 Phase 1 只实现最小可工作的路径。

因此设计中保留：

- `wiki_id:doc_id` 身份模型
- 全局 `registry.yaml`
- 基于 page type 和 gate 的权限模型
- shared wiki 概念
- 多传输层之上的共享核心

### 2.2 核心保持可插拔

架构仍然假设以下部分可插拔：

- 存储
- content adapter
- retrieval provider
- external view
- attachment storage

### 2.3 Git 仍是权威源

权威链保持为：

```text
Git authority → Local workspace compile/index/staging → External view/edit layer
```

当前实现说明：
- 当前 Phase 1 代码已经把 Git 可见文件当作权威工件。
- 当前运行时尚未实现原始设计中描述的完整 gate-to-commit 编排。
- 因此，“写入 Git 可见文件”应理解为与权威模型对齐的基线，而不是完整的 authority-promotion 流程。

### 2.4 以协议为中心的系统形态

目标架构仍然是一个全局 `aw-agent`，通过以下接口暴露共享核心：

- MCP Server
- CLI `aw`
- REST API

当前实现说明：
- 共享核心服务已实现于 `src/agent_wiki/`
- 当前唯一已实现的 transport 是 `src/agent_wiki/transports/cli/app.py` 中的最小 CLI stub
- MCP 与 REST 仍然是设计目标，而不是已落地的运行时接口
- `aw-agent` 目前还不是一个真实的长驻服务进程，因为 `aw serve` 尚未存在

### 2.5 风险 gate 随 truth-zone 风险升级

设计仍然假设：

- A 级用于 raw/source capture
- B 级用于 atom/synthesis/dispute 更新
- C 级用于 principle 与其他高风险写入

当前实现说明：
- gate 分类已存在
- 完整的 `max_gate` enforcement 与 gate-check 执行仍不完整
- 因此当前基线不应被视为已具备完整策略治理能力

---

## 3. 已确认的架构决策

### 3.1 权威与数据流

以下仍是当前有效的需求基线：

1. **Workspace 是唯一真源（SSOT）。** 所有知识的权威版本存放在 workspace 中，外部视图（包括 Obsidian）是面向人的读写展示层，不是平级数据源。
2. Git 保存 workspace 的持久化权威：页面、`purpose.md`、配置、`MANIFEST.jsonl`、`retrieval_index.jsonl` 以及审计/日志工件。
3. Workspace 保存 runtime、pending、proposal、index 和 conflict 状态。
4. `.agent-wiki/` 保存本地运行时状态，不提交到 Git。
5. `retrieval_index.jsonl` 是 Phase 1 的粗检索基线；FTS5 retrieval.db 是 v0.2 的加速索引（不进 Git，可 rebuild）。
6. 向量检索仍是可选能力。

**数据流向：**

```text
Agent 写入 → workspace（唯一真源）
人在 Obsidian 编辑 → pull-view 回流 workspace
workspace → push-view → Obsidian（全量可浏览/可编辑视图）
```

**扩展架构（终态设计，Phase 1 不实现）：**

- N 个个人 workspace（私有，默认不可见）
- M 个团队 workspace（权限分级：共享/分权限只读/分权限读写）
- 跨 workspace 查询保留 source wiki 可追踪性
- 设计原则：以终为始，先做个人闭环

### 3.2 多 wiki 与身份

以下仍是基线决策：

1. 全局 `registry.yaml` 是权威配置。
2. 跨 wiki 身份使用 `wiki_id:doc_id`。
3. 支持 shared wiki，并可限制 page type。
4. Cross-wiki 检索必须保留 source wiki 可追踪性。

当前实现说明：
- registry 加载已在 `src/agent_wiki/bootstrap/registry_loader.py` 中实现
- multi-wiki 与 shared wiki 的 smoke 行为已有测试覆盖
- cross-wiki query 聚合已在 `src/agent_wiki/application/query.py` 中实现

### 3.3 目录与状态布局

设计基线保持为：

- `purpose.md`
- `config.yaml`
- `pages/`
- `MANIFEST.jsonl`
- `retrieval_index.jsonl`
- `review_queue.jsonl`
- `query_outcomes.jsonl`
- `operation_log.jsonl`
- `approval_log.jsonl`
- `.agent-wiki/`

当前实现说明：
- 当前运行时直接使用这些工件
- `pages/` 当前仍以 `pages/{doc_id}.md` 方式写入
- path 与 identity 分离仍是设计要求，但尚未在代码中完全实现

### 3.4 Agent 能力分层

当前有效的 tier 模型仍然是：

- T1 Full：ingest/query/lint/sync/cron/propagation 目标能力
- T2 Standard：ingest/query/lint，依赖外部调度
- T3 Minimal：仅 query/capture_raw

当前实现说明：
- 当前实现的服务边界与该模型方向一致
- 由于 MCP/REST 尚未实现，所有 Agent 尚无 transport-level 的完整策略执行
- 因此 tier 模型应被理解为目标策略形态，而不是已完全封装好的运行时边界

### 3.5 摄入与编译

仍然要求：

- `capture_raw` 不得直接修改 truth zone
- `compile_update` 修改 `atom` 与 `synthesis`
- 高风险 principle 写入必须经过 proposal/approval
- analyze/apply 分离仍是目标模式

当前实现说明：
- `capture_raw` 已实现
- `compile_update` 的 analyze/apply 已以简化形式实现
- principle 写入当前走本地 proposal/approval smoke path
- analyze 当前仍是启发式，而不是完整的 evidence-planning engine

### 3.6 外部视图与同步

目标设计仍然是：

- external view 是面向人的读写层
- reverse sync 先流入 workspace
- gate failure 阻止 authority promotion，而不是阻止 workspace 可见性

当前实现说明：
- 当前 Phase 1 的 sync 仍是 copy-based markdown sync，提供 `status`、`pull-view` 与 `push-view`
- adapter-driven reverse sync 与 gate-to-Git promotion 仍是后续工作

### 3.7 Pending 查询策略

仍然要求：

- raw pending 可以被查询
- truth-zone pending 默认排除，除非显式传入 `include_pending=true`

当前实现说明：
- truth-zone pending 的 opt-in 查询行为已在 `src/agent_wiki/application/query.py` 中实现
- raw pending indexing 相比完整设计仍是简化版

### 3.8 真值证据规则

仍然要求：

- truth-zone 的 `source_refs` 必须通过 `wiki_id:doc_id` 指向受跟踪的 raw 页面
- 外部 URL 与附件不能直接充当 truth-zone `source_refs`

当前实现说明：
- 对标准 compile update，这条规则今天已经生效
- shared-wiki approval flow 当前存在一个针对 principle/shared smoke path 的定向 bypass
- 这个 bypass 应被视为临时的 Phase 1 简化，而不是设计规则的放宽
- 在任何 production-style 的 C 级治理声明成立之前，这个 bypass 都应被移除或明确阻断

### 3.9 检索与回答格式

仍然要求：

- provider-pluggable retrieval
- 词法检索作为最低保障路径
- 三层输出：
  - L1 answer
  - L2 reasoning/context
  - L3 proof/evidence

当前实现说明：
- 词法基线与分层输出已实现
- 向量路由、load budget 与更丰富的 provider orchestration 尚未实现

### 3.10 反馈与 weekly review 闭环

仍然要求：

- query usage 应反向驱动维护
- feedback 应创建 review work，而不是自动编辑页面
- weekly review 应提出建议，而不是自动执行

当前实现说明：
- `feedback.py` 会追加 `query_outcomes.jsonl` 并创建 review queue 项
- `weekly_review.py` 目前产出最小摘要，并基于 queue reason 提供建议动作
- 更丰富的 query-outcome policy 与 multi-signal review synthesis 仍是未来工作

### 3.11 Review queue

Review queue 在概念上仍支持 conflict、missing evidence、pending gate fix、signal candidate、feedback issue、principle proposal、dispute 等类型。

当前实现说明：
- 当前 queue item 形状仍然很小：`item_type`、`doc_id`、`reason`、`status`
- 更丰富的 lifecycle、assignment、priority、`wiki_id` 与 resolution 语义仍是设计目标
- 因此当前 queue shape 应被视为过渡态，而不是可支撑严肃多 wiki 治理的最终形态

### 3.12 C 级确认与审计

仍然要求：

- 高风险变更先 proposal
- 存在显式 approval 路径
- 执行后写入 approval log

当前实现说明：
- `src/agent_wiki/application/approvals.py` 中已实现最小本地 proposal/approval 流程
- approval log 会写入 `approval_log.jsonl`
- 设计仍预期后续通过 MCP 实现更丰富的人机交互

### 3.13 身份与权限

设计仍要求由 knowledge agent 解析身份，而不是让调用者通过 request parameter 控制身份。

当前实现说明：
- identity、permission 与 gate helper 模块已存在
- 当前 identity resolver 仍接受并优先使用显式 actor 字段
- 完整的 `max_gate` enforcement 仍然缺失
- 这些都是待修复的实现缺口，而不是设计变更

### 3.14 传输层与命名

命名基线仍然是：

- Python package：`agent_wiki`
- CLI：`aw`
- service process：`aw-agent`
- MCP server：`agent-wiki`

当前实现说明：
- package 名称已实现
- CLI entry point 已在 `pyproject.toml` 中配置
- 完整 CLI command surface、MCP 与 REST 仍不完整
- `aw-agent` 当前应被理解为目标服务身份，而不是已经可部署的长驻进程

---

## 4. 当前 Phase 1 实现状态

当前 `src/agent_wiki/` 下的实现基线覆盖：

- bootstrap 与 registry loading
- raw capture
- compile update
- propagation
- lexical query
- cross-wiki query smoke behavior
- lint
- sync status/pull/push
- feedback
- weekly review
- approvals
- manifest/retrieval/pending/review/runtime repositories

这意味着项目已经具备一个**可工作的 Phase 1 基线实现**，但仍不是设计终局中描述的完整协议化架构。

### 4.1 Release-readiness blockers

在项目对外声称具备更强的 production-ready multi-agent governance 之前，以下项目应被视为阻塞项：

- 可信身份优先级必须高于 caller-supplied actor fields
- 中央化 `max_gate` enforcement
- 面向 Git-first governance 的 authority-promotion / commit orchestration
- 页面级 sensitivity schema + retrieval/response filtering
- 可部署的 `aw serve` 进程与真实的长驻 `aw-agent` 运行路径

---

## 5. 差异映射：设计目标 vs 当前实现基线

| Area | Design target | Current implementation | Status |
|---|---|---|---|
| Transport surface | MCP + CLI + REST | minimal CLI stub only | Not Yet Implemented |
| Gate enforcement | policy-complete A/B/C checks and `max_gate` enforcement | gate classification only, partial service separation | Partial |
| Identity safety | caller cannot override resolved identity | explicit actor fields still override metadata | Divergence |
| Propagation recovery | rollback + stale markers + mirror handling | direct write/append model only | Phase 1 Simplification |
| Authority promotion | gate-checked commit orchestration to Git authority | Git-visible file writes only, no full orchestrator yet | Divergence |
| Retrieval runtime | provider-pluggable, load-policy aware, budgeted | lexical baseline + layered output | Phase 1 Simplification |
| Sync | adapter-driven reverse sync and gate-to-authority path | markdown file copy modes | Phase 1 Simplification |
| Review queue | rich workflow schema | minimal queue entries | Phase 1 Simplification |
| Query outcomes | query path logs outcomes directly | feedback path records outcomes | Simplified |
| Page sensitivity | schema-backed page access policy with query filtering | no page-level sensitivity enforcement yet | Not Yet Implemented |

---

## 6. 建议阅读顺序

如果你想理解项目在今天的真实状态，建议按如下顺序阅读：

1. `README.md`
2. `docs/design.md`
3. `core/schema.md`
4. `docs/agent-differences.md`
5. `src/agent_wiki/`
6. `tests/`

这样可以依次获得：
- 面向项目的总体摘要
- 架构意图
- 操作契约预期
- 各 Agent 差异
- 当前实现
- 已验证行为

---

## 7. 最后说明

本文档应被视为**需求与架构基线**，而不是“所有目标能力都已经实现”的声明。当当前实现小于设计目标时，设计仍然是权威，当前运行时应被视为 Phase 1 的基线或简化版本。

尤其是：身份优先级、`max_gate`、authority-promotion / commit orchestration、页面级 sensitivity filtering，以及可部署的 service surface，仍然是更强治理声明成立前最重要的未解决阻塞项。
