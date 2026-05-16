# Agent Wiki 初步需求与架构设计

> 状态：Brainstorming 阶段阶段性产物，用于 Claude Code / 人类评审需求和方案思路。  
> 日期：2026-05-16  
> 推荐方案：协议中心型 Knowledge Agent  
> 注意：本文是需求与架构决策汇总，不是最终实现计划。

---

## 1. 项目背景和目标

Agent Wiki 是一个通用的、agent-agnostic 的统一知识库系统，目标是让多个不同能力边界的 AI Agent 可以单独或共同使用同一套知识资产。

核心问题不是“把文档存在哪里”，而是建立一套可编译、可检索、可审计、可演化、可被多 Agent 协作使用的知识系统。

### 1.1 理念来源

项目参考两类核心来源：

1. 微信文章中的知识系统理念：
   - LLM Wiki：`Raw Sources → Wiki → Schema` 的极简编译哲学。
   - GBrain：工程化混合检索，采用 `Chunk 确认 → 整页加载 → 分层呈现`，并预留知识图谱演化。
   - Obsidian-Wiki：Skill 驱动知识和多 Agent 支持。
   - 核心论点：`Skillify` 是知识范式转变，不只是功能特性。

2. `nashsu/llm_wiki` 参考实现：
   - TypeScript/Rust 实现。
   - Two-Step Ingest：`Analyze → Generate`。
   - 4-Signal Graph 与 Louvain 社区检测。
   - `purpose.md` 与 review system。

### 1.2 目标 Agent

Phase 1 需要设计支持 5 类 Agent：

| Agent | 定位 | 关键能力 | 主要限制 |
|---|---|---|---|
| Hermes Agent | T1 Full | 内置 cron、memory_search、飞书/微信、rich toolset | 需要把知识持久化在文件/仓库而非短记忆中 |
| OpenClaw | T1 Full | 类 Hermes，skill prompt、内置 cron、飞书 | 执行模型比 Hermes 更受限 |
| Claude Code | T2 Standard | CLAUDE.md 注入、Bash、持久 workspace | 无内置调度、无内置向量 |
| Codex | T3 Minimal | CLI、full-auto、代码执行 | 无持久状态、冷启动 |
| OpenCode | T3 Minimal | `opencode run`、provider-agnostic | 无持久状态、冷启动 |

### 1.3 Phase 1 目标

Phase 1 的硬目标是实现一个完备的个人多 Agent 知识库体系，形成稳定日用闭环：

```text
capture_raw → compile_update → query → lint → sync → weekly-review
```

Phase 1 同时需要做冒烟验证：

- 多 wiki 管理。
- shared wiki。
- 跨库检索。
- C 级 principle 晋升的 proposal/approval 闭环。

这些冒烟测试不要求生产级稳定，但必须证明接口没有设计错误。

### 1.4 Phase 2 目标预埋

Phase 2 面向团队多人协作。多人协作和多 Agent 协作本质上都是多写者、冲突、权限、协调和审计问题，因此 Phase 1 的数据模型和接口必须从一开始支持 Phase 2 终态，但实现只覆盖个人知识库必要路径。

---

## 2. 核心设计原则

### 2.1 设计以终为始，实现分阶段

架构决策按 Phase 2 终态设计，Phase 1 只实现必要路径。

典型例子：

- 使用 `wiki_id:doc_id` 复合身份，即使 Phase 1 只有少量 wiki。
- 使用全局 `registry.yaml`，即使 Phase 1 是个人场景。
- 权限模型绑定 `actor_type + agent_id + wiki + page_type + operation risk`，即使 Phase 1 只监听本机。
- 支持多个 shared wiki，而不是写死唯一 `global`。

这样避免 Phase 2 团队化时发生结构性迁移。

### 2.2 核心可插拔

核心系统只依赖接口，不绑定具体实现。

必须可替换的组件包括：

- Storage：Git、未来 S3、多 repo、本地文件系统等。
- ContentAdapter：Obsidian、Notion、Logseq、Plain Markdown 等。
- Retrieval：lexical baseline、local vector、OpenAI embedding、其他模型。
- External view：Obsidian、Notion、Logseq、飞书页面等。
- Attachment storage：本地对象存储、未来 Git LFS/annex 等。

Phase 1 默认实现不代表架构绑定。

### 2.3 Git 是权威源

权威链路为：

```text
Git authority → Local workspace compile/index/staging → External view/edit layer
```

