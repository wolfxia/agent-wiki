---
title: Dream Cycle Deep Maintenance Design
date: 2026-05-18
status: approved
phase: v0.3-phase3
depends_on: [typed-knowledge-graph, compile-pipeline]
risk_gate: B-level
---

# Dream Cycle — 夜间深度整理

## 1. Problem Statement

当前编译管道（compile-execute）只做单维度编译：raw → atom。缺少：

1. **跨atom综合**：不同topic的atom页之间可能存在深层关联（如"约束前置"跨3DGS、NPU调度、事件相机三域出现），但没有机制发现和表达这些关联
2. **Orphan漂移**：部分raw笔记可能永远不会被编译（不在任何compile_suggestion中），部分atom可能不被任何其他页引用，形成知识孤岛
3. **质量退化**：随着知识积累，早期atom页可能过时或质量不足，缺少自动审查机制

## 2. Design Goals

1. **synthesis页自动生成**：发现跨atom关联，用LLM生成综合分析页
2. **Orphan检测与报告**：定期扫描未关联的raw/atom页
3. **质量审查**：自动标记低质量页，写入review_queue
4. **零LLM检测 + LLM生成**：关联发现用关键词+图谱（零LLM），只有最终synthesis写作用LLM

## 3. Architecture

### 3.1 Pipeline

```text
aw dream-cycle
  ├── Step 1: orphan_scan()        → orphan report
  ├── Step 2: cross_reference()    → candidate groups (zero-LLM)
  ├── Step 3: synthesis_generate() → synthesis pages (LLM)
  └── Step 4: quality_review()     → review_queue items
```

### 3.2 Orphan Scan

**输入**：MANIFEST.jsonl + knowledge_graph.jsonl + review_queue.jsonl
**输出**：orphan report（JSONL格式，写入 .agent-wiki/dream_cycle_orphans.jsonl）

检测规则：
- raw页不在任何compile_suggestion的source_docs中 → raw orphan
- atom页不被任何synthesis引用，也不在knowledge_graph.jsonl的任何关系中 → atom orphan
- 重复检测：上次报告中的orphan如果仍存在，保留首次发现时间

**零LLM**：纯数据查询

### 3.3 Cross-Reference Analysis

**输入**：所有atom页 + knowledge_graph.jsonl
**输出**：candidate_groups（List[CandidateGroup]）

```python
@dataclass
class CandidateGroup:
    atom_ids: list[str]        # 2+ atom页ID
    shared_keywords: list[str] # 共享关键词
    graph_relations: list[str] # 图谱中的关系（如有）
    strength: float            # 关联强度 0-1
```

关联发现策略（零LLM）：
1. **关键词重叠**：提取每个atom页的frontmatter keywords + 标题分词，计算Jaccard相似度
2. **图谱关系**：从knowledge_graph.jsonl找atom页中实体的间接关系
3. **Topic交叉**：不同topic下的atom如果problem_cluster相同，提高关联权重

筛选：strength >= 0.3 的组才进入下一步

### 3.4 Synthesis Generation

**输入**：candidate_groups（Step 2输出）
**输出**：synthesis页（写入truth zone）

复用 `CompileApplyService` 的LLM调用逻辑（compile.llm配置）。

synthesis页结构：
```yaml
---
page_type: synthesis
source_atoms: [atom-xxx-001, atom-yyy-002]
topic: cross-domain
problem_cluster: meta-principles
generated_by: dream-cycle
generated_at: 2026-05-18T03:00:00
---
# 跨域元原理：约束前置

## 关联知识
- [[atom-3dgs-mobile-3dgs-mobile-0001]] — 3DGS训练中的约束前置
- [[atom-agent-os-agent-os-0005]] — NPU调度的约束前置

## 综合分析
...
```

B-level gate：synthesis写入走 compile_update 的审核路径，source_refs必须引用存在的atom页。

限制：每次dream-cycle最多生成 `max_synthesis_per_run`（默认10）个synthesis页。

### 3.5 Quality Review

**输入**：所有atom + synthesis页
**输出**：review_queue items

检查项：
- 完整性：frontmatter必需字段是否齐全
- 时效性：超过30天未更新的atom页标记为"可能过时"
- 引用完整性：source_refs中的页面是否都存在
- 内容长度：过短（<200字）的atom页标记

质量分复用maintain中已有的quality_report逻辑。

## 4. Configuration

```yaml
# registry.yaml
dream_cycle:
  enabled: true
  schedule: "0 3 * * *"  # 凌晨3点
  synthesis:
    min_atoms: 2                # 最少关联atom数
    max_synthesis_per_run: 10   # 每次最多生成
    strength_threshold: 0.3     # 关联强度阈值
  quality:
    min_score: 50               # 低于此分数标记审核
    staleness_days: 30          # 超过此天数标记过时
  orphan:
    report_path: .agent-wiki/dream_cycle_orphans.jsonl
```

## 5. CLI

```bash
aw dream-cycle                    # 执行完整流程
aw dream-cycle --step orphan      # 只跑orphan检测
aw dream-cycle --step cross-ref   # 只跑交叉引用
aw dream-cycle --step synthesis   # 只跑synthesis生成
aw dream-cycle --step quality     # 只跑质量审查
aw dream-cycle --dry-run          # 只输出计划，不写入
```

## 6. New Files

| File | Purpose |
|------|---------|
| `src/agent_wiki/application/dream_cycle.py` | DreamCycleService 主逻辑 |
| `src/agent_wiki/domain/candidate_group.py` | CandidateGroup 数据类 |
| `tests/test_dream_cycle.py` | 单元测试 |
| `tests/test_cross_reference.py` | 交叉引用测试 |

## 7. Reuse

- `ManifestRepository` — 读取所有页元数据
- `ReviewQueueRepository` — 写入质量审查项
- `CompileApplyService._call_llm()` — LLM调用
- `knowledge_graph.jsonl` — 图谱关系查询
- `CompileUpdateService` — synthesis页写入（走B-level gate）

## 8. Testing Strategy

1. **orphan_scan**：创建孤立raw/atom页，验证检测
2. **cross_reference**：创建2个共享关键词的atom页，验证candidate_group生成
3. **synthesis_generate**：mock LLM，验证synthesis页结构和frontmatter
4. **quality_review**：创建缺失字段的atom页，验证review_queue写入
5. **integration**：完整dream-cycle流程，验证端到端

## 9. Phase Boundaries

| Item | Phase 3 | Phase 4+ |
|------|---------|----------|
| orphan scan | ✅ 实现 | - |
| cross-reference (keyword+graph) | ✅ 实现 | - |
| synthesis generation | ✅ 实现 | - |
| quality review | ✅ 基础版 | 增量改进 |
| provenance claim-level marking | - | Phase 4 |
| BrainBench-style evaluation | - | Phase 4+ |
