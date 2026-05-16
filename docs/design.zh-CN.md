# Agent Wiki 架构设计

> 通用多 Agent 环境知识系统  
> v1.1 — 2026-05-16  
> 状态：已与当前 Phase 1 实现基线对齐的设计目标

---

## 0. 第一性原理

**“变聪明”不在于积累更多知识，而在于改善行为。**

从控制论角度看：知识库是被控对象，Agent 行为是输出，反馈闭环是控制器。没有反馈，任何开环系统无论内部多复杂，都不会真正变得更好。

**核心问题：从知识到行为改进的闭环在哪里？**

### 四个核心判断

1. **Compile before retrieve** —— 方向正确。但编译产物必须是可维护、可追踪、可复用的知识工件，而不只是更花哨的摘要。
2. **Skillify 是设计原则，不是后补功能** —— 知识从进入系统时起就应携带路由语义。
3. **混合检索是调用骨架，不是优化项** —— 由已配置的粗检索 provider 找候选页，再通过整页/分段加载获得理解，并用分层展示控制上下文成本。Phase 1 默认是词法检索；向量检索是可选 provider。
4. **Schema 必须是操作契约，而不是方向性宣言** —— 它必须明确告诉 LLM/Agent：新来源到来时该更新哪些页、哪些矛盾要标记、何时创建、何时修订。

---

## 1. 架构

```text
Git authority
  → local workspace and runtime state
  → capture_raw / compile_update / query / lint / sync / feedback / weekly-review / approvals
  → reviewable JSONL artifacts and markdown pages
  → thin agent transports and adapters
```

### 架构意图

目标系统仍然是以协议为中心的 `aw-agent`：在共享核心服务之上暴露 MCP、CLI 与 REST。仓库设计仍然假设：

- 一个共享核心引擎
- 可插拔的存储、检索与内容适配器
- Git-first authority
- 显式的传播、维护与审批流
- 通过薄客户端供多 Agent 访问

### 当前 Phase 1 实现基线

当前 `src/agent_wiki/` 中的实现，已经交付了一个基于文件系统与 JSONL 的基线运行时，活跃子系统包括：

- `src/agent_wiki/bootstrap/registry_loader.py`
- `src/agent_wiki/application/capture_raw.py`
- `src/agent_wiki/application/compile_update.py`
- `src/agent_wiki/application/query.py`
- `src/agent_wiki/application/linting.py`
- `src/agent_wiki/application/sync.py`
- `src/agent_wiki/application/feedback.py`
- `src/agent_wiki/application/weekly_review.py`
- `src/agent_wiki/application/approvals.py`
- `src/agent_wiki/application/propagation.py`
- `src/agent_wiki/infrastructure/storage/manifest_repo.py`
- `src/agent_wiki/infrastructure/retrieval/retrieval_index.py`
- `src/agent_wiki/infrastructure/runtime/*`

### Phase 1 简化说明

当前运行时**尚未**暴露完整的 MCP 或 REST 传输层。已实现的 transport surface 仍然只是 `src/agent_wiki/transports/cli/app.py` 中的最小 CLI stub。下文保留 MCP/REST 作为目标架构，但所有与实现有关的描述都明确限定在当前 `src/agent_wiki/` 基线上。

---

## 2. 数据流完整性（Anti-Island）

**设计原则：Write = Propagate。一次写入在所有下游工件更新前都不算完成。**

### 2.1 目标传播模型

目标传播仍然包括：

- 页面写入
- manifest 更新
- retrieval/provider index 更新
- 条件性的 review queue 创建
- 日志与审计轨迹
- 最终的外部镜像/同步处理

### 2.2 已实现的传播模型

当前 `src/agent_wiki/application/propagation.py` 已支持：

- 将 raw 页面写入 `pages/{doc_id}.md`
- manifest append/upsert
- retrieval index append
- `log.md` append
- compile update 的 `operation_log.jsonl` append
- 证据相关情形下的 `review_queue.jsonl` append
- 非法 raw 回退到 `.agent-wiki/pending_manifest.jsonl`

### 2.3 当前写入流

#### A 级 raw capture

实现位置：
- `src/agent_wiki/application/capture_raw.py`
- `src/agent_wiki/application/propagation.py`

流程：

```text
capture_raw
  → validate allowed page type
  → validate doc_id shape
  → committed path: page + manifest + retrieval_index + log
  → invalid doc_id path: pending_manifest only
```

#### B 级 compile update

实现位置：
- `src/agent_wiki/application/compile_update.py`
- `src/agent_wiki/application/propagation.py`

流程：

```text
compile_update
  → analyze existing doc_id / problem_cluster
  → validate allowed page type
  → validate source_refs against raw manifest entries
  → write page
  → upsert manifest
  → append retrieval card
  → append operation log
  → optionally append review queue item
  → append log.md
```

#### C 级 proposal / approval smoke path

实现位置：
- `src/agent_wiki/application/approvals.py`

流程：

```text
propose
  → write .agent-wiki/proposals/{proposal_id}.json
approve
  → load proposal
  → propagate compiled write
  → append approval_log.jsonl
```

### 2.4 与目标设计的差距

以下传播能力仍然只是设计目标，而不是当前实现：

- 页面写入与 manifest 写入之间的显式回滚
- `index_stale` 标记
- `mirror_pending` 标记
- 独立于 retrieval index 的 provider-index refresh
- mirror push 与重试逻辑
- conflict snapshot 与自动 reverse-propagation queueing

这些**不是矛盾**，而是更完整 anti-island 设计在 Phase 1 中的简化版本。

---

## 3. Phase Gate 系统

架构仍然假设存在 A/B/C/D 分阶段 gate。

### 目标 gate 意图

- **A** —— raw/source capture 校验
- **B** —— truth-zone 的 atom/synthesis/dispute 变更
- **C** —— principle 晋升、shared 高风险写入、裁决
- **D** —— 长周期维护与演化质量

### 当前实现状态

- gate 分类已存在于 `src/agent_wiki/infrastructure/identity/gates.py`
- A/B/C 行为在服务边界上有部分体现：
  - raw capture 路径
  - compile update 路径
  - approvals 路径
