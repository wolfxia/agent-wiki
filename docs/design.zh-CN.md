# Agent Wiki 架构设计

> 本文档描述 agent-wiki 的目标架构、数据流闭环和当前实现状态的对齐情况。

## 1. 架构总览

Agent Wiki 采用分层架构：

```
┌─────────────────────────────────────────┐
│            Agent 前端层                  │
│  Hermes │ CC │ Codex │ OpenClaw │ OpenCode │
├─────────────────────────────────────────┤
│            传输层                        │
│     MCP Server │ REST API │ CLI          │
├─────────────────────────────────────────┤
│            应用服务层                    │
│  capture_raw │ compile_update │ query    │
│  lint │ sync │ feedback │ weekly_review  │
├─────────────────────────────────────────┤
│            领域层                        │
│  models │ contracts │ enums │ gates      │
├─────────────────────────────────────────┤
│            基础设施层                    │
│  manifest │ retrieval │ pending │ log    │
│  identity │ review_queue                │
├─────────────────────────────────────────┤
│            存储层                        │
│  Git仓库 │ 本地workspace │ .agent-wiki/  │
├─────────────────────────────────────────┤
│            外部视图层                    │
│  Obsidian │ Notion │ 其他知识库UI       │
└─────────────────────────────────────────┘
```

### 核心抽象

| 抽象 | 说明 |
|------|------|
| Wiki | 一个独立的知识库实例，有独立Git仓库和配置 |
| Page | 一个知识页面（raw/atom/synthesis/principle 四类） |
| Manifest | 页面元数据的权威索引（JSONL格式） |
| Retrieval Index | 检索用的文本索引（JSONL格式） |
| Gate | 写入操作的风险分级门控（A/B/C三级） |
| ContentAdapter | 外部知识库格式适配器（Obsidian/Notion/PlainMarkdown） |

## 2. 写入传播链路

写入不仅是页面编辑——它触发完整的传播链路：

```
写入请求
  → Gate分级检查
  → 页面写入（pages/{doc_id}.md）
  → Manifest更新（MANIFEST.jsonl）
  → Retrieval索引更新（retrieval_index.jsonl）
  → 操作日志追加（log.md）
  → 审查队列插入（如需）
```

### Gate分级

| 级别 | 风险 | 适用操作 | 传播要求 |
|------|------|----------|----------|
| A | 低 | capture_raw | 直接传播，无需审核 |
| B | 中 | compile_update | 传播+检索可用性验证 |
| C | 高 | principle晋升 | 内容质量检查+人工确认（两步提交） |

### C级两步提交

C级操作采用 proposal → approval 两步流程：

1. **Proposal阶段**：写入proposal文件，标记状态为pending
2. **Approval阶段**：人工或授权Agent确认，状态变更为approved，执行传播

### 传播失败处理

任何传播步骤失败时：
- 回滚已传播的步骤
- 标记为stale
- 记录到操作日志
- 等待重试或人工干预

> 说明：以上仍然是目标设计，不应被读成当前 Phase 1 已完整实现的运行时保证。当前基线仍缺少完整的 authority-promotion / commit orchestration、stale marker 生命周期，以及自动重试编排。

## 3. 查询检索流程

```
查询请求
  → 查询类型分类（6类：fact/explanation/procedure/comparison/status/dispute）
  → 粗检索（retrieval_index.jsonl 词法匹配）
  → Manifest过滤和排序
  → 分层输出：
      L1 答案（直接回答）
      L2 上下文（相关页面摘要）
      L3 证明（原始来源引用）
```

### 争议处理

当检索结果中存在冲突信息时，查询结果附带dispute标记，提示用户注意不一致。

### Pending Truth-Zone

默认不包含pending（未提交）的内容。仅在显式请求时包含，并用caveat标记。

## 4. 页面类型体系

| 类型 | 说明 | 可变性 | Gate级别 |
|------|------|--------|----------|
| raw | 原始捕获的笔记/来源 | 不可变 | A |
| atom | 收敛后的原子知识单元 | 可修订 | B |
| synthesis | 知识工件（非摘要！） | 可修订 | B |
| principle | 严格晋升的原则性知识 | 严格管控 | C |

