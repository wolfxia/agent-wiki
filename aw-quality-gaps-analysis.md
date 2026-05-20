# agent-wiki 知识质量三维度缺口分析

> 现状数据驱动，不是凭感觉。Codex请先分析再设计，不要急着写代码。

## 背景

agent-wiki v0.5.0，1299个atom页，4737个MANIFEST条目。检索质量已达标（strict_recall@3=0.438，18条测试4.7⭐/5.0）。但知识准确性、时效性、来源可追溯性三个维度存在结构性缺口。

## 现状数据

### 来源可追溯性（最好）
- 1299个atom → 100%有source_refs → 100%可追溯到pages/下的raw文件
- 80%的atom引用2+个raw（多源交叉验证）
- **缺陷**：raw层原始URL/论文DOI没有结构化字段，混在正文中

### 时效性（有基础，缺机制）
- 知识时间跨度：2026-04-04 ~ 2026-05-20
- **无过期/失效检测**
- **无增量更新**（raw改了要全量重编译atom）
- **无版本管理**（atom覆盖写，无法回溯历史版本）

### 准确性（Schema合规好，验证缺）
- Claims: 100%, Applicability: 99%, Evidence: 99%
- **Relationship_Hints: 0%**, **Open_Questions: 0%**
- 无事实核查、无冲突检测、无置信度标注

## 需要Codex分析的三个问题

### Issue 1: Relationship_Hints 和 Open_Questions 为什么是0%？

**已知线索**：
- 编译prompt要求生成5个Schema字段（Claims/Applicability/Evidence/Relationship_Hints/Open_Questions）
- 但实际atom文件中只有前3个字段有内容
- 可能的原因：(a) prompt没强制生成这两个字段 (b) 编译器丢掉了这两个字段 (c) 生成但格式不对被过滤了

**需要分析**：
1. 读编译器代码（src/agent_wiki/application/compile.py 或相关文件），找到Schema字段生成的逻辑
2. 确认根因是prompt问题还是代码问题
3. 提出修复方案（不要直接写代码，先说清楚方案和风险）

### Issue 2: 时效性标记机制设计

**核心问题**：知识只有"写入"没有"老化"。2026-04-07的OS行业判断，5月市场变了，atom里还是旧结论。

**约束**：
- 不能靠LLM判断"知识是否过时"（不可靠）
- 不能每条知识都人工标注有效期（不现实）
- maintain已经14.9秒了，不能显著增加耗时

**需要分析**：
1. MANIFEST中是否已有时间元数据可利用（created_at/updated_at/mtime）
2. 哪些topic时效性要求高（OS行业动态 vs 架构原理），是否需要分类处理
3. "待验证"标记应该加在哪一层（MANIFEST? atom元数据? 查询时动态标记?）
4. 对检索排序的影响——过时知识应该降权还是标注caveat？

### Issue 3: Claim级别置信度标签

**现状**：关系层已有EXTRACTED/INFERRED/AMBIGUOUS三级置信度标签，但没下沉到Claim级别。

**核心问题**：atom的Claims里，"LLM推理加速市场2026年增长40%"这种数字和"Mobile-GS去掉排序实现116FPS"这种有论文依据的结论混在一起，无法区分。

**需要分析**：
1. 在Claim级别加置信度标签，是改编译prompt（让LLM标注）还是改后处理（规则检测+LLM辅助）？
2. 如果改编译prompt，已有1299个atom怎么办？（全量重编译成本？增量补标？）
3. 置信度标签对检索的影响——低置信度Claim构成的atom是否应该降权？
4. 和现有关系层EXTRACTED/INFERRED/AMBIGUOUS标签如何对齐？

## 交付要求

1. **先读代码，再出方案**。每个Issue给出：根因分析 → 方案选项（至少2个）→ 推荐方案 → 风险评估
2. **不要直接写代码**。输出分析报告即可，我审查后再决定是否推进
3. 重点关注向后兼容性——1299个已有atom不能因为改版全废了
4. 重点关注maintain性能——刚从5分钟降到15秒，不能倒退

## 相关文件

- 编译器: `src/agent_wiki/application/compile.py`
- Schema定义: 搜索 Claims/Applicability/Evidence/Relationship_Hints/Open_Questions 相关代码
- MANIFEST结构: `src/agent_wiki/infrastructure/storage/manifest_repo.py`
- 查询层: `src/agent_wiki/application/query.py`
- 关系层: `src/agent_wiki/application/relations.py`
- 编译prompt: 搜索 compile 相关的 prompt 模板