- 完整 gate 策略执行**尚未**实现：
  - permissions 中的 `max_gate` 尚未被执行
  - 目前还没有中央 gate-check service
  - 也还没有 route-test 或 content-quality gate 执行

### 设计说明

设计文档仍然保留 gate 模型。当前代码应被理解为一个沿着 A/B/C 分离方向前进的基线，而不是已经完整交付的 gate engine。

---

## 4. 以协议为中心的 Agent 接入

### 4.1 目标传输层架构

目标架构仍然是：

```text
Knowledge Agent / aw-agent
├─ MCP Server
├─ CLI / aw
├─ REST API
└─ Shared core services
```

### 4.2 当前实现状态

当前已实现的表面：

- Python package `agent_wiki`
- `src/agent_wiki/transports/cli/app.py` 中的最小 CLI stub

当前代码库中**尚未**实现：

- MCP transport package 与 server
- REST transport package 与 app
- 完整工作流的 CLI command surface

### 4.3 Agent identity 与权限

当前已实现的组件：

- `src/agent_wiki/infrastructure/identity/resolver.py`
- `src/agent_wiki/infrastructure/identity/permissions.py`
- `src/agent_wiki/infrastructure/identity/gates.py`

### 重要偏差

- 目标设计要求：请求参数不得覆盖已解析出的身份。当前实现仍然在 `IdentityContext` 中接受显式 actor 字段，并优先于 metadata 使用。这是一个**真实实现缺口**，不是设计变更，因此设计文档仍应把“调用者不可覆写身份”视为目标行为。
- 完整的 `max_gate` enforcement 也仍然缺失。身份覆写与 gate 缺失一起，应该被视为在做更强多 Agent 安全声明前必须解决的治理阻塞项。

---

## 5. 核心引擎到 `src/agent_wiki/` 的映射

### 5.1 Bootstrap 与配置

- `src/agent_wiki/bootstrap/registry_loader.py` —— 把 YAML registry 解析成 `RegistryConfig`、`WikiConfig` 等模型
- `src/agent_wiki/bootstrap/container.py` —— 最小服务装配

### 5.2 Capture 与 compile

- `src/agent_wiki/application/capture_raw.py`
- `src/agent_wiki/application/compile_update.py`
- `src/agent_wiki/application/propagation.py`

### 5.3 Retrieval 与 query

- `src/agent_wiki/application/query.py`
- `src/agent_wiki/infrastructure/retrieval/retrieval_index.py`

### 5.4 Maintenance loop

- `src/agent_wiki/application/linting.py`
- `src/agent_wiki/application/sync.py`
- `src/agent_wiki/application/feedback.py`
- `src/agent_wiki/application/weekly_review.py`

### 5.5 Approvals 与高风险路径

- `src/agent_wiki/application/approvals.py`

### 5.6 持久化与运行时工件

- `src/agent_wiki/infrastructure/storage/manifest_repo.py`
- `src/agent_wiki/infrastructure/runtime/pending_state.py`
- `src/agent_wiki/infrastructure/runtime/review_queue.py`
- `src/agent_wiki/infrastructure/runtime/operation_log.py`

---

## 6. 把查询质量视为一等公民

### 为什么这必须被显式写出来

此前设计对治理、authority 与 risk gate 的强调仍然正确，但 Tao 的批评对真实的 Phase 1 运行环境也是对的：**Phase 1 是 1 个人配合 5 个 Agent，而不是 5 个人共享 1 个受治理平台。**

这会改变优先级排序。

一个知识系统如果不能稳定返回有用答案，再强的 gate 模型也无济于事。对真实的 Phase 1 工作流来说，**查询质量就是生命线**：

- 检索弱，知识库就不会被信任
- 知识库不被信任，人和 Agent 就会绕过它
- 一旦被绕过，治理与审计路径就失去意义，因为系统已经不在闭环中

### 三份评审的合并立场

- **Codex 是对的**：identity、`max_gate`、provenance 与 deployment truthfulness 都是真实架构缺口。
- **CC 是对的**：这些缺口必须被文档明确标成 blocker，而不是轻描淡写。
- **Tao 也是对的**：对 Phase 1 的可用性来说，retrieval quality 与 Obsidian-connected workflow 的优先级高于治理完整性。

因此，综合后的架构立场是：

1. **Phase 1 先保证可用性** —— retrieval quality 与 Obsidian-connected workflow 是 P0，因为它们决定系统是否会被真正使用。
2. **Phase 1.5 / 更强声明再补治理硬化** —— 身份优先级、`max_gate`、sensitivity filtering 与 authority promotion 仍然是做更强多 Agent 治理声明前的 blocker。
3. **不要把二者混成一个优先级桶** —— “必须能用” 与 “必须可治理” 都是真实需求，只是发生在采用曲线的不同阶段。

### 查询质量的目标要求

Phase 1 不应再只把 retrieval 描述成 lexical baseline，而应描述成一个**可用的 lexical baseline**，具备明确质量要求：

- 中文分词支持，而不是默认按空格切词
- 模糊关键词匹配，处理 near-miss query term
- title/topic/problem-cluster/keyword 的加权排序
- 每次 query path 都记录 hit/miss instrumentation
- 对重复低价值查询进行显式跟踪，作为维护信号

### Phase 1 实现状态

今天已实现：

- 基于 `retrieval_index.jsonl` 的词法检索
- 启发式 query classification
- L1/L2/L3 分层响应组装
- 查询输出中的 dispute caveat
- 可选纳入 pending truth-zone

尚未实现、但已提升为架构优先项：

- 中文感知分词
- 模糊词法匹配
- 超出当前简单 baseline 的加权排序
- 在 query path 中一等公民化的 hit/miss tracking
- 当 hit 质量随时间退化时的 drift detection

### 设计含义

这意味着设计文档不应再把 query quality 当作治理之下的实现细节。对 Phase 1 来说，retrieval quality 是核心架构的一部分，因为它决定反馈闭环是否会收到有意义的使用数据。

---

## 7. 知识生命周期自动化

### 为什么自动化很重要

当前 raw → atom/synthesis 的 compile 链路在架构上是成立的，但 Tao 的批评也成立：对于真实 Agent 组合来说，`compile_update` 的实际门槛过高。