**关键区分**：synthesis ≠ 摘要。synthesis 是经过编译的知识工件，包含推理、关联和结构化输出。

## 5. 数据流闭环机制

### 写入传播矩阵

每个写入操作必须完成其传播矩阵中的所有步骤：

| 操作类型 | 页面 | Manifest | Retrieval | Log | Queue |
|----------|------|----------|-----------|-----|-------|
| capture_raw | ✅ | ✅ | ✅ | ✅ | — |
| compile_update | ✅ | ✅ | ✅ | ✅ | 条件性 |
| proposal | ✅ | ✅ | — | ✅ | ✅ |
| approval | — | ✅ | ✅ | ✅ | ✅ |

### 传播失败处理

- 检测：每次传播后运行完整性检查
- 自动修复：stale标记 → 重试传播
- 人工兜底：连续2次失败 → 暂停并告警

### 反向传播

外部视图（如Obsidian）的人类编辑通过ContentAdapter反向同步：
```
Obsidian编辑 → ContentAdapter解析 → workspace写入 → Gate检查 → Git commit
```

Phase 1 实现Obsidian适配器的反向同步。

## 6. Agent能力分层

| 层级 | Agent | 能力 |
|------|-------|------|
| T1 Full | Hermes, OpenClaw | 全部操作 |
| T2 Standard | Claude Code | capture_raw, compile_update, query, lint, sync |
| T3 Minimal | Codex, OpenCode | query, capture_raw |

T3 Agent通过CLI `aw` + identity profile访问，无MCP，无持久状态。

## 7. 外部视图与ContentAdapter

外部知识库UI（Obsidian、Notion等）是**可替换的视图层**：

- 权威源 = Git仓库
- Workspace = 编译工作区
- External View = 可替换视图层

ContentAdapter层隔离格式差异：
- `ObsidianAdapter`：处理Obsidian特有的frontmatter、WikiLink等
- `NotionAdapter`：处理Notion的数据库结构（Phase 2）
- `PlainMarkdownAdapter`：纯Markdown，无特殊格式

检索层只认统一内部表示，不关心外部格式。

## 8. 自进化机制

自进化 ≠ 资产堆积 = 行为改进。

闭环：
```
query → 记录outcome → weekly review → 识别改进点 → 更新规则/技能
```

- 每次查询记录 `query_outcome`（命中率、满意度信号）
- 周度review生成报告，识别低效模式
- 改进建议输出到 `self-improving/corrections.md`

## 9. 当前实现状态

### 已实现（Phase 1基线）

- ✅ Python包 `agent_wiki`（`src/agent_wiki/`）
- ✅ 注册表驱动的多wiki配置
- ✅ A级原始捕获 + 传播
- ✅ B级编译更新
- ✅ 词法查询 + L1/L2/L3输出
- ✅ Lint检查（manifest/page + manifest/index）
- ✅ Sync操作（status/pull-view/push-view）
- ✅ 反馈记录 + 审查队列
- ✅ 周度审查摘要
- ✅ C级提案/审批
- ✅ 跨wiki查询
- ✅ 32个测试通过

### 设计目标（尚未完整实现）

- ⬜ MCP传输层
- ⬜ REST传输层
- ⬜ 完整gate执行
- ⬜ 回滚/stale恢复模型
- ⬜ 更丰富的schema/frontmatter校验
- ⬜ 向量检索提供者
- ⬜ Obsidian反向同步

## 10. 知识图谱（设计目标）

选择方案B：显式关系 + 4-Signal候选关系。

- 已确认关系：存储在页面frontmatter中
- 候选关系：由4类信号生成建议（不直接修改页面）
  - 共现信号（co-occurrence）
  - 引用信号（cross-reference）
  - 查询共现信号（query co-occurrence）
  - 结构信号（structural proximity）
- Louvain社区检测留Phase 2

## 11. Phase 2 方向

- 团队多人协作（RBAC/OIDC）
- 显式锁和并发控制
- 向量检索提供者路由
- Notion适配器
- 知识图谱可视化
- 更强的传播保证

---

*本文档与代码实现对齐，设计目标与实现状态分开标注。*

---

