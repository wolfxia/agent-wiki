# wiki-schema.md — Agent-Agnostic Operation Contract

> Version: v1.2  
> Date: 2026-05-16  
> Status: 与当前 Phase 1 实现基线对齐的操作契约
>
> 本文件是 **Schema Layer（Schema 层）** —— 它定义任何 Agent 应当如何摄入、编译、路由、lint、晋升和维护 wiki。  
> 它不是方向性宣言，而是**操作契约**。
>
> 状态说明：该契约仍然是目标操作模型。当前 `src/agent_wiki/` 实现只强制执行其中一个子集，且会在下文中被明确标记为 **Phase 1 Implementation Profile (Current)**。

---

## 0. 范围与角色

本文件约束以下执行者：
- `wiki-ingest`（任意 Agent 的摄入适配器）
- `wiki-query`（任意 Agent 的查询适配器）
- `wiki-lint`（任意 Agent 的 lint 适配器）
- `dream-cycle`（定期维护）
- 人类编辑者（在触发自动维护前）

它**不**约束：
- 领域特定业务逻辑
- 向量存储实现细节
- 编辑器 UI / 插件配置

如果 `purpose.md` 回答的是“什么值得关注”，那么 `wiki-schema.md` 回答的是：
**“系统应如何维护这些知识对象？”**

---

## 1. 核心哲学

1. **Compile before retrieve** —— 在摄入/编译阶段预先组织，而不是把组织工作推迟到查询阶段。
2. **Raw immutable, compiled mutable** —— raw 是不可变原料；atom/synthesis/principle 是可维护工件。
3. **Skillified knowledge** —— 每个知识对象从创建起就必须携带路由语义，而不是事后补上。
4. **Prefer revise over create** —— 新材料应优先修订已有编译页，而不是先创建新页。
5. **Proof beats fluency** —— 编译后的 truth zone 中不允许没有来源支撑的流畅断言。
6. **Rollback beats drift** —— 当运行时或编译链不稳定时，应回滚到最近的稳定状态。
7. **Write = propagate** —— 一次写入在所有下游工件更新完成之前都不算完成（anti-island）。

---

## 2. 页面类型体系

### 2.1 raw
- 用途：原始笔记、学习输出、外部材料摘录
- 生命周期：不可变
- 默认写入模式：append-only
- 默认查询角色：`proof_only`
- 默认 `load_policy`：`proof_only`

### 2.2 atom
- 用途：针对单一 problem cluster 的收敛知识
- 生命周期：可修订，可追加认知演化时间线
- 默认查询角色：`fact_lookup` / `concept_explain`
- 默认 `load_policy`：`section_then_page`

### 2.3 synthesis
- 用途：跨多个 problem cluster 的结构化综合
- 生命周期：可重写，优先修订
- 默认查询角色：`trend_scan` / `compare_tradeoff` / `decision_support`
- 默认 `load_policy`：`full_page`

### 2.4 principle
- 用途：元原则、决策框架、跨主题判断规则
- 生命周期：严格晋升 / 可降级
- 默认查询角色：推理支架，不能成为唯一证据来源
- 默认 `load_policy`：`full_page`

### 2.5 类型体系原则
- raw 永不删除。
- 编译页必须能追溯到 raw。
- principle 必须反向链接到 atom 或 synthesis。
- **Problem cluster** 是收敛单元，不是 topic 名称。

---

## 3. 规范身份契约

1. 每个页面必须有稳定的 `doc_id`。
2. Path 不是身份；重命名/移动不改变 `doc_id`。
3. 路径变更应记录在 `legacy_paths[]` 中。
4. `canonical_uri` 指向 workspace 中的权威位置。
5. 外部存储镜像路径不参与身份定义。
6. Retrieval 单元必须引用 `doc_id`，而不是只引用 path。

### 当前实现的重要说明

当前实现仍在多个服务中以 `pages/{doc_id}.md` 的形式读写页面。这是 **Phase 1 implementation simplification**，不是契约变更。契约仍然要求 path 与 identity 分离。

---

## 4. Frontmatter 与 Manifest 契约

### 4.1 目标公共字段
所有页面最终都应携带：
- `doc_id`
- `page_type`
- `topic`
- `problem_cluster`
- `query_types`
- `route_priority`
- `load_policy`
- `review_status`
- `confidence`
- `updated`
- `source_refs`
- `sensitivity`
- `access_policy`

### 4.2 类型专属目标字段

#### raw
- `evidence_strength`
- `superseded_by`
- `when_to_use`
- `compiled_into`
- `ingest_origin`