在当前 Phase 1 现实中：

- T3 Agent 可以 capture raw，但不能 compile
- Hermes 还没有通过 MCP 接入
- Claude Code 虽然有能力，但 session 是临时的
- 人类很可能无法持续手工维护 compile 边界

如果没有自动化，最可能的失败模式是：

```text
raw accumulates → compile_update is under-triggered → atom/synthesis stay sparse → query quality stagnates
```

这会重现这个项目最初试图解决的失败模式。

### 目标生命周期自动化模型

因此，即便完整治理硬化还未落地，Phase 1 也应包含一个**轻量自动化层**来推动知识演化。

#### 7.1 Auto-compile suggestions

当同一 `topic` 或 `problem_cluster` 下的 raw 页面累积超过阈值时，系统应自动创建 compile suggestion。

目标行为：

- 用类似“同一 topic 下 N 个 raw 页面”的阈值规则
- 创建 review queue / suggestion entry，而不是盲目直接改 truth-zone 页面
- 把建议路由给 T2+ 执行者或 approval path

这样可以让 compile 链路持续运转，而不要求完全自治。

#### 7.2 Fast feedback loop

weekly review 仍然有用，但它更适合趋势分析，而不是唯一控制回路。

目标行为：

- 连续三次低分或低价值 query outcome 触发 compile suggestion
- hit rate 持续下滑时触发 lint + reindex 或 retrieval-quality 调查
- weekly review 作为慢回路看趋势，fast feedback 负责即时漂移

#### 7.3 由 `purpose.md` 驱动的知识演化

Tao 对 `purpose.md` 被低估的批评也是对的。

`purpose.md` 应被视为整个 wiki 的意图锚点，而不只是元数据：

- 影响 query priority 与 ranking
- 当多个 raw cluster 竞争注意力时影响 compile direction
- 影响无关内容的归档或降权
- 为 C 级判断某个 principle 是否属于该 wiki 提供依据

否则，系统很容易退化成一个带 gate 的文件管理器，而不是目的驱动的知识系统。

#### 7.4 Obsidian-connected adoption path

对 Phase 1 的实际采用来说，Obsidian sync 不应被描述成一个可有可无的外部集成，而应被视为实际的人类入口路径。

这意味着 Phase 1 应当瞄准：

- ObsidianAdapter 是真实交付物，而不只是设计占位
- 外部编辑能以生命周期闭环可感知的方式流回 workspace
- 至少做到：Obsidian edit → raw capture path → compile suggestion / compile trigger

#### 7.5 候选关系作为差异化能力

4-Signal relation system 也应被重新定义。

如果没有关系发现能力，这个系统在结构上会很像一个受治理的文件仓库。Candidate relations 是它成为知识引擎的关键因素之一。

Phase 1 至少应瞄准：

- co-occurrence signal
- cross-reference signal

这些 signal 可以先写入 suggestions 工件，而不是直接修改权威关系，直到经过 review。

### Phase 1 实现状态

今天已实现：

- raw capture 路径
- 手动/显式 compile update 路径
- feedback capture
- weekly review summary

尚未实现、但已提升为优先项：

- auto-compile suggestions
- 由重复低价值查询触发的 fast feedback
- purpose 驱动的 ranking / compile prioritization
- 超越文件拷贝的 ObsidianAdapter reverse flow
- 低成本 candidate relation discovery

---

## 8. 检索运行时

### 目标检索设计

目标运行时仍然是：

1. 分类 query type
2. 通过已配置 provider 做 coarse retrieval
3. 按 `wiki_id:doc_id` 聚合
4. 按 policy 加载
5. 组装分层的 L1/L2/L3 上下文
6. 带 dispute awareness 返回结果

### 已实现基线

当前 `src/agent_wiki/application/query.py` 中的 query baseline 已实现：

- 启发式 query-type classification
- 基于 `retrieval_index.jsonl` 的词法检索
- `include_pending=True` 时可扫描 pending truth-zone
- 通过 manifest/pending manifest 做过滤
- 基于分数和 manifest priority 的简单排序
- 从顶部页面内容生成 L1 answer
- 当 `review_status=disputed` 时在 L2 context 中附带 dispute caveat
- 用 manifest `source_refs` 生成 L3 proof
- 通过 `CrossWikiQueryService` 做 cross-wiki fan-out

### Phase 1 简化说明

当前运行时尚未实现：

- 超出 lexical baseline 的 provider routing
- vector retrieval plugin 集成
- 显式的 load-policy 执行
- query budget enforcement
- query service 内部自动写入 query_outcome

当前 query outcome 仍通过独立 feedback workflow 记录，而不是由 `QueryService` 自动记录。

---

## 9. Sync 与外部视图

### 目标设计

目标 Phase 1 架构仍然假设：

- external views 是面向人的界面层
- external edits 先回流到 workspace
- gate-check 阻止 Git commit，而不是阻止可见性
- adapters 负责把外部格式归一化

### 已实现基线

当前 `src/agent_wiki/application/sync.py` 的实现是刻意最小化的：

- `status` 列出 workspace 中的 markdown pages
- `pull-view` 把配置的外部路径中的 `*.md` 复制到 `pages/`
- `push-view` 把 `pages/*.md` 复制到配置的外部路径

### 偏差说明

这是一个**简化的 Phase 1 文件系统同步**，而不是完整的 adapter-driven reverse sync。设计文档应继续描述更丰富的 adapter-based sync 作为目标模型，但必须明确指出：当前实现只是 copy-based placeholder，尚无 gate-to-commit path。

---

## 10. Review queue、feedback 与 weekly review

### 目标设计

review loop 应把 query usage、缺失证据、维护压力与高风险知识演化连接起来。

### 已实现基线

feedback 与 weekly review 当前都是简单的 JSONL 流程：

- `src/agent_wiki/application/feedback.py`
  - 向 `query_outcomes.jsonl` 追加 feedback
  - 当证据缺失或存在重写目标时，创建 `feedback_issue` queue item
