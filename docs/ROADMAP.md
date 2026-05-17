# v0.2 Roadmap — 数据地基 + 检索升级

> 核心原则：先修数据身份稳定性，再做检索升级。FTS5 不能建在不稳定的 doc_id 上。
> 架构约束：数据源必须可插拔（ExternalView adapter 协议，新增数据源只需加 adapter + registry 配置）

---

## v0.2.0 — 数据身份稳定 + 检索提速

### 执行顺序（按依赖关系排序）

| # | Task | 描述 | 依赖 | TDD |
|---|------|------|------|-----|
| T7 | **Hermes MCP env 修复** | 文档+测试对齐：Hermes config 显式传 ACTOR_TYPE/ID；MCP health 暴露 resolved actor；清理重复 env fallback 逻辑 | 无 | ✅ |
| T3 | **pull-view 同名冲突修复** | doc_id = slug(relative_path)，如 `agent-os_2026-04-15_MCP协议`；保留 vault_relative_path；旧数据一次性 migration；**ExternalView adapter 可插拔**：新增数据源只需加 adapter 类 + registry 配置 | T7 | ✅ |
| T4 | **maintain orphan cleanup** | ManifestRepo.delete()、TopicIndexRepo.delete()、RetrievalIndexRepo.rebuild()；maintain 自动清理 + 写 operation_log | T3 | ✅ |
| T1 | **FTS5 全文索引** | SQLiteFTSIndexProvider；运行态 DB 放 .agent-wiki/retrieval.db（不进 Git）；authority 仍保留 retrieval_index.jsonl（可 rebuild）；索引字段：doc_id/wiki_id/page_type/topic/problem_cluster/summary/content/sensitivity/updated_at | T3, T4 | ✅ |
| T2 | **jieba 中文分词** | Tokenizer protocol：BigramTokenizer 默认，JiebaTokenizer 可选；FTS5 用预分词 tokens 字段，不依赖 SQLite 中文 tokenizer 插件 | T1 | ✅ |
| T8 | **compile_update 端到端验证** | MCP compile_update 补齐 summary/aliases/confidence/contested/wikilinks 字段；实际执行一次 raw→atom 编译，验证 schema 质量 | T3 | ✅ |

### 中优（v0.2.0 scope 内尽量做）

| # | Task | 描述 |
|---|------|------|
| T5 | **wewe-rss 数据源接入** | ExternalView adapter（plain_markdown 复用）+ registry 配置；等 T3/T4 完成后再接入 |
| T9 | **性能基准测试** | 500/1000 页合成数据跑 query P50/P95；pytest -m perf |
| T10 | **索引一致性健康检查** | aw health/wiki.lint 检查 MANIFEST/pages/FTS doc_id 集合一致性 + rebuild 建议 |
| T11 | **query 排序改进** | page_type_boost + lexical_score + structured_score + purpose_boost + freshness；各分数写入 hit debug metadata |

### 不做

| # | 原因 |
|---|------|
| T6 query cache | FTS5 后 433 页不需要缓存；cache invalidation 是新复杂度 |
| push-view 双向同步 | 等 v0.1 观察期结束再评估 |
| 多 wiki | v0.3 |

### 数据源可插拔架构（老板要求）

```
registry.yaml
  external_views:
    - adapter: obsidian          # ObsidianAdapter
      mode: read_write
      path: ~/iCloud/Obsidian/
    - adapter: plain_markdown    # PlainMarkdownAdapter
      mode: read_only
      path: ~/hermes-projects/learning
    - adapter: plain_markdown    # 同一 adapter，不同路径
      mode: read_only
      path: ~/hermes-projects/knowledge
    - adapter: plain_markdown    # wewe-rss（T5 接入时只需加这行）
      mode: read_only
      path: ~/wewe-rss/output/
    - adapter: arxiv             # 未来：ArxivAdapter（只需实现 read() protocol）
      mode: read_only
      path: ~/papers/
```

**新增数据源 = 加 adapter 类 + registry 加一行配置**，不需要改 core 逻辑。

Adapter protocol：
```python
class ExternalViewAdapter(Protocol):
    def read(self, source_path: str) -> dict:  # → {"content": str, "adapter_metadata": dict}
        ...
    def write(self, target_path: str, content: str, metadata: dict) -> None:  # optional for read_write
        ...
```

---

## v0.2.0 Gate（验收标准）

| 指标 | v0.1 现状 | v0.2 目标 |
|------|----------|----------|
| pull-view 同名冲突 | 3 个文件互相覆盖 | **0 冲突**，3 个文件各有独立 doc_id |
| maintain 孤儿清理 | 手动清理 | 删除 pages/ 文件后 maintain 自动清理 MANIFEST/index |
| 查询延迟 P95 | ~60s（全扫描） | **<2s**（FTS5），最好 <500ms |
| MCP identity | env 缺失时报错 | 显式 env 优先 + registry fallback 兜底 |
| compile_update schema | 7 字段 | 补齐 summary/aliases/confidence/contested/wikilinks |
| 数据源接入 | 改代码 | **加配置即可** |
| FTS rebuild | N/A | 幂等，重复运行不产生重复索引 |
| 性能基准 | 无 | 500/1000 页 P50/P95 有数据 |

---

## 迁移策略（T3 配套）

T3 改 doc_id 后需要一次性 migration：

1. 旧 MANIFEST 里 basename doc_id → slug(relative_path) 新 doc_id
2. retrieval_index.jsonl 同步更新
3. topic_index.md 同步更新
4. 保留 vault_relative_path 不变
5. migration 脚本：`aw migrate --slugify-doc-ids --registry ... --wiki-id main`
6. migration 前自动备份 MANIFEST.jsonl → MANIFEST.jsonl.pre-migration