- Git 仓库负责版本、协作、审计和权威状态。
- Local workspace 是编译、索引、pending、proposal、冲突快照和运行态所在。
- Obsidian/Notion/Logseq 等外部系统是人类编辑和阅读偏好的视图层。
- 写入必须通过 gate-check 后回流 Git，未通过 gate 的变更不能成为权威状态。

### 2.4 协议中心，而非 adapter 逻辑分散

系统采用独立 `Knowledge Agent` 进程，而不是让每个 Agent import 核心库或各自实现检索/写入逻辑。

核心形态：

```text
Knowledge Agent / aw-agent
├─ MCP Server     主接口，供 Hermes/OpenClaw/Claude Code 等发现和调用
├─ CLI / aw       兜底接口，供 Codex/OpenCode/脚本调用
├─ REST API       前端/仪表盘接口，权限边界对齐 CLI
└─ Core Engine    ingest/compile/retrieve/lint/propagate/sync/review
```

Agent adapter 从“实现知识库逻辑”降级为 thin client 或配置入口。

### 2.5 Gate 强度随真相区风险上升

`gate-check` 不是一刀切，而是按操作风险分级：

| Gate | 操作类型 | 检查强度 |
|---|---|---|
| A 级 | raw/source capture | schema、frontmatter、manifest、doc_id、索引一致性 |
| B 级 | atom/synthesis 修订、dispute 标记 | A 级 + route test、query profile 覆盖、dispute caveat |
| C 级 | principle 晋升、dispute 裁决、跨库 merge | B 级 + 内容质量、证据充分性、重复/空洞检测、人工确认 |

风险逻辑：raw 写错只影响一条源，principle 写错会污染整个推理体系。

---

## 3. 已确认决策汇总

### 3.1 系统权威和数据流

1. Git 仓库是权威源，本地 workspace 是编译/索引/staging 区，外部系统只是视图层。
2. 写入必须通过 Git 回流，未通过 gate 的变更不能成为 committed authority state。
3. Git 中保存知识页、`purpose.md`、配置、`MANIFEST.jsonl`、`retrieval_index.jsonl`、日志、审计日志和 review queue。
4. Git 不保存 `vectors.db`，因为它是二进制、不可 diff、并发冲突难处理。
5. `retrieval_index.jsonl` 是文本可 diff 工件，进入 Git。
6. 向量库本地构建，但 embedding model 和 schema 必须统一，确保可重建。
7. 多 wiki Git 组织同时支持 monorepo 和 multi-repo；Phase 1 默认 monorepo，接口预留 multi-repo 映射。

### 3.2 多 wiki 与身份模型

8. 一个全局 `aw-agent` 管理多个知识库，通过 `wiki_id` / workspace path 路由。
9. 全局 `registry.yaml` 是多 wiki 注册权威；单 wiki config 只保存局部规则。
10. 跨库身份使用 `wiki_id:doc_id` 复合身份，`doc_id` 只要求在单 wiki 内唯一。
11. 跨库检索按 `purpose.md` / topic 路由，先选最相关 wiki，必要时扩展跨库检索。
12. 查询结果必须标注来源 wiki，保证可追溯。
13. 允许跨库编译产物，跨域 `synthesis/principle` 可写入 shared wiki。
14. shared wiki 用户可配置多个，不写死唯一 `global`。
15. Phase 1 的 shared wiki 主要存高阶产物，限制为 `synthesis/principle`，不存 raw/atom。

`registry.yaml` 的关键字段必须覆盖：

```yaml
version: 1
default_route_policy: purpose_then_topic
wikis:
  - wiki_id: imaging-os
    type: personal            # personal | shared | archive | external_mirror
    repo:
      provider: git
      mode: monorepo          # monorepo | multi_repo
      path: ./wikis/imaging-os
      remote: origin
    workspace_path: ./wikis/imaging-os
    purpose_path: purpose.md
    config_path: config.yaml
    allowed_page_types: [raw, atom, synthesis, principle]
    external_views:
      - adapter: obsidian
        mode: read_write       # read_write | read_only
        path: ~/Knowledge/ImagingOS
      - adapter: plain_markdown
        mode: read_write
    pending_query_policy:
      raw: include_by_default
      atom: exclude_by_default
      synthesis: exclude_by_default
      principle: exclude_by_default
    retrieval:
      coarse_provider: lexical
      optional_providers: [local_vector]
      route_priority: 80
    permissions:
      - actor_type: agent
        actor_id: claude-code
        allowed_operations: [query, capture_raw, compile_update, lint]
        max_gate: B
        allowed_page_types: [raw, atom, synthesis]

  - wiki_id: global-research
    type: shared
    workspace_path: ./wikis/global-research
    allowed_page_types: [synthesis, principle]
    shared_write_policy:
      allowed_sources: cross_wiki_only
      min_gate: C
      require_human_confirmation: true
    retrieval:
      coarse_provider: lexical
      route_priority: 100
```