- `src/agent_wiki/application/weekly_review.py`
  - 读取 `review_queue.jsonl` 与 `query_outcomes.jsonl`
  - 汇总 queue 数量与 feedback 数量
  - 根据 queue reason 生成 suggested actions

### Phase 1 简化说明

当前 queue item 比目标 review queue 契约小得多。它们还不包含原始设计中描述的完整状态机、assignment metadata、priority 或 conflict snapshot。

---

## 11. Shared wiki 与 cross-wiki 行为

### 已实现 smoke coverage

当前代码与测试已经展示了以下 Phase 1 smoke-path 行为：

- multi-wiki registry loading
- shared wiki `allowed_page_types` 限制
- cross-wiki lexical query aggregation
- C 级 proposal/approval 写入路径

这些行为由以下测试验证：

- `tests/test_multi_wiki.py`
- `tests/test_shared_wiki.py`
- `tests/test_cross_wiki_query.py`
- `tests/test_approvals.py`

### 设计说明

这些 smoke coverage 证明了接口方向是可行的，但它们还不是原始 protocol-centered 设计中所描述的 transport-complete、policy-complete 系统。

shared-wiki approval bypass 对 raw-backed provenance 的放宽应被视为临时 smoke-path exception。它不能被理解为对正常 truth-zone evidence rule 的放松，并且在任何 production-style C-level governance claim 之前都必须被移除或显式阻断。

---

## 12. 相对于 Design v1.0 的已知偏差

| Area | Design target | Current implementation | Status |
|---|---|---|---|
| Transport surface | MCP + CLI + REST | minimal CLI stub only | Not Yet Implemented |
| Identity resolution | caller cannot override resolved identity | explicit actor fields still override metadata | Divergence to fix |
| Gate enforcement | operation risk + `max_gate` policy | gate classification exists, full enforcement missing | Partial |
| Authority promotion | gate-checked commit orchestration to Git authority | Git-visible file writes only, no full orchestrator yet | Divergence to fix |
| Propagation failure handling | rollback + stale markers + mirror state | direct append/write only | Phase 1 Simplification |
| Retrieval runtime | provider-pluggable, load-policy aware | lexical baseline with layered output | Phase 1 Simplification |
| Sync | adapter-driven reverse sync + gate/commit path | copy-based markdown sync | Phase 1 Simplification |
| Review queue | rich workflow schema | minimal append-only queue items | Phase 1 Simplification |
| Query outcome loop | query service logs outcomes directly | feedback service records outcomes | Simplified |
| Page sensitivity | schema-backed page access policy with query filtering | no page-level sensitivity enforcement yet | Not Yet Implemented |

---

## 13. 给读者的建议

阅读本文件时：

- 把架构章节视为系统长期目标形态
- 把实现说明视为今天已交付的 `src/agent_wiki/` Phase 1 基线
- 把偏差表视为当前尚待补齐部分的权威地图

这样可以稳定设计，又不假装当前实现已经是完整目标系统。

---

*Design v1.1 已按当前实现基线对齐。请结合 `core/schema.md`、`docs/requirements-and-architecture.md` 与测试一起使用，以进行当前状态评审。*

---

## 14. Phase 1 优先级综合结论

三份评审意味着，Phase 1 的优先级栈比“纯治理优先”或“纯便利优先”都更细致。

### P0 — 必须先可用

这些决定系统会不会被真实使用：

- 把词法基线的查询质量提升到可用水平
  - 中文分词
  - 模糊匹配
  - 基于关键词/topic 的加权排序
  - query path 中的 hit/miss tracking
- Obsidian-connected workflow
  - 把 ObsidianAdapter 作为真实的 Phase 1 交付物
  - 让 reverse flow 能进入知识生命周期闭环

### P1 — 必须让知识持续演化

这些防止 raw capture 变成死路：

- 当 raw 页面按 topic/problem cluster 累积时自动生成 compile suggestion
- 由重复低价值查询触发的 fast feedback
- 由 purpose 驱动的 ranking、compile direction 与 health evaluation
- 低成本 candidate relations，尤其是 co-occurrence 与 cross-reference signals

### P2 — 必须支撑更强的治理声明

这些仍然是在做更强多 Agent 治理或更广泛部署声明前必须补齐的：

- 可信 identity precedence
- 中央化 `max_gate` enforcement
- 页面级 sensitivity policy 与 filtering
- 更丰富的 review queue lifecycle records

### P3 — 必须补完 authority 与 service 路径

这些用于补齐运维成熟度：

- authority-promotion / commit orchestration
- `aw serve` 与真实的 service deployment path
- 更广的 DFX readiness criteria 与运维 runbook

### 设计含义

这不是对 Codex 或 CC 的否定，而是综合：

- **Codex/CC 正确指出了更强声明成立前的治理阻塞项。**
- **Tao 正确指出了真实 Phase 1 可用性的采用阻塞项。**

因此，设计文档必须同时把这两件事写清楚：治理很重要，但如果 query quality 与 Obsidian-connected workflow 失败，其余部分就永远不会真正进入用户的知识闭环。

---

## 15. DFX 设计

> Agent Wiki 的可部署性、可靠性、安全性、可观测性、性能、可维护性与可扩展性  
> v1.0 — 2026-05-16  
> 状态：已与当前 Phase 1 实现基线对齐的设计目标

### 15.1 范围与阅读说明

本节补充以下文档：

- `README.md`
- `core/schema.md`
- `docs/design.md`
- `docs/agent-differences.md`

本文从七个 DFX 维度定义 Agent Wiki 的非功能设计。每个章节都会区分：

- 随架构演进应保持稳定的**目标设计**
- 当前仓库中已经实现或已明确具备落地基础的 **Phase 1 基线**
- 在更强多 Agent / 网络化场景下需要补强的 **Phase 2 方向**

这里继续沿用仓库中的同一条规则：

**不要把目标架构与当前实现混成一个故事。** 目标解释系统要去哪里；实现说明今天已经有什么。

---

### 15.2 可部署性（Deployability）

#### 设计目标

Agent Wiki 应能在三种部署形态下易于安装、运行、升级与回滚：

1. 本机单用户知识服务
2. 容器化自托管服务
3. 面向网络暴露的多用户服务

