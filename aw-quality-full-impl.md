# agent-wiki 知识质量全方位实施计划

> 一次到位，P0-P3全部实施。TDD，每Phase独立commit。

## 当前状态
- 基线：397 passed, 1 failed (test_identity_resolution 无关)
- 分支：codex-work（已同步main）
- 1299个已有atom，4737个MANIFEST条目
- maintain ~15秒

## Phase 1: 补齐时间戳基础设施 [P0]

### 目标
让现有的staleness检测框架真正可用，查询时展示caveat。

### 具体改动
1. **propagation.py** — `capture_raw`和`compile_update`写入MANIFEST时，设置`created_at`和`updated_at`（ISO 8601字符串）。upsert时保留旧`created_at`，只刷新`updated_at`。旧条目缺失时间戳时fallback为文件mtime或null。
2. **manifest_repo.py** — `upsert()`和`batch_upsert()`处理created_at/updated_at逻辑。
3. **query.py** — L2 context返回时，对`updated_at`超过阈值（默认30天）的atom加`possibly_stale: true` caveat。默认不降权，只标注。
4. **配置化** — `freshness_class`或`volatile_topics`配置，不同topic可配不同阈值。架构原理类(evergreen)阈值可设90天或null，行业动态类可设14天。

### 测试要求
- 新raw写入有created_at/updated_at
- compile更新时created_at不变、updated_at刷新
- 旧条目缺失时间戳时fallback正确
- 查询返回stale caveat（有时间戳的）
- 旧条目不加stale caveat（时间戳unknown）

### commit msg
`feat: add created_at/updated_at timestamps to manifest entries and query freshness caveats`

## Phase 2: 编译Schema五节强制 + Gate检查 [P1]

### 目标
新编译的atom必须包含全部5个schema section，杜绝0%覆盖率。

### 具体改动
1. **compile_apply.py** — JSON schema增加`relationship_hints`字段（`list[{source_doc, target_concept, hint_type}]`）。prompt中"when relevant"改为强制输出，缺失写"None identified from source evidence."。
2. **compile_execute.py** — `CompileGeneratedInput`增加`relationship_hints`和`open_questions`字段，从structured output提取不再丢弃。写入atom页面时确保全部5个section都有内容。
3. **compile_quality_gate.py** — gate检查5个section都存在（Claims/Applicability/Evidence/Relationship_Hints/Open_Questions）。**仅对新编译生效**，backfill/旧atom不检查。
4. **compile_apply.py structured output schema** — claims改为`list[{text, evidence_refs, confidence_label}]`，confidence_label复用EXTRACTED/INFERRED/AMBIGUOUS。

### 测试要求
- prompt生成包含5个section的atom
- 缺失任一section时gate拒绝
- structured output正确提取relationship_hints和open_questions
- 旧atom页面不受gate影响
- claims有confidence_label

### commit msg
`feat: enforce 5-section schema in compile with quality gate check`

## Phase 3: Claim Annotations Sidecar + 增量Backfill [P1]

### 目标
为每个atom的claims建立结构化置信度标注，支持增量补标旧数据。

### 具体改动
1. **Sidecar存储** — 新增`.agent-wiki/claim_annotations.jsonl`，格式：`{doc_id, claims: [{text, confidence_label, evidence_refs, rationale}], annotated_at, annotation_method: "compile"|"rule"|"llm_review"}`
2. **编译时写入** — 新atom编译完成后，claims annotations直接写入sidecar，method="compile"。
3. **规则后处理** — 新增`ClaimAnnotationService`：
   - 解析atom的## Claims section
   - 规则识别：有source ref/doc_id/DOI/论文引用 → EXTRACTED；有数字/百分比但无引用 → INFERRED；证据冲突/模棱两可 → AMBIGUOUS
   - 增量处理：只处理mtime变化的页面，用fingerprint state文件追踪
   - method="rule"
4. **maintain集成** — maintain中加入`annotate_claims`步骤，限量cap（默认50条/次），基于mtime增量。不要全量扫描。
5. **查询集成** — L2/L3返回时附带claim confidence labels，格式：`claims: [{text, confidence, evidence_refs}]`

### 测试要求
- 新编译atom的claims自动写入sidecar
- 规则标注正确识别EXTRACTED/INFERRED/AMBIGUOUS
- 增量backfill只处理新/变化页面
- sidecar写入和读取的round-trip正确
- maintain中annotate_claims步骤限量生效
- 查询L2返回claim confidence

### commit msg
`feat: claim annotations sidecar with incremental rule-based backfill`

## Phase 4: 查询展示集成 [P2]

### 目标
L2/L3查询结果展示claim confidence和freshness caveat，review_queue支持低置信度claim。

### 具体改动
1. **query.py L2** — 返回结果附加：
   - `freshness: {status: "fresh"|"possibly_stale"|"unknown", updated_at, stale_threshold_days}`
   - `claims: [{text, confidence, evidence_refs}]`
2. **query.py L3** — 完整证据链，展示claim→evidence_refs→source page的追溯路径
3. **review_queue** — AMBIGUOUS confidence的claim自动入review_queue，标注`review_reason: "ambiguous_claim"`

### 测试要求
- L2返回freshness和claims字段
- L3返回完整证据链
- AMBIGUOUS claim进入review_queue
- EXTRACTED/INFERRED claim不进入review_queue

### commit msg
`feat: integrate claim confidence and freshness into query L2/L3 output`

## Phase 5: 可配置降权机制 [P3]

### 目标
可选的stale/low-confidence降权，默认关闭，需eval验证后才启用。

### 具体改动
1. **配置** — `registry.yaml`或编译配置中增加：
   ```yaml
   retrieval:
     freshness_penalty:
       enabled: false  # 默认关闭
       stale_days: 30
       penalty_weight: 0.1
     confidence_penalty:
       enabled: false  # 默认关闭
       ambiguous_penalty_weight: 0.05
   ```
2. **query.py排序** — 当enabled时，对stale atom减分，对AMBIGUOUS claim为主的atom减分。权重可配置。
3. **eval gate** — 降权启用前必须跑retrieval_queries_v2.jsonl验证recall不降。如果recall下降超过5%，自动回退。

### 测试要求
- 默认关闭时不影响排序
- 启用后stale atom排序降低
- 启用后AMBIGUOUS atom排序降低
- 权重可配置
- 降权不影响recall超过5%的阈值

### commit msg
`feat: configurable freshness and confidence ranking penalties with eval gate`

## 铁律

1. **TDD** — 先写RED test，再GREEN实现，每个Phase独立commit
2. **向后兼容** — 旧1299个atom不能废，缺字段时状态是unknown/not_annotated，不是failed
3. **maintain性能** — 不能显著超过15秒。增量处理+限量cap，不做全量扫描
4. **不调LLM做判断** — staleness靠时间戳+配置，不靠LLM
5. **每个Phase跑全量pytest** — 397→只升不降
6. **claim annotations存sidecar** — 不塞MANIFEST（避免每行变大拖慢读写）
7. **降权默认关闭** — P3是可选功能，不启用时零影响

## 完成后

1. 在main上跑全量pytest
2. 重启aw-agent
3. 跑一次maintain确认性能
4. 跑eval验证recall不降
