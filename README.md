# Agent Wiki — Universal Knowledge System for AI Agents

> 一个通用的、agent-agnostic的知识库框架，让任何AI Agent都能拥有自组织的知识体系。

## 核心思想

**知识系统不应绑死在某个Agent上。** 同一份知识资产，Hermes能查、CC能写、OpenClaw能维护、OpenCode能引用。

实现方式：**核心层agent-agnostic + 适配层per-agent**。

## 四Agent能力矩阵

| 能力 | Hermes | Claude Code | OpenClaw | OpenCode |
|------|--------|-------------|----------|----------|
| 执行方式 | Skill + Cron | Hook + CLAUDE.md | Skill + Cron | CLI run |
| 知识写入 | terminal + file | Bash + Write | skill prompt | opencode run |
| 知识读取 | memory_search + file | Read + Glob | skill prompt | opencode run -f |
| 定时任务 | cronjob | 外部cron | cron | 外部cron |
| 向量检索 | 内置memory_search | 无（需外部） | 无（需外部） | 无（需外部） |
| 人类界面 | 飞书/微信 | Terminal | 飞书 | Terminal |
| 编辑器集成 | Obsidian sync | VSCode | Obsidian sync | 无 |

## 项目结构

```
agent-wiki/
├── README.md                    ← this file
├── LICENSE                      ← MIT
│
├── core/                        ← Agent-agnostic 核心层
│   ├── schema.md                ← wiki-schema（操作契约，从v2.1提取通用化）
│   ├── page-types.md            ← raw/atom/synthesis/principle 定义
│   ├── query-profiles.md        ← 6类query type定义
│   ├── manifest-schema.json     ← MANIFEST.jsonl 的 JSON Schema
│   ├── frontmatter-schema.json  ← Frontmatter 字段的 JSON Schema
│   ├── retrieval-schema.json    ← retrieval_index.jsonl 的 JSON Schema
│   ├── review-queue-schema.json ← review_queue.jsonl 的 JSON Schema
│   ├── query-outcomes-schema.json ← query_outcomes.jsonl 的 JSON Schema
│   └── lint-rules.md            ← 通用lint规则 + 数据流完整性检查
│
├── engine/                      ← 核心引擎（Python，agent-agnostic）
│   ├── __init__.py
│   ├── ingest.py                ← Two-Step ingest: Analyze → Decide → Record
│   ├── compile.py               ← raw → atom → synthesis 编译
│   ├── retrieve.py              ← 向量粗筛 → doc聚合 → 整页/section加载
│   ├── lint.py                  ← 契约检查 + 数据流完整性检查
│   ├── promote.py               ← principle晋升 + lifecycle管理
│   ├── sync.py                  ← 双向同步（workspace ↔ external store）
│   ├── vectorstore.py           ← 向量存储抽象层（SQLite + bge-large-zh）
│   ├── manifest.py              ← MANIFEST CRUD + 级联传播
│   └── propagation.py           ← 写入传播矩阵引擎（防孤岛核心）
│
├── adapters/                    ← Per-Agent 适配层
│   ├── hermes/                  ← Hermes Agent 适配
│   │   ├── README.md            ← 安装说明
│   │   ├── skills/              ← wiki-query, wiki-ingest, wiki-lint skills
│   │   ├── cron/                ← 定时任务配置（sync, lint, dream-cycle）
│   │   └── config.yaml          ← Hermes-specific 配置
│   │
│   ├── claude-code/             ← Claude Code 适配
│   │   ├── README.md
│   │   ├── CLAUDE.md            ← 知识库使用指令（写入CC工作区）
│   │   ├── hooks/               ← pre/post write hooks
│   │   └── commands/            ← /wiki-query, /wiki-ingest 等slash commands
│   │
│   ├── openclaw/                ← OpenClaw 适配
│   │   ├── README.md
│   │   ├── skills/              ← OpenClaw skill格式
│   │   ├── cron/                ← OpenClaw cron配置
│   │   └── config.yaml          ← OpenClaw-specific 配置
│   │
│   └── opencode/                ← OpenCode 适配
│       ├── README.md
│       ├── commands/            ← opencode run 包装脚本
│       └── config.yaml          ← OpenCode-specific 配置
│
├── scripts/                     ← 通用脚本
│   ├── init-wiki.sh             ← 初始化wiki目录结构
│   ├── build-retrieval-views.py ← 离线构建 retrieval_index
│   ├── rebuild-vectors.py       ← 向量库重建
│   ├── gate-check.py            ← Phase Gate 验收脚本
│   └── migrate-v1-to-v2.py      ← 旧格式迁移
│
├── templates/                   ← 页面模板
│   ├── raw.md.tmpl
│   ├── atom.md.tmpl
│   ├── synthesis.md.tmpl
│   └── principle.md.tmpl
│
├── docs/                        ← 设计文档
│   ├── design.md                ← 架构设计文档（含数据流闭环）
│   ├── phase-gates.md           ← Phase Gate 详细说明
│   ├── agent-differences.md     ← 四Agent能力差异与适配策略
│   └── migration-guide.md       ← 从现有知识库迁移指南
│
└── tests/                       ← 测试
    ├── test_ingest.py
    ├── test_compile.py
    ├── test_retrieve.py
    ├── test_lint.py
    ├── test_propagation.py      ← 数据流闭环测试
    └── test_manifest.py
```