字段语义：

- `type` 区分个人库、shared wiki、归档库和外部镜像。
- `allowed_page_types` 是 gate 和 lint 的硬约束。
- `external_views` 绑定 ContentAdapter 和读写模式。
- `pending_query_policy` 决定 pending 内容是否进入查询。
- `shared_write_policy` 限制 shared wiki 只能接收跨库高阶产物。
- `route_priority` 参与 `purpose.md` / topic 路由时的 tie-break。
- `permissions` 绑定 `actor_type + actor_id + operation + max_gate + page_type`。

### 3.3 目录与状态组织

16. 全局根目录包含 `registry.yaml`。
17. 每个 wiki 包含 `purpose.md`、`config.yaml`、`pages/`、`MANIFEST.jsonl`、`retrieval_index.jsonl`、`review_queue.jsonl`、`query_outcomes.jsonl` 等。
18. `pages/` 不按 `page_type` 固定分区，路径不参与身份和语义判断。
19. 用户可以自由组织页面路径；系统只要求 frontmatter 与 manifest 一致。
20. 每个 wiki 的本地运行态放在 `.agent-wiki/`，默认不进 Git。
21. Git `MANIFEST.jsonl` 只记录 committed 权威态。
22. 本地 `.agent-wiki/pending_manifest.jsonl` 记录 pending/uncommitted 叠加态。
23. 查询和 sync 使用 committed + pending 的合并视图，但遵守 pending 查询策略。

### 3.4 Agent 能力分层

24. Agent 不强求同等能力，按三层定义：
    - T1 Full：Hermes、OpenClaw，支持 ingest/query/lint/sync/cron/propagation。
    - T2 Standard：Claude Code，支持 ingest/query/lint，sync/cron 靠外部触发。
    - T3 Minimal：Codex、OpenCode，支持 query/capture_raw，其他能力依赖外部。
25. `query` 和 `capture_raw` 是所有 Agent 使用知识库的最低公约数。
26. `lint/sync/cron/propagation` 是能力增强，不是准入门槛。
27. T3 Agent 只能执行 `capture_raw`，不能直接改 truth zone。
28. T2+ 才能执行 `compile_update`，且必须通过 B 级 gate。

### 3.5 Ingest 与编译

29. ingest 拆成两层：
    - `capture_raw`：写入 raw/source，不改 truth zone，所有 Agent 可用。
    - `compile_update`：编译/修订 atom/synthesis/principle，改 truth zone，至少 T2 可用。
30. `compile_update` 强制 `analyze → apply` 两步。
31. `analyze` 输出目标 wiki、目标 doc、变更类型、证据链、风险级别和 gate 计划。
32. `apply` 才实际修改页面和索引。
33. B 级操作无需人工确认，但 analyze 结果必须作为审计记录保留。
34. 成功 apply 后写入 `operation_log.jsonl` 和 `log.md` 摘要。
35. 失败或未执行的 analyze 只保存在本地 proposal/运行态，不进入 Git。

### 3.6 ContentAdapter 与外部视图

36. 检索召回不依赖 Obsidian 或任何具体外部格式。
37. `ContentAdapter` 在摄入/回流时把格式特性转为统一内部表示：`doc_id`、`source_refs`、`cross_refs` 等。
38. ObsidianAdapter 解析 `[[wikilinks]]`、双链和 Obsidian frontmatter。
39. NotionAdapter 未来解析 Notion block format 和 database relation。
40. PlainMarkdownAdapter 只识别标准 Markdown link 和 YAML frontmatter。
41. 格式特有结构保存在 `adapter_metadata`，用于 round-trip、sync、debug，不参与默认 ranking。
42. Phase 1 实现 ObsidianAdapter 读写和 PlainMarkdownAdapter 读写。
43. Notion/Logseq 等 Phase 1 可定义接口或只读视图，不实现完整反向同步。

### 3.7 External edit 与 sync

