# v0.2 Roadmap — Multi-Source Reliability + Retrieval Upgrade

> 目标：让 v0.1 的 433 页知识库真正好用 — 检索更快更准，数据源更多，系统更健壮

## 主题

**从"能跑"到"好用"** — v0.1 证明闭环可行，v0.2 让它日常可靠

---

## v0.2.0 — 词法检索升级 + 数据健壮性

### 高优（必须做）

| # | Task | 描述 | TDD |
|---|------|------|-----|
| T1 | **FTS5 全文索引** | SQLite FTS5 替代当前 `rgrep` 逐文件扫描，433 页查询从 60s→<1s | ✅ |
| T2 | **jieba 中文分词** | FTS5 + jieba tokenize，中文查询不再需要精确匹配关键词 | ✅ |
| T3 | **pull-view 同名文件冲突修复** | doc_id 加子目录前缀（如 `agent-os_2026-04-15_MCP协议`），避免跨子目录同名覆盖 | ✅ |
| T4 | **maintain 自动清理孤儿** | pages/ 文件删除后，MANIFEST/retrieval_index/topic_index 同步清理 | ✅ |

### 中优（应该做）

| # | Task | 描述 |
|---|------|------|
| T5 | **wewe-rss 数据源接入** | 微信公众号文章 → external_view(plain_markdown) → 自动 pull-view |
| T6 | **query 结果缓存** | 高频查询缓存 5min，减少重复扫描开销 |
| T7 | **MCP env 传递修复** | 排查 Hermes 为什么只传 WORKSPACE 不传 ACTOR_TYPE/ID（可能需给 Hermes 提 issue） |

### 低优（可以做）

| # | Task | 描述 |
|---|------|------|
| T8 | **compile_update 端到端验证** | 从 raw 页实际执行一次编译，产出 atom/synthesis 页 |
| T9 | **weekly-review 输出质量验证** | 确认 weekly-review cron 产出的内容有实际价值 |

---

## v0.2.1 — 语义检索增强（可选）

> 前提：FTS5+jieba 仍然不够用时才做

| # | Task | 描述 |
|---|------|------|
| T10 | **向量检索 Provider 接口** | 定义 `SemanticProvider` protocol，支持可插拔 embedding 模型 |
| T11 | **本地 embedding 索引** | 用 sentence-transformers 或本地 API 生成 embedding，存入 SQLite vec 扩展 |
| T12 | **混合检索路由** | RetrievalRouter 支持 lexical→semantic fallback 或并行 merge |

---

## 验收标准（v0.2.0 Gate）

| 指标 | v0.1 现状 | v0.2 目标 |
|------|----------|----------|
| 查询延迟 | 60s（全扫描） | <2s（FTS5） |
| 中文查询命中率 | 依赖精确关键词 | jieba 分词后模糊匹配 |
| 同名文件冲突 | 3 个文件互相覆盖 | 0 冲突 |
| 孤儿 MANIFEST 条目 | 手动清理 | maintain 自动清理 |
| 数据源 | 3（Obsidian/learning/knowledge） | 4（+wewe-rss） |

---

## 不做的事（v0.2 scope 外）

- 多 wiki 支持（v0.3）
- REST API（v0.3）
- 权限 gate 复杂逻辑（v0.3）
- 4-Signal Graph / Louvain 聚类（页数<1000 不需要）
- Obsidian 双向同步（push-view，等 v0.1 观察期结束再评估）