#### atom
- `solves`
- `applicable_when`
- `not_for`
- `depends_on`
- `source_coverage`
- `supports`

#### synthesis
- `answers`
- `preferred_for`
- `related_principles`
- `freshness_sla_days`
- `depends_on`
- `related_pages`

#### principle
- `principle_scope`
- `applies_to_topics`
- `use_for`
- `misuse_risks`
- `counterexamples`
- `promotion_basis`
- `review_required`

### 4.3 字段一致性规则
- `query_types` 不能为空。
- `route_priority` 必须在预定义枚举中。
- `load_policy` 必须与 page type 匹配。
- `review_status` 不得缺失。
- `source_refs` 必须指向 manifest 中存在的来源。
- `sensitivity` 必须属于已文档化的枚举，例如 `public`、`internal`、`confidential`。
- 当页面级访问策略与 wiki 默认值不同，必须提供 `access_policy`。

---

## 5. 摄入与编译契约

### 5.1 目标摄入模型
新来源通过 Two-Step ingest 进入系统：

#### Step 1: Analyze
必须回答：
1. 属于哪个 `topic`？
2. 属于哪个 `problem_cluster`？
3. 与哪些已有 atom/synthesis 相关？
4. 是在补充证据、补充结构，还是引入新问题？
5. 是否与已有断言冲突？

#### Step 2: Decide
只允许四种结果：
- `append_raw`
- `update_atom`
- `update_synthesis`
- `create_review_item`

#### Step 3: Record
必须更新以下工件：
- `MANIFEST.jsonl`
- `retrieval_index.jsonl`
- 已配置 retrieval provider 的索引
- `log.md`
- `review_queue.jsonl`（当存在 conflict/dispute 时）

### 5.2 禁止操作
- 不得把 raw 内容直接写入 principle truth zone。
- 新来源到达时，不得跳过分析直接创建 synthesis。
- 未更新 manifest 时，不得写入编译页。

### 5.3 当前实现概况

今天在 `src/agent_wiki/` 中已实现：
- `capture_raw` 写入 raw 页面、manifest 条目、retrieval 卡片和 `log.md` 条目。
- 非法 raw `doc_id` 会回退到 `.agent-wiki/pending_manifest.jsonl`。
- `compile_update.analyze` 当前通过简单的 `doc_id` / `problem_cluster` 启发式判断 create vs revise。
- `compile_update.apply` 当前支持 `atom` 与 `synthesis` 写入、校验 `allowed_page_types`、校验 `source_refs`，并写入 operation log。
- C 级 principle 写入当前走 proposal + approval 流程，而不是直接 compile。

尚未实现的完整契约部分：
- 完整 evidence-chain 分析输出
- 来自 analyze 的 route/gate planning 工件
- 更深的 contradiction resolution 逻辑
- 超出当前简化字段的 manifest/frontmatter parity enforcement

---

## 6. Update vs Create 规则

### 6.1 优先修订的场景
- problem cluster 已存在
- 新来源只是在补充证据
- 新来源强化已有结论
- 新来源只带来 section-level 增量

### 6.2 创建新 atom 的条件
- 同一 topic 下出现稳定的新 problem cluster
- 与已有 atom 相似但不等价
- 至少有 2-3 个 raw 来源可以支撑

### 6.3 创建新 synthesis 的条件
- 需要跨 atom/problem-cluster 的整合
- 问题已达到趋势/比较/决策层级
- atom 本身不足以回答高层问题

### 6.4 晋升为 principle 的条件
- 在 2+ topic 中具有解释力
- 不被现有证据推翻
- 具有明确适用边界与反例
- 最好有人类验证

### 6.5 当前实现说明

当前 `CompileUpdateService.analyze()` 只根据 `doc_id` 与 `problem_cluster` 区分 create vs revise。该行为应被视为基线启发式，而不是最终判断矩阵。

---

## 7. 矛盾与溯源规则

### 7.1 Provenance 枚举
- `extracted`
- `inferred`
- `ambiguous`

### 7.2 必须进入 review queue 的情况
- 新来源明确推翻已有编译断言
- 同一概念在不同 synthesis 中出现冲突结论
- principle 缺少支持页面的反向链接
- 同一 problem cluster 存在两个互斥答案

### 7.3 disputed 规则
- `disputed` 必须包含 `dispute_reason`
- 命中 disputed 页面时，查询输出必须带 caveat
- disputed 项在解决前不得晋升为 principle

### 7.4 无溯源禁止规则
- 没有 `source_refs` 的断言不得进入编译 truth zone
- 未验证洞察可以进入 timeline，但必须标记为 `inferred` 或 `ambiguous`