44. Phase 1 允许人类通过 External view 编辑。
45. Obsidian 反向同步在 Phase 1 范围内。
46. 反向同步链路为：`External edit → ContentAdapter → Local workspace → gate-check → Git commit`。
47. `sync` 支持三种模式：
    - `pull-view`：External view → workspace → gate → Git。
    - `push-view`：Git/workspace → External view。
    - `status`：diff、冲突、待回流检查。
48. 自动定时 sync 只给 T1/MCP；CLI 只手动触发。
49. gate-check 拦截的是 Git commit，不是 workspace 可见性。
50. 外部编辑先 apply 到 workspace；gate 失败时标记 pending，不提交 Git。
51. 人类可在 Obsidian 中自然修复 gate 问题，再次 sync 后通过 gate 并 commit。

### 3.8 Pending 查询策略

52. raw pending 可查询。
53. truth zone pending 默认不参与 query，除非显式 `include_pending=true`。
54. raw pending 建本地 `.agent-wiki/pending_retrieval_index.jsonl`。
55. truth zone pending 默认不建 index；显式 include 时走文件加载或临时索引。

### 3.9 原始资料与证据链

56. raw 支持 Markdown 页面 + 原始附件目录。
57. PDF、网页快照、图片等原始附件本地保存或存对象存储，raw 页面记录摘要和引用。
58. Phase 1 附件不进 Git，只记录 `source_uri`、hash 和可恢复位置。
59. 附件 `StorageProvider` 预留 Git LFS/annex，但 Phase 1 不实现。
60. truth zone 的 `source_refs` 必须引用 Git 可追踪 raw 页面，即 `wiki_id:doc_id`。
61. 外部附件/URL 只能由 raw 页面引用，不能被 atom/synthesis/principle 直接当作 source_refs。

### 3.10 检索与返回格式

62. 检索模型可插拔。
63. `retrieval_index + lexical search` 是最低可用路径。
64. 向量检索是增强插件，不是最低依赖。
65. Phase 1 默认 lexical search，optional local vector plugin。
66. `retrieval_index.jsonl` 粒度按 page_type 分策略：raw 页级，atom/synthesis/principle section/claim 级。
67. `wiki.query` 固定三层返回：
    - L1：直接可用答案。
    - L2：命中页面、`wiki_id:doc_id`、状态 caveat、相关原因。
    - L3：证据链，列 raw `source_refs` 和必要原文片段。
68. 不同 Agent 可按上下文预算选择读取不同层。

### 3.11 Query outcome、feedback 与 weekly review

69. Phase 1 实现行为改进闭环：记录 query outcome，并生成 weekly review。
70. `query_outcomes` 记录策略按 query_type 配置。
71. `proof_trace` 和 `decision_support` 必记，普通 fact 类查询可采样。
72. 增加 `wiki.feedback(query_id, approved, missing_evidence, rewrite_targets, notes)`。
73. MCP 和 CLI 都提供 `wiki.feedback`。
74. feedback 自动生成 `review_queue` item，但不自动改页面、不触发 compile。
75. `weekly-review` 输出三部分：新信号、队列状态、建议行动。
76. weekly review 只建议，不自动执行。

### 3.12 4-Signal 与图谱边界

77. Phase 1 不是纯显式关系，也不是完整图算法。
78. Phase 1 维护显式 `cross_refs/depends_on/source_refs`，并生成 4-signal 候选关系。
79. 4-signal 是建议器，不是执行器；候选关系只进入报告/候选区，不自动改页。
80. Louvain 社区检测留到 Phase 2。
81. weekly review 合并 4-signal 候选关系，与 query outcome、待编译 raw、缺证据页面一起呈现。

### 3.13 Review queue 与冲突处理

82. `review_queue` 扩展为通用任务队列，而不是只处理争议。
83. 状态机为 `open → assigned → in_progress → resolved → archived`。
84. 增加 `item_type`，包括 conflict、missing_evidence、pending_gate_fix、signal_candidate、feedback_issue、principle_proposal、dispute 等。
85. 增加 `priority` 字段。
86. dispute 是 `item_type=dispute` 的子流程。
87. git rebase 冲突、Obsidian 回流冲突、同一 doc 并发修改统一进入 review queue。
88. workspace 中保存完整 patch/快照供 Agent 修复。
89. 人类通过 Obsidian inbox 或飞书/微信消息看到冲突摘要，不直接操作 workspace patch。
90. External view 原页面保持可读，pending/disputed 详情折叠展示，冲突入口汇总到收件箱。

