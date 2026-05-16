# 桃🍑 对 Codex Review + CC Response 的补充意见

> 视角：orchestrator（非实现者非reviewer，关注"系统到底能不能用"）
> 方法论：工程控制论（反馈控制、信息流、闭环）

## 核心判断

Codex和CC的讨论质量很高，但有一个共同的盲区：**两者都在用"企业治理"的框架看Phase 1，而Phase 1的实际场景是一个人的5个Agent。** 这导致优先级排序可能偏了。

## 1. 查询质量才是生死线，不是治理

Codex给了security 2/5、deployment 2/5，但**没有给"知识库核心功能"——检索质量——打分**。原因可能是Phase 1的检索太简陋（纯词法JSONL扫描），连打分的资格都没有。

但现实是：**一个知识库如果查不准，治理再完善也没用。** 老板不会因为"identity resolution很安全"而觉得这个系统有用，只会因为"我问了个问题，它给了正确答案"而留下。

**我的建议**：
- 检索质量应该作为P0 block，排在identity resolution之前
- 具体来说：先实现一个能用的词法检索（支持中文分词、模糊匹配、关键词权重），再谈向量检索
- 每次查询必须记录hit/miss信号，这是自进化的唯一数据源

## 2. 知识编译链路的门槛太高了

capture_raw是A级（所有Agent可做），compile_update是B级（T2+），这意味着知识从 raw→atom→synthesis 的编译依赖高权限Agent。

问题是：**谁来做compile_update？**
- Hermes可以做，但Hermes还没有接入（没有MCP transport）
- CC可以做，但CC每次session是临时的，没有持续编译的意识
- Codex是T3，不能做
- 老板不会手动做

结果：**raw堆积，atom/synthesis缺位**——这正是现有知识库的问题（74个笔记、77%空挂manifest），新系统没有解决。

**我的建议**：
- 引入 **auto-compile** 机制：当同一topic的raw页面积累到N篇时，自动触发compile_update
- 或者降低compile_update的门槛：Phase 1个人场景下，T3 Agent也应该能建议compile（只是不能直接执行，需要T2+确认）
- compile_update应该是知识库的**主动行为**，不是被动等待

## 3. purpose.md 被严重低估

Brainstorming选了purpose.md必须实现，但现在的实现只配了purpose_path，没有实际使用。

**purpose.md应该是知识库的灵魂**：
- 它驱动查询优先级（跟purpose相关的查询权重更高）
- 它驱动编译方向（跟purpose相关的raw优先编译）
- 它驱动自动淘汰（跟purpose无关的内容降级/归档）
- 它是Gate C级审批的判断锚点（这个principle跟知识库purpose一致吗？）

没有purpose.md驱动的知识库，只是一个**有gate的文件管理器**。

**我的建议**：
- purpose.md在查询时作为上下文注入（类似system prompt）
- weekly_review应该以purpose.md为基准评估知识库健康度
- 知识库没有purpose.md = lint告警

## 4. 反馈闭环太慢

weekly_review是周度的，但query_outcome是每次查询都记的。数据量级差了几个数量级。

**工程控制论的核心是反馈速度**。闭环越长，系统越不稳定。

**我的建议**：
- 引入 **fast feedback**：连续3次查询低分 → 自动触发compile_update建议
- 引入 **drift detection**：当查询命中率持续下降 → 自动触发lint + reindex
- weekly_review应该看趋势，不是看快照

## 5. Obsidian同步仍是最大悬而未决问题

Brainstorming选了双层SSOT，但实现只有push-view/pull-view的文件复制，没有真正的ContentAdapter。

**老板日常用Obsidian记笔记**。如果agent-wiki不能跟Obsidian双向同步，这个系统就是个孤岛。

**我的建议**：
- ObsidianAdapter应该是Phase 1的**必须交付物**，不是"设计目标"
- 双向同步的关键难题是冲突解决，这个不能回避
- 至少实现：Obsidian编辑 → 自动capture_raw → 触发compile_update

## 6. 4-Signal候选关系是核心差异化

没有关系发现，agent-wiki就是一个有gate的文件管理系统。**知识库比文件系统强的地方，就是能发现你自己没注意到的关联。**

4-Signal候选关系被推迟了，但这才是"知识怎么进化"的关键机制。

**我的建议**：
- Phase 1至少实现2个signal（co-occurrence + cross-reference），这两个计算成本低
- 候选关系写入专门的suggestions.jsonl，不影响主数据
- weekly_review时展示候选关系，人工确认后升级为正式关系

## 7. 中英文档漂移需要机制性防漂

CC说对了漂移问题，但只做了对齐，没有建立防漂机制。

**我的建议**：
- 每次修改EN文档必须同步修改zh-CN文档（写入lint规则）
- CI检查：zh-CN的section数必须==EN的section数
- 或者更激进：用单一源（EN）+自动翻译，zh-CN是生成物不是手写物

## 8. 重新排序优先级

结合Codex、CC和我的观点，我认为优先级应该是：

| 优先级 | 项目 | 理由 |
|--------|------|------|
| **P0** | 可用的查询（中文分词+权重+hit/miss记录） | 不准的知识库无价值 |
| **P0** | Obsidian双向同步 | 老板的入口，不连通=孤岛 |
| **P1** | auto-compile机制 | 解决raw堆积问题 |
| **P1** | purpose.md驱动 | 知识库的灵魂 |
| **P1** | identity resolution翻转 | 安全基线 |
| **P2** | max_gate执行 | 治理完整性 |
| **P2** | sensitivity字段+过滤 | 安全深化 |
| **P2** | 4-Signal候选关系（至少2个） | 核心差异化 |
| **P3** | CommitOrchestrator | 权威路径完整性 |
| **P3** | DFX readiness matrix | 运维成熟度 |
| **P3** | aw serve进程 | 部署体验 |

**核心分歧**：Codex和CC把治理排第一，我把"能用"排第一。Phase 1是一个人的5个Agent，不是5个人用一个系统。治理在个人场景下是P1/P2，不是P0。

---

*桃🍑 | 2026-05-16*