部署方式必须保持核心架构不变：一个共享的 `aw-agent` 进程、Git 作为 authority、本地 workspace 作为 runtime state，以及 MCP / CLI / REST 作为同一核心之上的薄接口。

#### 关键决策

##### 决策：作为独立 agent 进程运行，而不是嵌入式库

**理由：** 项目架构假设一个共享知识引擎为多个客户端与多种 transport 提供服务。长驻进程更适合承载 MCP service hosting、approval routing、background maintenance 与 identity resolution，而不是把逻辑散落到各个客户端内部。

**备选方案：** 把 wiki 逻辑直接嵌入每个 agent adapter 或 client library 中。

**不采用原因：** 这会复制核心行为，削弱 identity 与 gate enforcement，也会让 propagation、audit 与 transport consistency 更难保证。

##### 决策：把本机部署作为 Phase 1 的主力运行模式

**理由：** 当前项目目标是在一台机器上运行个人多 Agent 知识系统。本机安装与本机进程管理在保留整体架构的同时，能把运维复杂度降到最低。

**备选方案：** 一开始就先做网络服务。

**不采用原因：** Phase 1 还不需要完整的远程认证、反向代理或团队级运维姿态。

##### 决策：使用 registry YAML + 环境变量 + `.env` 的 12-factor 风格配置

**理由：** Agent Wiki 既需要明确表达多 wiki 拓扑，也需要环境相关覆盖配置。registry 表达知识拓扑；环境变量表达端口、token、存储路径等部署关注点。

**备选方案：** 硬编码 per-agent config，或只使用一个巨大的单体配置文件。

**不采用原因：** 这会把 transport/runtime 问题与知识拓扑耦合在一起，也会削弱主机部署和容器部署的可移植性。

##### 决策：以 Git branch 隔离作为知识状态发布与回滚的主要边界

**理由：** Git 已经是 authority of record。基于分支的 rollout 与 rollback 与仓库的核心 authority 模型天然一致，也方便快速回退已提交的知识状态。

**备选方案：** 把数据库原生 migration/version 作为主发布边界。

**不采用原因：** 这会削弱 Git 的 authority 角色，并使 Phase 1 运维故事更复杂。

#### Phase 1 实现状态

当前已实现或明显对齐的部分：

- 通过 `pyproject.toml` 已具备 Python package 安装路径，`README.md` 中也已有本地 editable install 的说明。
- CLI 入口已在 `src/agent_wiki/transports/cli/app.py` 中以最小 stub 形式存在。
- `src/agent_wiki/bootstrap/registry_loader.py` 已实现基于 registry 的配置加载。
- 当前运行时模型已经区分了 Git 提交工件与 `.agent-wiki/` 下的本地 runtime state。
- 仓库根目录已有 `Dockerfile`，支持单包部署方向。

当前基线尚未实现：

- 生产级 MCP server 进程
- 完整的 `aw serve` 长驻服务 surface
- `launchd` / `systemd` 服务管理示例
- 面向可选 retrieval provider 的 docker-compose 打包
- 带反向代理、TLS 与 OIDC 的 REST 部署

#### Phase 1 发布就绪说明

当前基线在 package 安装与总体架构方向上已经成立，但还不能被视为文档中所描述的长驻 `aw-agent` 服务。要支撑更强的部署声明，项目仍需要真实的 `aw serve` 进程、可健康检查的服务行为，以及保护远程或多 Agent 运行的治理控制。

#### Phase 2 规划

Phase 2 应补充：

- 一等公民的长驻 `aw-agent` 服务，并启用 MCP 与 REST
- 基于 nginx 或 caddy 的 HTTPS 反向代理部署
- 面向远程访问的 OIDC 身份与会话处理
- 更清晰的主机安装与容器发布包装
- 面向 token、证书与 per-wiki policy 的网络安全配置分层

#### 与其他 DFX 维度的关联

- **可靠性：** 部署形态决定重启行为与回滚速度。
- **安全性：** 网络部署会扩大认证与传输安全边界。
- **可观测性：** 服务包装需要暴露健康检查与结构化日志。
- **可维护性：** 一个可部署的共享核心进程比多个嵌入式实现更容易演进。
- **可扩展性：** 部署方式不应依赖某一个 transport 或 adapter。

---

### 15.3 可靠性（Reliability）

#### 设计目标

Agent Wiki 应在崩溃、部分传播失败与检索能力退化时保持知识完整性。系统失败方式必须可观测、可修复，并与 Git-first authority 模型一致。

#### 关键决策

##### 决策：把写入传播完整性视为可靠性的核心边界

**理由：** 在这个系统中，一次写入不只是一个页面编辑。它还必须更新 manifest、retrieval index、日志与 queue state。可靠性因此围绕“传播是否完整一致”展开。

**备选方案：** 只要页面文件写成功，就算成功。

**不采用原因：** 这会制造 knowledge islands，并导致页面内容与检索/审计状态之间出现静默漂移。

##### 决策：使用分层回滚模型：pending state、stale markers，然后是 Git revert

**理由：** 不是每次失败都应该强制执行硬回滚。pending state 是提交前缓冲，stale marker 是软回滚信号，而 Git revert 仍然是 authority 级恢复手段。

**备选方案：** 任意传播失败都立即硬回滚。

**不采用原因：** 这过于粗暴，会丢弃可恢复工作，也不符合 workspace 与 authority 分离的设计。

##### 决策：当可选 retrieval 组件失败时，查询应优雅降级

**理由：** Phase 1 的 query capability 不应依赖向量基础设施。lexical retrieval 是必备基线，因此即使可选 retrieval provider 失败，系统仍应保持可用。

**备选方案：** 向量或 richer retrieval 不可用时整体查询失败。

**不采用原因：** 会把可选增强能力变成单点运行风险。

##### 决策：依赖 Git remote 与可文本恢复的 JSONL 工件做备份与恢复

**理由：** 这与 Git-first 模型一致，也能让核心恢复路径保持可审计、可人工检查。JSONL manifests 与 indexes 都是可检查、可重建的。

**备选方案：** 只依赖数据库原生恢复。

**不采用原因：** Phase 1 应保持 file-first，并在没有专用存储工具时仍可恢复。