### 3.14 并发和提交策略

91. Phase 1 采用乐观并发。
92. 提交前执行 `git pull --rebase`，再运行对应风险级别的 `gate-check`。
93. 冲突失败进入 review queue。
94. 显式锁接口预留给 Phase 2 团队场景，Phase 1 实现为 no-op。
95. 提交策略按风险分级：
    - A 级：自动小提交。
    - B 级：按任务批量提交。
    - C 级：人工确认后单独提交。

### 3.15 C 级确认与审计

96. 高风险操作不允许 CLI 直接执行。
97. C 级操作必须走 MCP + 人工确认。
98. 标准路径是 MCP 两步提交：`propose_*` 生成 diff/证据/gate 报告，`approve_proposal` 落库提交。
99. 飞书/微信等消息确认是可选便捷入口，底层仍调用 `approve_proposal`。
100. proposal 存在本地 `.agent-wiki/proposals/`，未批准 proposal 不进入权威 Git。
101. 批准后把最终变更和批准记录写入 Git。
102. 批准记录同时写入 `approval_log.jsonl` 和 `log.md`。

### 3.16 权限与身份

103. 权限模型按 `actor_type + agent identity + wiki + page_type + operation risk` 控制。
104. `actor_type` 从 Phase 1 开始建模，包含 `agent`、`human`、`service`。
105. human edit 不强制 agent 的 analyze/apply 两步，但必须过同一套 A/B/C gate 才能 commit。
106. human edit 触及 C 级操作时仍需确认记录。
107. `agent_id` 由 Knowledge Agent 根据 MCP client、CLI config 或 token 解析，调用参数不能覆盖。
108. T3 只能 A 级，T2 可 B 级，C 级必须 MCP 人工确认。

身份和 token 安全边界：

- MCP 身份来自 MCP client metadata 和本地 `registry.yaml` / identity config 绑定，调用参数不能覆盖。
- CLI 身份来自本地 identity profile，默认路径为用户级配置，例如 `~/.config/agent-wiki/identity.yaml`。
- REST 身份来自本地 token，token 默认只授权 `127.0.0.1` 调用。
- token 不进入 Git，不写入 wiki workspace，不出现在 `log.md`、`operation_log.jsonl` 或错误报告中。
- token 存储优先使用 OS keychain；不可用时落到用户级配置目录，并要求文件权限仅当前用户可读写。
- token 必须支持轮换：生成新 token 后旧 token 可被显式 revoke。
- Phase 1 不做公网多租户认证；Phase 2 再引入团队 RBAC/OIDC。
- 审计日志记录 resolved actor identity、transport、actor_type、operation、wiki_id、gate level，但不记录 token 原文。
- 人类通过 CLI 直接执行时 actor_type 为 `human`；Agent 或脚本驱动 CLI 时 actor_type 必须由 identity profile 显式声明为 `agent` 或 `service`。

### 3.17 MCP、CLI、REST 接口边界

109. MCP Server 是主接口，支持完整能力和交互确认。
110. CLI `aw` 是兜底接口，供 Codex/OpenCode/脚本调用。
111. REST API 在 Phase 1 实现，供前端/仪表盘接入。
112. 三个接口共享同一套核心逻辑，只是传输层不同。
113. CLI 暴露低/中风险确定性命令：query、capture_raw、compile_update、lint、sync、gate-check、weekly-review、feedback。
114. MCP 暴露 CLI 能力 + C 级 proposal/approval、dispute 裁决、跨库 merge 等高风险操作。
115. REST 权限边界对齐 CLI。
116. REST 可调用 C 级 propose，但 approve 必须走 MCP 或消息通道确认。
117. Phase 1 服务只监听 `127.0.0.1`。
118. REST 使用本地 token。
119. MCP 使用 client identity/config 绑定。
120. Phase 2 再扩展团队级 RBAC/OIDC。

### 3.18 MCP Tool 与 CLI 命名

121. MCP tool 按能力域设计，形成稳定 contract。
122. 初始 MCP tools 包括：
    - `wiki.query`
    - `wiki.capture_raw`
    - `wiki.compile_analyze`
    - `wiki.compile_apply`
    - `wiki.lint`
    - `wiki.sync`
    - `wiki.gate_check`
    - `wiki.weekly_review`
    - `wiki.feedback`
    - `wiki.propose_principle`
    - `wiki.approve_proposal`