### 当前实现概况

今天已实现：
- `compile_update.apply` 会拒绝 `source_refs` 无法解析到现有 raw manifest 条目的编译写入，除非 shared-wiki approval path 明确绕过 raw-source 要求。
- `query` 会在 manifest 条目带有 `review_status=disputed` 与 `dispute_reason` 时展示争议 caveat。

这个 shared-wiki bypass 应被视为**临时实现例外**，不能被视为对正常 truth-zone 证据规则的放宽，也**不得进入 production C-level approval**。

尚未实现：
- 更丰富的 contradiction-state transition
- queue 工作流中的 dispute 生命周期管理
- 自动 contradiction discovery

---

## 8. Retrieval 契约

### 8.1 Query 类型
固定六类：
- `fact_lookup`
- `concept_explain`
- `trend_scan`
- `compare_tradeoff`
- `decision_support`
- `proof_trace`

### 8.2 固定检索管线
1. 分类 `query_type`
2. 通过已配置 retrieval provider 在 `retrieval_index` 上进行粗检索
3. 按 `wiki_id:doc_id` 聚合
4. 按 `load_policy` 加载
5. 组装分层上下文
6. 输出答案并记录 outcome

### 8.2.1 Retrieval provider 基线
- Retrieval 是 provider-based，而不是强制 vector。
- Phase 1 默认 provider 是基于 `retrieval_index.jsonl` 的词法搜索。
- 向量检索是可选增强 provider，不得成为最小查询能力的前提。
- Provider 输出必须使用统一的 normalized retrieval hit shape，并引用 `wiki_id:doc_id`。

### 8.3 分层展示
- **L1** Answer layer：可直接使用的答案条目
- **L2** Reasoning layer：为什么相关、有哪些争议、依赖哪些页面
- **L3** Proof layer：原始证据、`source_refs`、raw snippet

### 8.4 Load budget
- 首轮最多 3 个 full-page 编译页
- raw evidence 最多 2 组，除非 `proof_trace`
- principle 不得成为唯一上下文来源

### 8.5 Dispute-aware 规则
当命中 disputed 页面时：
- 输出必须明确指出存在争议
- reason 字段必须可见
- 没有 proof layer 时不得给出强结论

### 当前实现概况

今天在 `src/agent_wiki/application/query.py` 中已实现：
- 启发式 query-type classification
- 基于 `retrieval_index.jsonl` 的词法检索
- 通过 `include_pending=True` 的 pending truth-zone 可选纳入
- 基于词法分数与 manifest 派生优先级的简单排序
- L1/L2/L3 结果组装
- 通过 `CrossWikiQueryService` 进行 cross-wiki 聚合

尚未实现：
- 显式 `load_policy` 执行
- retrieval budget
- vector-provider dispatch
- 在 query 执行过程中自动记录 query outcome

---

## 9. Review Queue 契约

### 9.1 目标 queue item 最小字段
- `item_id`
- `wiki_id`
- `doc_id`
- `item_type`
- `status`
- `content_state`
- `priority`
- `reason`
- `created_at`
- `source_refs`
- `assigned_to`
- `resolved_by`
- `resolved_at`

### 9.2 状态流
- `open` → `assigned` → `in_progress` → `resolved` → `archived`

### 9.3 Content state
`content_state` 独立描述知识断言状态，不依赖 queue 工作流状态：
- `stub`
- `ambiguous`
- `disputed`
- `resolved`
- `stale`
- `pending_gate_fix`

### 9.4 Item types
常见 `item_type` 值：
- `conflict`
- `missing_evidence`
- `pending_gate_fix`
- `signal_candidate`
- `feedback_issue`
- `principle_proposal`
- `dispute`

### 当前实现概况

当前实现只写入一个**最小** review queue 形状：
- `item_type`
- `doc_id`
- `reason`
- `status`

该形状当前由以下模块产生：
- `src/agent_wiki/application/propagation.py`
- `src/agent_wiki/application/feedback.py`

这个最小形状应被视为 **Phase 1 transitional simplification**，而不是长期 queue 契约。更丰富的 queue 契约仍然是 serious multi-wiki governance、assignment、conflict handling 与 review lifecycle tracking 的实现目标。

当运行时采用更丰富的 queue 形状时，必须为旧的最小 JSONL 条目提供 migration 或 compatibility handling。

---

## 10. 生命周期与晋升规则

### 目标生命周期
- `raw` → `compiled` → `verified` → `disputed` / `stale` → `archived`