## 12. DFX 设计

> Agent Wiki 的可部署性、可靠性、安全性、可观测性、性能、可维护性与可扩展性  
> v1.0 — 2026-05-16  
> 状态：已与当前 Phase 1 实现基线对齐的设计目标

### 12.1 范围与阅读说明

本文补充以下文档：

- `README.md`
- `core/schema.md`
- `docs/design.md`
- `docs/agent-differences.md`

本文从七个 DFX 维度定义 Agent Wiki 的非功能设计。每个章节都会区分：

- 随架构演进应保持稳定的**目标设计**
- 当前仓库中已经实现或已明确具备落地基础的 **Phase 1 基线**
- 在更强多 Agent / 网络化场景下需要补强的 **Phase 2 方向**

这里继续沿用仓库现有的写法原则：

**不要把目标架构与当前实现混成一个故事。** 目标设计解释系统要去哪里；实现说明解释今天已经有什么。

---

### 12.2 可部署性（Deployability）

#### 设计目标

Agent Wiki 应当能够在三种部署形态下易于安装、运行、升级与回滚：

1. 本机单用户知识服务
2. 容器化自托管服务
3. 面向网络暴露的多用户服务

部署方式必须保持核心架构不变：一个共享的 `aw-agent` 进程、Git 作为权威源、本地 workspace 作为运行时状态，以及 MCP / CLI / REST 作为同一核心之上的薄接口。

#### 关键决策

##### 决策：以独立 Agent 进程运行，而不是嵌入式库

**理由：** 项目架构假设一个共享知识引擎为多个客户端与多种传输层提供服务。长驻进程更适合承载 MCP 服务、审批路径、后台维护任务与身份解析，而不是把逻辑散落到各个客户端内部。

**备选方案：** 把 wiki 逻辑直接嵌入到各个 agent adapter 或客户端库中。

**不采用原因：** 这会复制核心行为，削弱身份与 gate 的一致性，也会让传播、审计与多传输层一致性更难保证。

##### 决策：把本机部署作为 Phase 1 主力运行模式

**理由：** 当前项目目标是单机上的个人多 Agent 知识系统。本机安装与本机进程管理在保留整体架构的同时，能把运维复杂度降到最低。

**备选方案：** 一开始就优先做网络服务。

**不采用原因：** Phase 1 还不需要完整的远程认证、反向代理或团队级运维姿态。

##### 决策：使用 registry YAML + 环境变量 + `.env` 的 12-factor 风格配置

**理由：** Agent Wiki 既需要明确表达多 wiki 拓扑，也需要环境相关的覆盖配置。registry 负责表达知识库拓扑；环境变量负责端口、token、存储路径等部署关注点。

**备选方案：** 每个 agent 各自维护硬编码配置，或只用一个巨大的单体配置文件。

**不采用原因：** 这样会把传输层/运行时问题与知识库拓扑耦合在一起，也会削弱主机部署和容器部署的可移植性。

##### 决策：以 Git branch 隔离作为知识状态发布与回滚的主要边界

**理由：** Git 已经是权威源。基于分支的发布与回滚可以与仓库的权威模型保持一致，也能快速回退已提交的知识状态。

**备选方案：** 以数据库原生迁移/版本作为主发布边界。

**不采用原因：** 这会削弱 Git 的权威地位，并让 Phase 1 的运维叙事变得更复杂。

#### Phase 1 实现状态

当前已经实现或明显对齐的部分：

- 通过 `pyproject.toml` 已具备 Python package 安装路径，`README.md` 中也已有本地 editable install 的用法。
- CLI 入口已在 `src/agent_wiki/transports/cli/app.py` 中以最小 stub 形式存在。
- `src/agent_wiki/bootstrap/registry_loader.py` 已实现基于 registry 的配置加载。
- 当前运行时模型已经区分了 Git 提交态与 `.agent-wiki/` 下的本地运行时状态。
- 仓库根目录已有 `Dockerfile`，与单包部署方向一致。

当前基线尚未实现：

- 生产级 MCP Server 进程
- 完整的 `aw serve` 长驻服务入口
- `launchd` / `systemd` 的服务管理示例
- 面向可选检索提供者的 docker-compose 编排
- 带反向代理、TLS、OIDC 的 REST 网络部署