## 核心抽象

### 1. aw-agent（统一知识代理）

Agent Wiki 的核心逻辑由独立 `aw-agent` 进程统一实现，并通过 MCP Server、CLI `aw`、REST API 暴露。各 Agent 不直接实现 query/ingest/lint/sync 逻辑，只配置 MCP 连接参数或 CLI 路径。

### 2. KnowledgeStore（知识存储接口）

```python
class KnowledgeStore(Protocol):
    def read_page(self, doc_id: str) -> Page: ...
    def write_page(self, page: Page) -> WriteResult: ...
    def get_manifest(self, doc_id: str) -> ManifestEntry: ...
    def update_manifest(self, entry: ManifestEntry) -> None: ...
```

存储接口由 `aw-agent` 的 StorageProvider 实现，不由各 Agent adapter 实现。

### 3. RetrievalProvider（检索提供者接口）

```python
class RetrievalProvider(Protocol):
    def search(self, query: str, top_k: int, filters: dict | None = None) -> list[SearchHit]: ...
    def upsert_cards(self, cards: list[RetrievalCard]) -> None: ...
    def delete_doc(self, wiki_id: str, doc_id: str) -> None: ...
```

Phase 1 默认使用 `retrieval_index.jsonl + lexical search`。向量检索是可选增强插件，不是最低可用路径。

### 4. PropagationEngine（传播引擎）

```python
class PropagationEngine:
    """写入即传播 — 每个写操作必须级联更新所有下游工件"""

    WRITE_PROPAGATION_MATRIX = {
        "create_raw": ["manifest", "provider_index", "retrieval_index", "log", "mirror"],
        "create_atom": ["manifest", "provider_index", "retrieval_index", "log", "mirror"],
        "update_compiled": ["manifest", "provider_index", "retrieval_index", "review_queue?", "log", "mirror"],
        "mark_disputed": ["manifest", "retrieval_index", "review_queue", "log", "mirror"],
        "promote_principle": ["manifest", "provider_index", "retrieval_index", "review_queue", "log", "mirror"],
        "archive_page": ["manifest", "provider_index", "retrieval_index", "log", "mirror"],
    }

    def propagate(self, operation: str, doc_id: str, **kwargs) -> PropagationResult:
        """执行写操作 + 级联传播，失败按优先级处理"""
        ...
```

### 5. AgentClientConfig（Agent薄客户端配置）

```python
class AgentClientConfig(BaseModel):
    agent_id: str
    actor_type: Literal["agent", "human", "service"]
    preferred_transport: Literal["mcp", "cli", "rest"]
    mcp_server_name: str | None = None
    cli_path: str | None = None
    rest_base_url: str | None = None
    identity_config_path: str | None = None
```

Agent adapter 只负责发现和调用 `aw-agent`，不拥有知识库核心逻辑。

## 数据流闭环（防孤岛）

**核心原则：写入即传播，不传播就不算写完。**

```
写操作 → Step 1: 写页面(原子) → Step 2: 更新manifest(原子)
       → Step 3: 更新provider index(可延迟) → Step 4: 更新retrieval_index(可延迟)
       → Step 5: 更新review_queue(条件) → Step 6: 写log(非阻塞)
       → Step 7: push mirror(可延迟)

Step 1-2失败 → 全回滚
Step 3-4失败 → 标记 index_stale，下次lint补修
Step 7失败 → 标记 mirror_pending，下次sync补推
```

## Phase Gate（防沉没）

| Gate | 验收标准 | 可脚本验证 |
|------|---------|-----------|
| A | Schema完整 + retrieval provider baseline + manifest有doc_id + Skillify字段覆盖100% | ✅ |
| B | 每个高频topic有compiled page + 空挂率<30% + route test≥80% + dependency无断链 | ✅ |
| C | 5类query跑通 + 平均步骤<3 + route test≥85% + dispute自动caveat | ✅ |
| D | stale发现<7天 + 周维护覆盖>80% + 压缩比>1:10 | ✅ |

**不能跳Gate。未通过回退到上一稳定阶段。每Gate留快照。**

## 快速开始

```bash
# 1. 克隆
git clone https://github.com/<your-org>/agent-wiki.git
cd agent-wiki

# 2. 初始化wiki目录
./scripts/init-wiki.sh /path/to/your/wiki-root

# 3. 为你的Agent安装适配器
# Hermes:
cp -r adapters/hermes/skills/* ~/.hermes/skills/

# Claude Code:
cp adapters/claude-code/CLAUDE.md ~/workspace/code/CLAUDE.md.append

# OpenClaw:
cp -r adapters/openclaw/skills/* ~/.openclaw/skills/

# OpenCode:
# 配置 opencode 的 config.yaml 指向 wiki-root

# 4. 构建初始索引
python3 scripts/build-retrieval-views.py --wiki-root /path/to/your/wiki-root

# 5. 验证
python3 scripts/gate-check.py --phase A --wiki-root /path/to/your/wiki-root
```

## License

MIT