#### Phase 1 实现状态

今天已实现或部分实现的部分：

- `src/agent_wiki/application/propagation.py` 已有 propagation orchestration。
- 非法 raw capture 通过 `.agent-wiki/pending_manifest.jsonl` 提供 pending fallback。
- `src/agent_wiki/application/query.py` 与 `src/agent_wiki/infrastructure/retrieval/retrieval_index.py` 已提供 lexical retrieval 的降级运行模式。
- `MANIFEST.jsonl`、`retrieval_index.jsonl`、`operation_log.jsonl` 与 `review_queue.jsonl` 等 JSONL 工件符合文本可恢复模型。
- 当前仓库设计已经默认 Git remote 是天然备份边界。

设计目标尚未完整落地的部分：

- 显式七项 F1-F7 健康模型
- 传播失败后的自动 stale marker
- 自动重试编排与连续两次失败后暂停
- 传播各阶段之间的事务式回滚
- 长驻服务重启监管文档

#### Phase 2 规划

Phase 2 应补充：

- 明确的 propagation integrity state 与 stale-marker 生命周期
- 带上限重试与暂停行为的 retry controller
- 面向长驻 MCP / REST 服务进程的更强崩溃恢复
- 更明确的多写者并发协调
- 面向 mirrors 与 external views 的更强一致性校验

#### 与其他 DFX 维度的关联

- **可部署性：** 重启与回滚策略依赖部署形态。
- **安全性：** 可审计性与可回滚性可以降低错误写入的影响范围。
- **可观测性：** 可靠性故障必须变成健康信号与告警。
- **性能：** 重试与重建不能压垮正常查询/写入路径。
- **可维护性：** 明确的失败状态能简化修复与运维推理。

---

### 15.4 安全性（Security）

#### 设计目标

Agent Wiki 应保护敏感知识内容，通过身份与能力约束 Agent 行为，并确保高风险操作走更强审批路径。安全模型必须符合项目的信任边界：Phase 1 本机优先，Phase 2 强化远程与团队控制。

#### 关键决策

##### 决策：把认证、授权与操作风险 gate 分离建模

**理由：** 当前架构已经区分“调用者是谁”“具有什么能力层级”“当前操作属于什么风险等级”。这样既能让低风险使用保持顺畅，也能为高风险写入保留明确边界。

**备选方案：** 只有一个扁平的 allow/deny 权限系统。

**不采用原因：** 它无法足够清晰地表达 A/B/C gate 模型与 T1/T2/T3 能力模型。

##### 决策：Phase 1 采用 loopback-local trust + local token；Phase 2 迁移到 OIDC

**理由：** 本机部署可以在最小暴露面下保留显式身份；只有在网络暴露或团队共享时，才需要 OIDC 级别远程认证。

**备选方案：** 一开始就要求完整远程认证体系。

**不采用原因：** 这会给个人知识工作流带来不必要运维负担。

##### 决策：敏感性必须落实到页面级，并在查询阶段执行

**理由：** 仓库预计会保存 API keys、内部笔记等敏感知识。只按 repository 或 wiki 级过滤太粗；页面级敏感性才能让检索和输出更安全。

**备选方案：** 把整个 wiki 当成统一可信内容。

**不采用原因：** 无法满足多 Agent 与混合敏感级别内容并存的场景。

##### 决策：为每次重要操作保留可审计文本日志

**理由：** 任何改变知识状态的操作，都应能追溯到 Agent 身份、目标文档与时间戳。

**备选方案：** 只保留易失性的运行时审计事件。

**不采用原因：** 这不足以支撑事后审查、调试与信任恢复。

##### 决策：隔离 content adapter 执行，并在系统边界做输入校验

**理由：** adapter 会摄入外部内容，是最可能引入畸形或恶意输入的边界。

**备选方案：** 把所有 markdown/content 输入都当成可信内部数据。

**不采用原因：** 外部内容天然属于系统边界，应按不可信输入处理。

#### Phase 1 实现状态

今天已实现或已有部分表达的部分：

- `src/agent_wiki/infrastructure/identity/resolver.py`、`permissions.py` 与 `gates.py` 已存在身份与权限辅助逻辑。
- raw capture、compile update 与 approvals 三条服务边界已体现 A/B/C 分层。
- `approval_log.jsonl` 与 `operation_log.jsonl` 已提供审批与编译写入的审计记录。
- 当前已对 `doc_id`、`allowed_page_types` 与 `source_refs` 做有限输入校验。
- 项目文档中已明确高风险审批应走 MCP 或等价确认路径。

相对目标设计的重要缺口：

- 当前实现中，已解析身份仍可能被显式 actor 字段覆盖；`docs/design.md` 已将其列为真实实现缺口
- 尚无完整的 `max_gate` enforcement engine
- 尚未实现页面级 `sensitivity` schema 与查询过滤
- 当前基线尚未实现 git-crypt 工作流或加密内容处理
- 因网络服务尚未落地，尚无传输层 TLS / mTLS
- 目前还没有 adapter sandbox runtime

#### Phase 2 规划

Phase 2 应补充：

- 面向远程访问的 OIDC 认证
- 必要时用于服务间信任的 TLS 与 mTLS
- 在检索与响应组装阶段强制执行页面级敏感性过滤
- 始终走 canonical approval path 的高风险审批路由
- 在 confidential 内容场景下支持受保护存储流程的仓库加密模式
- 更严格的 content-adapter sandbox 与验证 profile

#### 与其他 DFX 维度的关联

- **可部署性：** 远程部署会扩大安全边界。
- **可靠性：** 审计日志与安全回滚有助于控制错误或未授权写入的影响。
- **可观测性：** 可疑访问与重复 gate 失败应成为可观测信号。
- **可维护性：** 安全规则应位于共享核心策略层，而不是散落在每个 Agent wrapper 中。
- **可扩展性：** 每个新增 adapter 与 transport 都必须接入同一套身份与策略系统。

---

### 15.5 可观测性（Observability）

#### 设计目标

Agent Wiki 应同时对机器与人类可诊断。运维者应能回答：