#### Phase 1 发布就绪说明

当前基线在 package 安装与总体架构方向上已经成立，但还不能被视为文档中所描述的长驻 `aw-agent` 服务。要支撑更强的部署声明，项目仍需要真实的 `aw serve` 进程、可健康检查的服务行为，以及保护远程或多 Agent 运行的治理控制。

#### Phase 2 规划

Phase 2 应补充：

- 一等公民的长驻 `aw-agent` 服务，启用 MCP 与 REST
- 基于 nginx 或 caddy 的 HTTPS 反向代理部署
- 面向远程访问的 OIDC 身份与会话处理
- 更清晰的主机安装与容器发布包装
- 面向 token、证书与 per-wiki policy 的网络安全配置分层

#### 与其他 DFX 维度的关联

- **可靠性：** 部署形态决定重启行为与回滚速度。
- **安全性：** 网络部署会扩大认证与传输安全边界。
- **可观测性：** 服务包装需要暴露健康检查与结构化日志。
- **可维护性：** 一个可部署的共享核心进程比多个嵌入式实现更容易演进。
- **可扩展性：** 部署方式不应绑定某一个 transport 或 adapter。

---

### 12.3 可靠性（Reliability）

#### 设计目标

Agent Wiki 应能在崩溃、部分传播失败与检索能力退化时，仍然保持知识完整性。系统失败方式必须是可观测、可修复，并与 Git-first 权威模型一致的。

#### 关键决策

##### 决策：把写入传播完整性作为可靠性的核心边界

**理由：** 在这个系统里，一次写入不只是改一个页面文件，而是要同步更新 manifest、retrieval index、日志与 queue 状态。因此，可靠性的核心在于传播是否完整且一致。

**备选方案：** 只要页面文件写成功，就算操作成功。

**不采用原因：** 这会制造 knowledge island，并导致页面内容与检索/审计状态之间出现静默漂移。

##### 决策：采用分层回滚模型：pending 状态、stale 标记、最后再 Git revert

**理由：** 不是所有失败都应该直接触发硬回滚。pending 是提交前缓冲，stale marker 是软回滚信号，而 Git revert 是最终的权威层恢复手段。

**备选方案：** 任意传播失败都立即执行硬回滚。

**不采用原因：** 这过于粗暴，会丢弃本可恢复的工作，也不符合 workspace 与 authority 分离的设计。

##### 决策：当可选检索组件失败时，查询应优雅降级

**理由：** Phase 1 的查询能力不应依赖向量基础设施。词法检索是必备基线，因此即便可选检索提供者失败，系统仍应保持可用。

**备选方案：** 一旦向量或 richer retrieval 不可用，就整体查询失败。

**不采用原因：** 会把可选增强能力变成单点故障。

##### 决策：依赖 Git remote 与可文本恢复的 JSONL 工件做备份与恢复

**理由：** 这与 Git-first 模型一致，也能让核心恢复路径保持可审计、可人工检查。JSONL 的 manifest 与 index 都可以被直接检查与重建。

**备选方案：** 只依赖数据库原生恢复。

**不采用原因：** Phase 1 应保持 file-first，并且不依赖专用存储工具也能恢复。

#### Phase 1 实现状态

今天已经实现或部分实现的部分：

- `src/agent_wiki/application/propagation.py` 已有传播编排。
- 对于无效 raw capture，`.agent-wiki/pending_manifest.jsonl` 已提供 pending fallback。
- `src/agent_wiki/application/query.py` 与 `src/agent_wiki/infrastructure/retrieval/retrieval_index.py` 已提供基于词法检索的降级运行模式。
- `MANIFEST.jsonl`、`retrieval_index.jsonl`、`operation_log.jsonl`、`review_queue.jsonl` 等 JSONL 工件与可文本恢复的恢复模型一致。
- 当前仓库设计已经默认 Git remote 是天然备份边界。

当前设计目标尚未完整落地的部分：

- 显式的 7 项 F1-F7 健康检查模型
- 传播失败后的自动 stale marker
- 自动重试编排与“连续两次失败后暂停”机制
- 传播链各阶段之间的事务式回滚
- 长驻服务崩溃后的重启监管文档

