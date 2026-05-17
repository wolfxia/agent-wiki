# Agent Wiki — Phase 1 剩余缺口清单

> 2026-05-17 | 当前基线：139 passed | 69 commits
> 上一轮 Codex 完成：MCP transport (FastMCP stdio) + 共享权限 + Obsidian push-view

## 已完成 ✅

- [x] 核心领域逻辑 (capture_raw / compile_update / query / lint / sync / feedback / weekly_review / approvals)
- [x] 注册表驱动多库配置
- [x] 权限/身份/风控门 (A/B/C级)
- [x] 跨库查询 + shared wiki 限制
- [x] MCP FastMCP stdio server (5 tools: wiki.query/capture_raw/compile_update/lint/sync)
- [x] 共享权限 (hermes/openclaw/claude-code 共享, codex 低权限)
- [x] Obsidian push-view (frontmatter保留 + 知识图谱索引)
- [x] CLI 基础命令 (info/serve/query/capture-raw/compile-update/lint/maintain)
- [x] 质量评估框架 (3层6维) + MaintenanceService
- [x] CC + Codex Phase 1 代码评审

## 缺口列表（按依赖关系排序）

### 缺口1 [基础设施] REST API 完善
**现状**：REST app 只有 /health + /query + /capture-raw，缺少 compile_update / lint / sync / feedback / weekly-review / approvals
**要求**：
- a) 补齐 compile-update / lint / sync / feedback / weekly-review / approvals 端点
- b) 所有端点走统一 identity resolution (Bearer token → IdentityResolver)
- c) 每个 B/C 级端点必须做 gate check
- d) 新增 test_rest_app.py 覆盖所有新端点
**交付**：全量 pytest pass + REST 端点功能完备

### 缺口2 [基础设施] CLI workflow-complete
**现状**：CLI 有 query/capture-raw/compile-update/lint/maintain/serve，缺少 sync/feedback/weekly-review/approvals
**要求**：
- a) 补齐 `aw sync` (status/pull-view/push-view 子命令) 
- b) 补齐 `aw feedback` (记录反馈 + review queue 插入)
- c) 补齐 `aw weekly-review` (生成周报)
- d) 补齐 `aw approvals` (proposal/approve/reject 子命令)
- e) 每个新命令对应 smoke test
**交付**：CLI 命令与 MCP tool surface 对齐 + 全量 pass

### 缺口3 [核心闭环] MaintenanceService 串通自进化闭环
**现状**：MaintenanceService.run() 调了 CompileSuggestService + FastFeedbackService + RelationsService，但：
- 没有被任何定时/cron机制触发
- compile_suggest / fast_feedback 的 detect_and_enqueue 是空壳还是真实实现需验证
- quality_report 只有输出没有触发行为改进
**要求**：
- a) 验证 CompileSuggestService.detect_and_enqueue 是否真正扫描 manifest 找到超阈值 cluster 并写入 review_queue
- b) 验证 FastFeedbackService.detect_and_enqueue 是否真正扫描 query_outcomes 找到连续零命中并写入 review_queue
- c) 如果是空壳则实现真实逻辑
- d) MaintenanceService.run() 输出的 summary 要包含具体 action items（不仅是计数）
- e) QualityReportService.generate() 的结果要能被 weekly_review 消费
**交付**：maintenance → review_queue → weekly_review 闭环可验证

### 缺口4 [核心闭环] weekly-review 消费 review_queue + query_outcomes
**现状**：WeeklyReviewService 存在，但需要验证它是否真正消费了 review_queue + query_outcomes + feedback 数据
**要求**：
- a) 验证 WeeklyReviewService 是否从 review_queue.jsonl 读取 open/in_progress items
- b) 验证是否从 query_outcomes.jsonl 读取 miss_signal
- c) 验证是否从 feedback 记录读取用户反馈
- d) 输出结构化报告（不是空壳 placeholder）
- e) 新增 test_weekly_review.py 覆盖真实数据消费
**交付**：weekly review 从3个数据源消费 + 输出结构化报告

### 缺口5 [基础设施] aw-agent 长驻进程 + venv
**现状**：没有虚拟环境，`aw serve` 有入口但没有部署流程
**要求**：
- a) 创建 .venv 并安装项目 (pip install -e ".[dev]")
- b) 验证 `aw --help` 在 venv 内可用
- c) 验证 `aw serve` 能启动 MCP stdio server（可用 echo 测试）
- d) 补 Dockerfile（Phase 1 简单版：Python 3.11 + pip install）
- e) 补 pyproject.toml 的 [project.scripts] 确保 aw + aw-agent 入口正确
**交付**：venv 内 pytest pass + `aw --help` + `aw serve` 可启动

### 缺口6 [验证] 端到端集成测试
**现状**：各模块单元测试有，但没有跨 workflow 的集成测试
**要求**：
- a) 新增 tests/test_e2e_workflow.py
- b) 测试完整 workflow: capture_raw → compile_update → query → lint → sync → feedback → weekly_review
- c) 验证每步的输出是下步的有效输入
- d) 验证 review_queue 在 maintenance 后有新 items
- e) 验证 weekly_review 能消费所有前置数据
**交付**：1个端到端测试通过

---

## 执行建议

1. **缺口5先做**（venv环境），否则后面测试环境不稳定
2. **缺口1+2并行**（REST+CLI都是transport层，互相独立）
3. **缺口3+4连做**（自进化闭环是核心价值）
4. **缺口6最后**（集成测试依赖所有前置功能完备）

## 设计文档参考

- `docs/superpowers/specs/2026-05-16-phase-1-design.md` — Phase 1 完整规格
- `docs/superpowers/specs/2026-05-17-transport-shared-access-obsidian-design.md` — MCP/Obsidian规格
- `docs/superpowers/specs/2026-05-16-quality-evaluation-design.md` — 质量评估规格
- `docs/design.md` — 架构设计
- `AGENTS.md` — 项目规范