123. CLI 命令一一映射低/中风险子集。
124. Python package 名为 `agent_wiki`。
125. CLI 可执行名为 `aw`。
126. 服务进程名为 `aw-agent`。
127. MCP server 名为 `agent-wiki`。

CLI actor_type 区分机制：

- `aw` 每次调用先解析 identity profile，而不是信任命令行传入的 `--actor-type`。
- 人类本地交互默认 profile 为 `human:<local_username>`。
- Agent 集成必须使用独立 profile，例如 `agent:codex`、`agent:opencode`、`agent:claude-code`。
- service/cron 使用 `service:<job_name>` profile，例如 `service:weekly-review`。
- CLI 可提供 `--profile <name>` 选择已注册 profile，但 profile 内容必须在本地 identity config 中预先存在。
- 未注册 profile 或 profile 权限不匹配时，`aw-agent` 拒绝执行。
- 审计日志记录 profile 名和解析后的 actor identity，不能只记录 shell 用户名。

### 3.19 purpose.md

128. `purpose.md` 必须实现并进入 Git。
129. `purpose.md` 是知识库价值判断锚点。
130. 它影响 ingest 判断、compile_update 取舍、principle 晋升、query 答案风格和跨库路由。
131. 内容至少包括：目标领域和边界、topic 优先级、答案风格偏好、什么不值得进入 truth zone。

### 3.20 Phase 1 默认技术栈和实现边界

132. Phase 1 使用 Python 优先。
133. 技术栈为 Typer、FastAPI、Python MCP SDK、Pydantic、SQLite。
134. Phase 1 默认实现组合：`GitStorage + LocalWorkspace + ObsidianAdapter(读写) + PlainMarkdownAdapter(读写) + lexical search + optional local vector plugin`。
135. Notion、Logseq、S3、Git LFS/annex、OpenAI embedding、团队 RBAC/OIDC 等只定义接口和配置 schema，不实现完整路径。

---

## 4. 推荐方案 A：协议中心型 Knowledge Agent

### 4.1 为什么选择方案 A

已比较三个主方案：

| 方案 | 描述 | 优点 | 问题 |
|---|---|---|---|
| A. 协议中心型 Knowledge Agent | 全局 `aw-agent` 管多 wiki，通过 MCP/CLI/REST 暴露能力 | Agent 逻辑集中、权限/gate/审计一致、符合 Phase 2 终态 | Phase 1 初始工程量较高 |
| B. CLI-first 工具链 | 先做 `aw` CLI，MCP/REST 后补 | 起步最快 | 后续会重构权限、身份、proposal、C 级确认 |
| C. 库/API 嵌入型核心 | 各 Agent import Python package | 单进程开发简单 | 违背协议调用原则，adapter 重新变厚，多 Agent 行为不一致 |

推荐并已选择方案 A。

理由：

- 多 Agent 使用同一知识库时，检索、写入、gate、权限和审计必须一致。
- MCP 是 Agent 标准协议，Hermes/OpenClaw/Claude Code 可直接发现和调用。
- CLI 为 Codex/OpenCode/脚本提供兜底能力。
- REST API 为前端和仪表盘提供接入路径。
- Phase 1 工程量更高，但不会把架构债留给 Phase 2。

### 4.2 高层架构

```text
┌──────────────────────────────────────────────────────────────┐
│                         Human / Agents                        │
│ Hermes / OpenClaw / Claude Code / Codex / OpenCode / Browser  │
└───────────────┬──────────────────┬──────────────────┬────────┘
                │                  │                  │
                ▼                  ▼                  ▼
          MCP Server             CLI aw             REST API
                │                  │                  │
                └──────────────────┴──────────────────┘
                                   │
                                   ▼
┌──────────────────────────────────────────────────────────────┐
│                    aw-agent / Knowledge Agent                 │
│                                                              │
│  Identity & Permission  Gate Engine  Proposal/Approval        │
│  Query/Retrieve         Ingest/Compile Sync/Propagation       │
│  Review Queue           Weekly Review  4-Signal Suggestions   │
└──────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌──────────────────────────────────────────────────────────────┐
│                      Pluggable Core Interfaces                │
│ StorageProvider  ContentAdapter  RetrievalProvider            │
│ EmbeddingProvider AttachmentStorage ExternalViewAdapter        │
└──────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌──────────────────────────────────────────────────────────────┐
│                  Git Authority + Local Workspace              │
│ registry.yaml / purpose.md / pages / MANIFEST / index / logs  │
│ .agent-wiki pending/proposals/vectors/cache/conflicts          │
└──────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌──────────────────────────────────────────────────────────────┐
│                         External Views                        │
│ Obsidian read/write, Plain Markdown, future Notion/Logseq      │
└──────────────────────────────────────────────────────────────┘
```