#### Phase 2 规划

Phase 2 应补充：

- 明确的传播完整性状态与 stale-marker 生命周期
- 带上限重试与暂停行为的 retry controller
- 面向长驻 MCP / REST 进程的更强崩溃恢复能力
- 多写者并发更新时更明确的协调机制
- 面向 external views 与 mirror 的更强一致性校验

#### 与其他 DFX 维度的关联

- **可部署性：** 重启与回滚策略依赖部署形态。
- **安全性：** 可审计与可回滚能降低错误写入的影响范围。
- **可观测性：** 可靠性问题必须通过健康信号与告警暴露出来。
- **性能：** 重试与重建不能压垮正常查询/写入路径。
- **可维护性：** 明确的失败状态能简化修复与运维推理。

---

### 12.4 安全性（Security）

#### 设计目标

Agent Wiki 应保护敏感知识内容，通过身份与能力约束 agent 行为，并确保高风险操作走更强审批路径。安全模型必须符合项目的信任边界：Phase 1 本机优先，Phase 2 强化远程与团队控制。

#### 关键决策

##### 决策：将认证、授权与操作风险 gate 分离建模

**理由：** 当前架构已经区分“调用者是谁”“具有什么能力层级”“当前操作属于什么风险等级”。这样既能让低风险使用保持顺畅，也能为高风险写入保留明确边界。

**备选方案：** 只有一个扁平的 allow/deny 权限系统。

**不采用原因：** 这不足以清晰表达项目的 A/B/C gate 模型与 T1/T2/T3 能力模型。

##### 决策：Phase 1 采用 loopback-local trust + local token；Phase 2 迁移到 OIDC

**理由：** 本机部署可以在最小暴露面的前提下保留显式身份；只有在网络暴露或团队共享时，才需要 OIDC 级别的远程认证。

**备选方案：** 一开始就强制使用完整的远程认证体系。

**不采用原因：** 对个人知识工作流来说，这会带来不必要的运维负担。

##### 决策：敏感性必须落在页面级，并在查询阶段生效

**理由：** 仓库预计会保存 API key、内部文档等敏感知识。只按仓库级或 wiki 级过滤过于粗糙；页面级敏感标记才能让检索和输出更安全。

**备选方案：** 把整个 wiki 当成统一可信内容。

**不采用原因：** 无法满足多 agent 与混合敏感级别内容共存的使用场景。

##### 决策：为每次重要操作保留可审计文本日志

**理由：** 任何改变知识状态的操作，都应能追溯到 agent 身份、目标文档与时间戳。

**备选方案：** 只保留易失性的运行时审计事件。

**不采用原因：** 这不足以支撑事后审查、问题排查与信任恢复。

##### 决策：对 content adapter 进行隔离，并在系统边界做输入校验

**理由：** adapter 会摄入外部内容，是最可能引入畸形或恶意输入的边界。

**备选方案：** 把所有 markdown/content 输入都当作可信内部数据。

**不采用原因：** 外部内容天然属于系统边界，应按不可信输入处理。

#### Phase 1 实现状态

今天已实现或已有部分表达的部分：

- `src/agent_wiki/infrastructure/identity/resolver.py`、`permissions.py`、`gates.py` 已存在身份与权限辅助逻辑。
- raw capture、compile update、approvals 三条服务边界已经体现了 A/B/C 分层。
- `approval_log.jsonl` 与 `operation_log.jsonl` 已提供审批与编译写入的审计记录。
- 当前已对 `doc_id`、`allowed_page_types`、`source_refs` 做有限输入校验。
- 项目说明中已经明确高风险审批应走 MCP 或等价的确认路径。

相对设计目标的重要缺口：

- 当前实现路径中，已解析身份仍可能被显式 actor 字段覆盖；`docs/design.md` 已把它列为真实实现缺口
- 尚未有完整的 `max_gate` enforcement engine
- 尚未实现页面级 `sensitivity` schema 与查询过滤
- 当前基线尚未实现 git-crypt 工作流或加密内容处理
- 因为网络服务尚未落地，尚无传输层 TLS / mTLS
- 目前尚未有 adapter 沙箱运行时