- 发生了什么
- 为什么某次查询或传播失败
- 知识完整性是否正在漂移
- 哪些维护动作值得优先处理

#### 关键决策

##### 决策：同时保留结构化机器日志与人类可读日志

**理由：** JSONL 日志适合自动化与检查工具；Markdown 日志适合 Git-native 工作流中的快速人工审阅。

**备选方案：** 只保留人类可读日志，或只保留结构化日志。

**不采用原因：** 单一格式会削弱工具能力或人工可读性中的一端。

##### 决策：健康检查应反映传播完整性，而不只是进程是否存活

**理由：** 一个还在运行的进程，不等于一个健康的知识系统。健康状态应描述下游工件是否仍然同步。

**备选方案：** 只提供“服务在线/离线”的检查。

**不采用原因：** 这无法反映系统真实的正确性边界。

##### 决策：weekly review 属于可观测性的一部分，而不只是维护流程

**理由：** 对知识系统来说，可观测性还包括系统是否被有效使用。低信号查询、堆积的 queue 项与缺失证据，都是操作信号。

**备选方案：** 把 weekly review 仅视作人工治理流程。

**不采用原因：** 这会把可执行的行为反馈排除在运维视图之外。

#### Phase 1 实现状态

今天已经实现：

- propagation 会写入人类可读的 `log.md`
- compile 操作会写入结构化的 `operation_log.jsonl`
- approvals 会写入结构化的 `approval_log.jsonl`
- feedback 提交会写入结构化的 `query_outcomes.jsonl`
- `src/agent_wiki/application/weekly_review.py` 已实现 weekly review summary generation
- `src/agent_wiki/application/linting.py` 已实现最小 lint 与一致性检查

相对目标设计尚未实现：

- 专门的 `aw health` 命令/端点，以及正式的七项检查报告
- 查询延迟、命中率、传播成功率、stale 数量等指标导出
- 针对重复传播失败或 stale 堆积的阈值告警
- 在 query 路径内部自动记录 query outcome
- 围绕 queue 压力、external sync drift 与 retrieval provider 健康的更丰富可观测性视图

#### Phase 2 规划

Phase 2 应补充：

- 一等公民的 health endpoint / command
- 持久化指标采集：延迟、命中质量、传播完整性与 queue 健康
- 面向重复传播失败与 stale 累积的告警 hook
- 横跨 MCP、CLI 与 REST 的更强调用链追踪
- 能把使用模式与维护动作联系起来的更好 operator summary

#### 与其他 DFX 维度的关联

- **可靠性：** 可观测性让传播与恢复问题可行动。
- **安全性：** 审计日志与访问轨迹本身就是安全模型的一部分。
- **性能：** 延迟与检索指标是调优决策的基础。
- **可维护性：** 清晰诊断能降低调试成本。
- **可扩展性：** 可插拔 provider 也必须暴露可比的健康与使用信号。

---

### 15.6 性能（Performance）

#### 设计目标

Agent Wiki 应在保证正确性与可追踪性的前提下，对本机 Agent 工作流保持足够快的响应。性能目标应服从当前 Phase 1 的真实运行模型：文件后端、本机优先、以单用户为主、检索 provider 可插拔。

#### 关键决策

##### 决策：把词法检索作为必备基线，并优先优化它

**理由：** 词法检索是 Phase 1 的保证路径，也是 richer retrieval 失败后的降级路径，因此它必须足够快，能支撑日常本机使用。

**备选方案：** 只优化向量检索，因为它可能有更好的召回率。

**不采用原因：** 向量检索在 Phase 1 是可选能力，不能成为唯一性能叙事。

##### 决策：在 Phase 1 保持 raw capture 与 compile update 的轻量文件写路径

**理由：** 大多数 Phase 1 操作只会写有限数量的 markdown 与 JSONL 工件，因此核心写路径应该是可预测、低延迟的。

**备选方案：** 提前引入更重的持久层与分布式协调机制。

**不采用原因：** 这会过早为 Phase 2 需求优化，并增加当前基线复杂度。

##### 决策：Phase 1 使用乐观并发；显式锁留给 Phase 2

**理由：** 当前项目范围以单用户或弱协调使用为主，已经足够。过早引入强锁会让系统在还没有真实多写者压力之前就承担额外复杂度。

**备选方案：** 从第一天就实现显式锁。

**不采用原因：** 对本机优先基线来说，这是过早的协调成本。

#### Phase 1 实现状态

当前基线特征：

- 查询路径是基于 `retrieval_index.jsonl` 的文件后端词法检索。
- 写入路径是受限的文件系统与 JSONL append/update 流程。
- 已有 cross-wiki query，但仍是简单的 fan-out 基线。
- 最低功能不依赖任何重型 retrieval provider。

本次设计任务给出的目标数值：

- 本机 JSONL 词法检索 < 100ms
- 开启可选向量 provider 时，向量检索 < 500ms
- 纯文件操作的 `capture_raw` < 50ms
- 有限传播工作的 `compile_update` < 200ms

当前尚未实现测量或强制约束：

- 与这些目标绑定的 benchmark harness
- 运行时显式 query/load budget
- 面向大库的 retrieval index 分段加载
- 向量库 LRU 缓存与 provider budget 控制
- 团队级场景下的并发写控制

#### Phase 2 规划

Phase 2 应补充：

- 显式性能基准与回归检查
- 分段 index 与大规模知识库检索策略
- provider 感知的缓存与 query budget 控制
- 面向多写者场景的更强并发控制
- 基于指标的 retrieval、propagation 与 cross-wiki fan-out 调优

#### 与其他 DFX 维度的关联

- **可靠性：** provider 失败时的降级查询仍必须可用。
- **可观测性：** 性能主张需要指标支撑才可信。
- **可维护性：** 更简单的数据路径更容易调优和推理。
- **可扩展性：** 新 provider 必须接入统一的 hit 与 budget 模型。

---

### 15.7 可维护性（Maintainability）

#### 设计目标

Agent Wiki 应在持续演进中保持架构清晰。可维护性依赖于稳定共享核心、明确边界、可靠测试，以及能区分目标设计与当前行为的文档体系。

#### 关键决策

##### 决策：保持分层架构与单向依赖