### 目标 stale 规则
- stale 是计算得出的派生属性，而不是手工状态
- 通过 `last_referenced` 与 `freshness_sla_days` 计算

### 目标晋升规则
- raw → atom/synthesis：进入编译覆盖
- compiled → verified：route test 稳定、证据充分、争议关闭
- synthesis/atom → principle：满足可迁移解释力条件

### 当前实现说明

当前运行时只实现了 principle proposal/approval 的 smoke path，并未实现上述完整的 promotion/demotion 生命周期语义。

---

## 11. Lint 规则

### 目标 lint 检查
最终必须检查：
1. frontmatter 完整性
2. `doc_id` 唯一性
3. `source_refs` 有效性
4. `query_types` 非空
5. `load_policy` 合法性
6. `review_status` 与 review_queue 一致性
7. 依赖链无断裂
8. retrieval_index 条目与编译页对应
9. disputed 必须有 `dispute_reason`
10. `compiled_into / superseded_by` 链一致性

### 11.1 数据流完整性检查（目标）

| Check | Detects | On Failure |
|-------|---------|-----------|
| manifest doc_id ↔ actual files 1:1 | 页面变了但索引不知道 | Alert + repair |
| vectors all have `doc_id` + unified `model` | 页面变了但搜索找不到 | Alert + mark `index_stale` |
| retrieval_index has cards for all compiled pages | 粗搜索没有数据源 | Alert + trigger rebuild |
| No `index_stale` markers >24h | 索引与页面不同步 | Alert + trigger rebuild |
| No `mirror_pending` markers >24h | 外部存储不同步 | Alert + trigger sync |
| query_outcomes consumed within 7 days | 知识被使用但没有反馈 | Alert |
| External store ↔ workspace diff < 5% | 人类编辑未回流 | Alert + trigger reverse propagation |

### 当前实现概况

当前 `src/agent_wiki/application/linting.py` 中的 `LintService` 只检查：
- 每个 manifest 条目都有 `canonical_uri`
- 每个 manifest `canonical_uri` 都指向存在的页面
- 每个 retrieval index 条目都有对应的 manifest 条目

这是一个刻意缩小的 Phase 1 baseline。更完整的 lint 契约仍然是目标状态。

---

## 12. Logging 与审计

### 目标日志
- `log.md` 记录 ingest、revise、merge、promote、dispute、archive 与重要 query outcome
- `query_outcomes.jsonl` 保存 append-only 的反馈 / 效果历史
- approval 操作写入持久审计记录

### 当前实现概况

当前运行时工件：
- propagation 写入的 `log.md`
- compile update 写入的 `operation_log.jsonl`
- approvals 写入的 `approval_log.jsonl`
- feedback 提交写入的 `query_outcomes.jsonl`

尽管当前运行时形状仍然最小，这些工件依旧遵循 append-only 原则。

---

## 13. 人类覆盖规则

### 必须有人类确认的情况
- principle 晋升 / 降级
- 跨 topic 的大规模合并
- disputed adjudication（高影响结论）
- workspace ↔ external store conflict merge

### 可以自动执行的情况
- raw ingest
- atom/synthesis timeline append
- retrieval view rebuild
- vector re-embedding
- review item creation
- lint 与 route test 执行

### 当前实现说明

当前代码只为高风险 principle 写入实现了本地 proposal/approval smoke path。更广义的人类覆盖路由仍然是设计目标。

---

## 14. Phase 1 实现概况（当前）

当前 `src/agent_wiki/` 中已执行的契约子集包括：

### 今天已实现
- registry-driven multi-wiki loading
- 同时支持 committed 与 pending 路径的 raw capture
- 面向 `atom` 与 `synthesis` 的 compile update
- 带 L1/L2/L3 输出的 lexical retrieval
- query 中的 dispute caveat
- 可选纳入 pending truth-zone 的查询
- 最小 manifest persistence
- 最小 lint 检查
- 最小 sync file-copy 模式
- feedback → review queue 创建
- weekly review 摘要生成
- principle 写入的 proposal/approval smoke path
- shared wiki page-type restrictions
- cross-wiki query smoke 行为

### 尚未从完整契约中实现的部分
- 完整 frontmatter 覆盖
- 完整 queue item schema
- MCP/REST transport parity
- 带 `max_gate` enforcement 的 gate engine
- vector-provider routing
- adapter-driven reverse sync 与 gate-to-Git flow
- stale marker 与 mirror marker recovery
- richer contradiction workflow

---

*本文件仍然是操作契约。当当前实现小于该契约时，契约依然描述的是目标架构与行为边界。*