#### Phase 1 发布就绪说明

当前 Phase 1 基线还不能被视为 production-ready 的多 Agent 治理体系。在更强的治理或部署声明成立之前，项目仍需要：可信身份优先级、高于 caller-supplied actor fields 的身份解析、中央化 `max_gate` enforcement、页面级敏感性策略，以及 authority-promotion / commit orchestration。

#### Phase 2 规划

Phase 2 应补充：

- 面向远程访问的 OIDC 认证
- 必要时用于服务间信任的 TLS 与 mTLS 传输安全
- 在检索与响应拼装阶段强制执行页面级敏感性过滤
- 始终走 canonical approval path 的高风险审批路由
- 在 confidential 内容场景下支持受保护存储工作流的仓库加密模式
- 更严格的 content-adapter sandbox 与校验 profile

#### 与其他 DFX 维度的关联

- **可部署性：** 远程部署会扩大安全边界。
- **可靠性：** 审计日志与安全回滚能帮助控制未授权或错误写入的影响。
- **可观测性：** 可疑访问与重复 gate 失败应成为可观测信号。
- **可维护性：** 安全规则应位于共享核心策略层，而不是散落在每个 agent wrapper 中。
- **可扩展性：** 新增 adapter 与 transport 时，必须接入同一套身份与策略系统。

---

### 12.5 可观测性（Observability）

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

**备选方案：** 只提供“服务是否在线”的检查。

**不采用原因：** 这无法反映系统真实的正确性边界。

##### 决策：weekly review 属于可观测性的一部分，而不只是维护流程

**理由：** 对知识系统来说，可观测性还包括系统是否被有效使用。低质量查询、堆积的 queue 项与缺失证据，都是操作信号。

**备选方案：** 把 weekly review 仅视作人工治理流程。

**不采用原因：** 这会把可执行的行为反馈排除在运维视图之外。

#### Phase 1 实现状态

今天已经实现：

- propagation 会写入人类可读的 `log.md`
- compile 操作会写入结构化的 `operation_log.jsonl`
- approvals 会写入结构化的 `approval_log.jsonl`
- feedback 提交会写入结构化的 `query_outcomes.jsonl`
- `src/agent_wiki/application/weekly_review.py` 已实现 weekly review summary 生成
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
- 持久化指标采集：延迟、命中质量、传播完整性、queue 健康
- 面向重复传播失败与 stale 累积的告警 hook
- 横跨 MCP、CLI、REST 的更强调用链追踪
- 能把使用模式与维护动作联系起来的更好 operator summary

#### 与其他 DFX 维度的关联

- **可靠性：** 可观测性让传播与恢复问题变得可行动。
- **安全性：** 审计日志与访问轨迹本身就是安全模型的一部分。
- **性能：** 延迟与检索指标是调优决策的基础。
- **可维护性：** 清晰诊断能降低调试成本。
- **可扩展性：** 可插拔 provider 也必须暴露可比的健康与使用信号。

---

### 12.6 性能（Performance）

#### 设计目标

Agent Wiki 应在保证正确性与可追踪性的前提下，对本机 agent 工作流保持足够快的响应。性能目标应服从当前 Phase 1 的真实运行模型：文件后端、本机优先、以单用户为主、检索提供者可插拔。

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
- 最低功能不依赖任何重型检索提供者。

本次设计任务给出的目标数值：

- 本机 JSONL 词法检索 < 100ms
- 开启可选向量提供者时，向量检索 < 500ms
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

### 12.7 可维护性（Maintainability）

#### 设计目标

Agent Wiki 应在持续演进中保持架构清晰。可维护性依赖于稳定的共享核心、明确边界、可靠测试，以及能区分目标设计与当前行为的文档体系。

#### 关键决策

##### 决策：保持分层架构与单向依赖

**理由：** 现有结构已经把 application、domain、infrastructure、bootstrap、transports 分开，有助于让核心策略脱离 adapter 与部署表面。

**备选方案：** 使用 feature-first 模块，把 transport、storage 与 domain 决策混在一起。

**不采用原因：** 这会模糊项目最关键的 core / adapter 边界。

