# DFX + Security Design Task

为 agent-wiki 项目补充 DFX 设计文档，写入 `docs/dfx.md`。

## 要求

1. 覆盖以下 DFX 维度，每个维度包含：设计目标、Phase 1 实现、Phase 2 规划、关键决策
2. 同时补充 `docs/dfx.zh-CN.md` 中文版
3. 完成后 commit

## DFX 维度

### 1. 部署设计（Deployability）

- **进程模型**：独立 Agent 进程（MCP Server 长驻），不是嵌入式库
- **本机部署（Phase 1 主力）**：`pip install -e .` + `aw serve` 启动 MCP Server，launchd/systemd 管理
- **Docker 容器化**：单容器打包（知识库引擎 + CLI + MCP Server），docker-compose 编排（知识库 + 向量库可选）
- **网络部署（Phase 2）**：REST API 暴露，反向代理（nginx/caddy），TLS，OIDC 认证
- **配置管理**：wiki registry YAML + 环境变量 + .env 文件，12-factor 风格
- **灰度发布**：Git branch 隔离知识库版本，workspace 是运行时态可快速回滚

### 2. 可靠性设计（Reliability）

- **写入传播完整性**：7 项数据流检查（F1-F7），传播失败 → stale 标记 + 自动重试 + 2 次失败暂停
- **回滚机制**：Git revert 为兜底，stale 标记为软回滚，pending 状态为预回滚
- **容错**：MCP Server 崩溃 → launchd 自动拉起，查询降级（向量失败 → 词法检索）
- **数据备份**：Git remote 为天然备份，manifest+index 是 JSONL 可文本恢复

### 3. 安全设计（Security）

- **认证**：Phase 1 本机 loopback（127.0.0.1）+ local token；Phase 2 OIDC
- **授权**：T1/T2/T3 三层 Agent 能力 + Gate A/B/C 三级操作门控 + wiki_permissions 细粒度
- **传输安全**：Phase 1 stdio/本地 socket；Phase 2 TLS + mTLS（Agent 间）
- **数据安全**：知识库内容可能含敏感信息（API key、内部文档），需要：
  - 页面级敏感标记（frontmatter: `sensitivity: public/internal/confidential`）
  - 查询结果按 Agent tier 过滤（T3 不可见 confidential 内容）
  - Git 仓库支持 .gitattributes 加密（git-crypt）
  - 审计日志：每次操作记录 agent_id + 操作类型 + 目标 doc_id + 时间戳
- **输入校验**：doc_id 格式校验、content 长度限制、source_refs 存在性校验
- **沙箱隔离**：ContentAdapter 运行在受限环境，防止恶意 Markdown 注入

### 4. 可观测性设计（Observability）

- **日志**：每次操作 → operation_log.jsonl（结构化），log.md（人类可读）
- **指标**：查询延迟、命中率、传播成功率、stale 条目数
- **告警**：传播连续失败 ≥ 2 次 → 告警；stale 堆积 > 阈值 → 告警
- **周度报告**：weekly_review 自动生成，含低效查询模式 + 改进建议
- **健康检查**：`aw health` 端点，返回 7 项数据流检查结果

### 5. 性能设计（Performance）

- **查询延迟**：词法检索 < 100ms（本机 JSONL），向量检索 < 500ms
- **写入延迟**：capture_raw < 50ms（纯文件操作），compile_update < 200ms
- **并发**：Phase 1 乐观并发（单用户场景足够），Phase 2 显式锁
- **索引**：retrieval_index.jsonl 按需加载，大库分段；向量库 LRU 缓存
- **容量规划**：单库 10K 页面 ~ 50MB JSONL，向量库另计

### 6. 可维护性设计（Maintainability）

- **代码结构**：分层架构（application/domain/infrastructure/transports），依赖单向
- **测试**：32 个测试覆盖 M1-M6，每个 Milestone 有独立 test 文件
- **文档**：4 份核心文档 + 操作契约 + DFX 文档，中英双语
- **lint 规则**：manifest/page 一致性、manifest/index 一致性、孤立页面、断裂引用
- **迁移**：Schema 版本号 + 迁移脚本，向前兼容

### 7. 可扩展性设计（Extensibility）

- **ContentAdapter 可插拔**：Obsidian/Notion/PlainMarkdown，接口统一
- **检索提供者可插拔**：词法/向量/图谱，通过 registry 配置
- **传输层可插拔**：MCP/REST/CLI，通过 registry 配置
- **Agent 适配器可插拔**：T1/T2/T3 模板，新 Agent 只需实现 identity profile

## 输出格式

参考 docs/design.md 的风格，每个维度一个小节，包含：
- 设计目标
- 关键决策（决策 + 理由 + 替代方案）
- Phase 1 实现状态
- Phase 2 规划
- 与其他 DFX 维度的关联

同时写中文版 `docs/dfx.zh-CN.md`。