### 4.3 核心数据流

#### A 级：capture_raw

```text
Agent/Human/Service
  → MCP/CLI/REST
  → aw-agent identifies actor
  → permission check
  → ContentAdapter normalize
  → write raw page to workspace
  → A-level gate-check
  → update MANIFEST + retrieval_index
  → git pull --rebase
  → commit
  → optional push-view
```

#### B 级：compile_update

```text
T2/T1 Agent
  → compile_analyze
  → evidence/source_refs/gate plan/risk classification
  → compile_apply
  → update atom/synthesis/dispute state
  → B-level gate-check
  → update MANIFEST + retrieval_index + operation_log + log.md
  → git pull --rebase
  → batch commit
```

#### C 级：principle / dispute adjudication / cross-wiki merge

```text
MCP caller or REST propose endpoint
  → propose_*
  → local .agent-wiki/proposals diff/evidence/gate report
  → human confirmation via MCP or message channel
  → approve_proposal
  → C-level gate-check
  → write final changes + approval_log + log.md
  → git pull --rebase
  → single commit
```

### 4.4 Query flow

```text
query request
  → identity + permission
  → query_type classification
  → purpose.md/wiki registry route
  → lexical baseline retrieval over retrieval_index
  → optional vector retrieval plugin
  → aggregate by wiki_id:doc_id
  → load full page / section / claim by policy
  → apply pending/disputed caveats
  → return L1/L2/L3
  → log query_outcome according to query_type policy
```

### 4.5 Sync flow

```text
pull-view:
  External view edit
    → ContentAdapter parse
    → apply to workspace
    → gate-check
    → pass: commit to Git
    → fail: mark pending in .agent-wiki/pending_manifest.jsonl

push-view:
  Git/workspace state
    → ContentAdapter render
    → update External view

status:
  compare Git/workspace/external view
    → report pending, conflict, drift, stale index
```

---

## 5. Phase 1 Scope Summary

### 5.1 Must implement in Phase 1

- Global `aw-agent` managing multiple registered wikis.
- MCP Server, CLI `aw`, and REST API sharing one core.
- `registry.yaml` and per-wiki `config.yaml`.
- `purpose.md` per wiki.
- `wiki_id:doc_id` identity.
- Git authority model with local workspace staging.
- `capture_raw` A-level flow.
- `compile_update` B-level analyze/apply flow.
- `query` with L1/L2/L3 result.
- Lexical baseline retrieval using `retrieval_index.jsonl`.
- Optional local vector plugin boundary.
- Obsidian read/write sync and Plain Markdown read/write.
- Pending state under `.agent-wiki/`.
- Risk-based gate-check.
- Generalized `review_queue`.
- `query_outcomes`, `wiki.feedback`, and `weekly-review`.
- 4-signal candidate generation as suggestions only.
- C-level proposal/approval smoke path for principle promotion.

### 5.2 Phase 1 Smoke Tests and Acceptance Checklist

Phase 1 硬验收是个人知识库日用闭环稳定；跨库、shared wiki 和 C 级晋升做冒烟验证。每项验收必须能通过命令或 MCP/REST 调用复现。