##### 决策：把设计文档当作活的架构文档，而不是事后营销材料

**理由：** 未来贡献者与 reviewer 需要同时理解目标架构与当前实现缺口。

**备选方案：** 只把文档改写成“今天实现了什么”。

**不采用原因：** 这会抹掉系统目标形态，让 Phase 2 决策失去一致评估基线。

##### 决策：使用里程碑导向测试与结构化 lint 验证系统行为

**理由：** 当前仓库已经以 M1-M6 为骨架组织测试，结构一致性检查也与 file-backed 架构天然契合。

**备选方案：** 主要依赖临时性的人工测试。

**不采用原因：** 随着 propagation、approvals 与 multi-wiki 行为变复杂，这种方式无法扩展。

##### 决策：schema versioning 与 migration 必须显式化

**理由：** 文件格式与运行时元数据一定会演进。显式迁移能在不掩盖格式变化的前提下保持延续性。

**备选方案：** 默默发生格式漂移。

**不采用原因：** 这会让旧知识工件语义不清，也更难修复。

#### Phase 1 实现状态

今天已经实现：

- `src/agent_wiki/` 下的分层代码组织
- `README.md` 中记录的 32 个通过测试，覆盖 M1-M6 基线
- README、schema、design、requirements、agent-differences 等核心文档集合
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
- 更完整的部署、恢复、审批运维文档
- 面向 adapter 与 retrieval provider 作者的扩展说明

#### 与其他 DFX 维度的关联

- **可部署性：** 可维护的包装与配置能降低运维负担。
- **可靠性：** 清晰结构更容易正确实现故障恢复。
- **安全性：** 集中且可测试的策略逻辑更安全。
- **可扩展性：** 只有可维护，插件点才不会演变成分叉实现。

---

### 12.8 可扩展性（Extensibility）

#### 设计目标

Agent Wiki 应能通过新增 transport、adapter、retrieval provider 与 agent profile 来扩展，而不改变核心知识模型。可扩展性必须建立在共享契约之上，而不是制造平行实现。

#### 关键决策

##### 决策：所有主要集成都依赖共享核心之上的接口，而不是直接改核心逻辑

**理由：** 项目已经明确存储、content adapter、retrieval、embedding、external views 都应可插拔。稳定的核心契约可以防止功能扩张带来行为碎片化。

**备选方案：** 直接在每个 transport 或每个 agent adapter 里实现各自逻辑。

**不采用原因：** 这会复制 propagation、permissions 与 query semantics。

##### 决策：把 content adapter 作为格式归一化边界

**理由：** Obsidian、Plain Markdown、Notion 与未来视图都应映射为统一内部表示，而格式特有信息只保存在 adapter metadata 中。

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

- 正式的 adapter interface 与 registration mechanism
- 在统一 hit contract 下挂接多个 retrieval provider
- 完整的 MCP / CLI / REST transport surface
- 带可复用 tier template 的更强 agent identity profile
- 确保外部集成始终保持 thin 的扩展指南

#### 与其他 DFX 维度的关联

- **可维护性：** 只有共享核心保持一致，可扩展性才成立。
- **安全性：** 所有扩展都必须继承相同的身份、策略与 gate 规则。
- **性能：** provider 插件必须进入统一的 budget 与指标体系。
- **可部署性：** 扩展的打包方式必须同时适配本机与网络部署。

---

### 12.9 跨 DFX 总结

这七个 DFX 维度是刻意耦合在一起的：

- **可部署性** 决定核心运行在哪里。
- **可靠性** 决定写入与查询在什么条件下仍然可信。
- **安全性** 决定谁可以看到什么、修改什么。
- **可观测性** 决定运维者如何发现漂移与故障。
- **性能** 决定系统是否适合真实 agent 工作流。
- **可维护性** 决定架构是否能在不失去清晰性的情况下继续演进。
- **可扩展性** 决定新工具能否加入系统而不分叉核心逻辑。

对 Agent Wiki 来说，这些不是附着在产品之上的次要属性，而是产品定义本身的一部分，因为这个系统的价值依赖于可信的多 Agent 知识操作，而不只是文件存储。