**理由：** 现有结构已经把 application、domain、infrastructure、bootstrap 与 transports 分开，有助于让核心策略脱离 adapter 与部署表面。

**备选方案：** 使用 feature-first 模块，把 transport、storage 与 domain 决策混在一起。

**不采用原因：** 这会模糊项目最关键的 core / adapter 边界。

##### 决策：把设计文档当作活的架构文档，而不是事后营销材料

**理由：** 未来贡献者与 reviewer 需要同时理解目标架构与当前实现缺口。

**备选方案：** 只把文档改写成“今天实现了什么”。

**不采用原因：** 这会抹掉系统目标形态，让 Phase 2 决策失去一致评估基线。

##### 决策：使用里程碑导向测试与结构化 lint 验证行为

**理由：** 当前仓库已经以 M1-M6 为骨架组织测试，结构一致性检查也与 file-backed 架构天然契合。

**备选方案：** 主要依赖临时性的人工测试。

**不采用原因：** 随着 propagation、approvals 与 multi-wiki 行为变复杂，这种方式无法扩展。

##### 决策：schema versioning 与 migrations 必须显式化

**理由：** 文件格式与运行时元数据必然会演进。显式 migration 能在不掩盖格式变化的前提下保持连续性。

**备选方案：** 默默发生格式漂移。

**不采用原因：** 这会让旧知识工件语义不清，也更难修复。

#### Phase 1 实现状态

今天已经实现：

- `src/agent_wiki/` 下的分层代码组织
- `README.md` 中记录的 32 个通过测试，覆盖 M1-M6 基线
- README、schema、design、requirements 与 agent-differences 等核心文档集合
- manifest/page 与 manifest/index 一致性的最小 lint 检查

相对目标设计尚未完整实现：

- 完整的 schema migration framework
- 更丰富的 lint 覆盖：断裂引用、孤立页面、frontmatter 完整性等
- 完整的 CLI / MCP / REST 对等性测试
- 更完整的 operator runbook 与部署流程文档

#### Phase 2 规划

Phase 2 应补充：

- 显式 schema versioning 与 migration utilities
- 扩展后的结构与语义 lint 套件
- 跨 transport 共享的更强 contract tests
- 更完整的部署、恢复与审批运维文档
- 面向 adapter 与 retrieval provider 作者的扩展说明

#### 与其他 DFX 维度的关联

- **可部署性：** 可维护的打包与配置能降低运维负担。
- **可靠性：** 清晰结构更容易正确实现故障恢复。
- **安全性：** 集中且可测试的策略逻辑更安全。
- **可扩展性：** 只有可维护，插件点才不会演变成分叉实现。

---

### 15.8 可扩展性（Extensibility）

#### 设计目标

Agent Wiki 应能通过新增 transport、adapter、retrieval provider 与 agent profile 来扩展，而不改变核心知识模型。可扩展性必须建立在共享契约之上，而不是制造平行实现。

#### 关键决策

##### 决策：所有主要集成都依赖共享核心之上的接口

**理由：** 项目已经明确存储、content adapters、retrieval、embeddings 与 external views 都应保持可插拔。稳定的核心契约可以防止功能扩张带来行为碎片化。

**备选方案：** 直接在每个 transport 或每个 agent adapter 里实现各自逻辑。

**不采用原因：** 这会复制 propagation、permissions 与 query semantics。

##### 决策：把 content adapter 作为格式归一化边界

**理由：** Obsidian、Plain Markdown、Notion 与未来 view 都应映射成统一内部表示，而格式特定信息只保存在 adapter metadata 中。

**备选方案：** 让每个外部系统决定各自的内部语义。

**不采用原因：** 检索、传播与策略逻辑会因此变成系统特定实现。

##### 决策：让 transport 在同一审批与策略路径之上可互换

**理由：** MCP、CLI 与 REST 应是传输层替代品，而不是彼此独立的策略引擎。

**备选方案：** 每个 transport 自己维护审批与权限行为。

**不采用原因：** 这会让风险处理不一致，也更难验证。

#### Phase 1 实现状态

当前设计与代码中已部分对齐：

- registry-driven multi-wiki 模型天然提供了扩展点
- transport 边界在概念上已存在，当前 CLI stub 位于 `src/agent_wiki/transports/cli/app.py`
- retrieval provider 抽象已存在于设计层，词法检索是 Phase 1 基线
- `docs/agent-differences.md` 已记录 agent adaptation strategy

当前仓库基线尚未实现：

- 一等公民的 `ContentAdapter` 插件运行时
- 通过统一 registry 接入的多 retrieval provider 实现
- MCP 与 REST transport 实现
- 针对 T1/T2/T3 模板的显式 agent-profile 注册流程

#### Phase 2 规划

Phase 2 应补充：

- 正式的 adapter interfaces 与 registration mechanisms
- 在统一 hit contract 下挂接多个 retrieval provider
- 完整的 MCP / CLI / REST transport surface
- 带可复用 tier template 的更强 agent identity profiles
- 确保外部集成始终保持 thin 的扩展指南

#### 与其他 DFX 维度的关联

- **可维护性：** 只有共享核心保持一致，可扩展性才成立。
- **安全性：** 所有扩展都必须继承相同的身份、策略与 gate 规则。
- **性能：** provider 插件必须进入统一的 budget 与指标体系。
- **可部署性：** 扩展的打包方式必须同时适配本机与网络部署。

---

### 15.9 跨 DFX 总结

这七个 DFX 维度是刻意耦合在一起的：

- **可部署性** 决定核心运行在哪里。
- **可靠性** 决定写入与查询在什么条件下仍然可信。
- **安全性** 决定谁可以看到什么、修改什么。
- **可观测性** 决定运维者如何发现漂移与故障。
- **性能** 决定系统是否适合真实 Agent 工作流。
- **可维护性** 决定架构是否能在不失去清晰性的情况下继续演进。
- **可扩展性** 决定新工具能否加入系统而不分叉核心逻辑。

对 Agent Wiki 来说，这些不是附着在产品上的次要属性，而是产品定义本身的一部分，因为系统的价值依赖于可信的多 Agent 知识操作，而不只是文件存储。