| # | 验收项 | 最小验收标准 |
|---|---|---|
| S1 | registry 加载 | `aw-agent` 能读取 `registry.yaml`，注册至少 2 个 personal wiki 和 1 个 shared wiki，并拒绝重复 `wiki_id` |
| S2 | identity 解析 | MCP、CLI、REST 三种入口都能解析 actor identity；请求参数无法覆盖 `agent_id` 或 `actor_type` |
| S3 | CLI actor profile | `aw --profile agent:codex query ...` 以 Codex/T3 权限执行；未注册 profile 被拒绝 |
| S4 | capture_raw A 级 | T3 profile 能写入 raw 页面，更新 `MANIFEST.jsonl` 和 raw 页级 `retrieval_index.jsonl`，并自动提交 Git |
| S5 | T3 权限拦截 | T3 profile 调用 `compile_update` 被拒绝，并产生可审计错误 |
| S6 | compile_update B 级 | T2 profile 完成 `compile_analyze → compile_apply`，修订 atom/synthesis，写入 `operation_log.jsonl` 和 `log.md` |
| S7 | lexical query baseline | 在未启用 vector provider 时，`wiki.query` 仍能通过 lexical provider 返回 L1/L2/L3 |
| S8 | optional vector isolation | 启用或禁用 local vector plugin 不改变 query contract，只影响候选排序/召回增强 |
| S9 | pending raw query | Obsidian 回流 raw gate 失败后，workspace 可见、Git 未提交、`.agent-wiki/pending_manifest.jsonl` 有记录，raw pending 可查询 |
| S10 | pending truth exclusion | truth zone pending 默认不进入 query；显式 `include_pending=true` 才可读取 |
| S11 | Obsidian pull-view | Obsidian 编辑经 ContentAdapter apply 到 workspace；gate 通过后提交 Git，gate 失败时进入 pending 和 review_queue |
| S12 | Obsidian push-view | Git committed 页面可渲染回 Obsidian，保留可 round-trip 的 `adapter_metadata` |
| S13 | review_queue 通用状态 | conflict、missing_evidence、signal_candidate 至少各创建 1 条 item，状态机使用 `open → assigned → in_progress → resolved → archived` |
| S14 | feedback 闭环 | `wiki.feedback` 对缺证据 query 生成 `review_queue` item，但不修改页面 |
| S15 | weekly-review | weekly review 输出新信号、队列状态、建议行动三部分，包含 query outcome 和 4-signal 候选 |
| S16 | 跨库检索 | query 先路由到最相关 wiki，必要时扩展跨库，并在 L2 标注来源 `wiki_id:doc_id` |
| S17 | shared wiki 写入限制 | shared wiki 拒绝 raw/atom 写入，只允许 C 级 synthesis/principle proposal |
| S18 | C 级 proposal | `propose_principle` 生成本地 `.agent-wiki/proposals/` diff、证据和 gate 报告，不写 Git |
| S19 | C 级 approval | `approve_proposal` 经 MCP 人工确认后写入 shared wiki、`approval_log.jsonl` 和 `log.md`，并单独提交 Git |
| S20 | REST 权限边界 | REST 可执行 query/capture/compile/propose，但不能 approve C 级 proposal |
| S21 | 乐观并发 | 提交前执行 pull/rebase；冲突时进入 review_queue 并保留 agent 用 patch/快照 |
| S22 | gate 分级 | A/B/C 三类操作分别触发对应 gate 检查集合，低风险操作不被 C 级确认阻塞 |

这些 smoke tests 不要求完整生产负载，但必须证明核心接口、权限、pending overlay 和跨库模型方向正确。

### 5.3 Interface-only or Phase 2+

- Notion/Logseq full reverse sync.
- S3 or non-Git authority storage.
- Git LFS/annex attachment provider.
- Team RBAC/OIDC.
- Distributed locking.
- Louvain community detection.
- Governance Agent that centrally decides all writes.
- Automatic compile proposal consumption.
- Production-grade multi-repo team workflow.

---

## 6. Open Review Questions for Claude Code

Claude Code review should focus on architecture coherence before implementation planning:

1. Does the protocol-centered `aw-agent` architecture keep Agent adapters sufficiently thin?
2. Are MCP/CLI/REST permission boundaries coherent, especially around C-level approve restrictions?
3. Is the Git authority + local pending overlay model practical for Obsidian reverse sync?
4. Is `wiki_id:doc_id` sufficient for cross-wiki identity and future multi-repo migration?
5. Does the generalized `review_queue` cover conflict, feedback, missing evidence, signal candidates, and disputes without overloading one abstraction?
6. Is Phase 1 scope still implementable, or should REST/API/vector/4-signal be staged more aggressively?
7. Are there hidden consistency risks in storing `retrieval_index.jsonl` in Git while keeping `vectors.db` local?
8. Is the gate model enforceable across agent/human/service actors without excessive UX friction?

---

## 7. Current Recommendation

Proceed with方案 A：协议中心型 Knowledge Agent。

The next design step is to turn this requirements baseline into a sectioned Phase 1 design spec covering:

- Architecture and module boundaries.
- Storage and workspace layout.
- Protocol contracts for MCP/CLI/REST.
- Data models and schemas.
- Gate-check and permission enforcement.
- Query/retrieval behavior.
- Sync and pending state.
- Review queue, feedback, and weekly review.
- Phase 1 validation and smoke tests.
