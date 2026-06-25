# OmniMind AI — TODO 清单

> 更新于 2026-06-17。实际配置已写入 `.env`（受 `.gitignore` 保护，禁止提交）。

## 🔴 阻塞项（缺这些无法跑通端到端）

- [ ] **DashScope（百炼）API Key** — `.env` 中 `DASHSCOPE_API_KEY=<待提供>`，缺失则 embedding + rerank 不可用，RAG 检索无法工作

## 🟠 集成验证（凭证到位后立即做）

- [x] **PG 连通性验证** — `.env` 真实 DSN 连 `81.70.235.39:54321/omnimind_ai`，`xxer` 账号可达
- [x] **运行 Alembic 迁移** — `alembic upgrade head`，在独立 `omnimind_ai` 库的 `public` schema 下建表（10 表 + alembic_version）
- [ ] **MinIO 只读验证** — 确认 `omnimind-files` bucket 可访问、`omnimind/` 前缀路径规划落地（MinIO 仅只读，不写）
- [ ] **DeepSeek 连通性冒烟** — API Key 已配置，验证 base_url、模型名、配额正常
- [ ] **百炼连通性冒烟** — API Key 到位后验证 embedding + rerank

## 🟡 内部联调（Java 侧到位后）

- [ ] **Java 回调地址 + Token** — `JAVA_BASE_URL`、`JAVA_INTERNAL_TOKEN` 仍占位，回调通知 Java 网关需要
- [ ] **INTERNAL_TOKEN** — 与 Java 网关共享的内部鉴权令牌，仍占位，影响入站鉴权

## 🟢 端到端功能测试（手动）

- [ ] **解析链路** — 上传/指定 tender_doc → 解析 → chunk → 向量入库
- [ ] **RAG 检索** — 召回 + RRF 融合 + rerank 全链路
- [ ] **审查 Agent**（Phase 6）— 创建审查任务 → 后台跑 → 轮询进度 → 拉风险 → 处置
- [ ] **编写 Agent**（Phase 7）— 创建任务 → prepare（评分点+大纲）→ SSE 流式生成章节 → 应答检查 → 导出草稿

## ⚪ 工程收尾

- [ ] **Docker 构建验证** — `docker build` 跑通，容器内 `alembic upgrade` + uvicorn 启动正常
- [ ] **`.env.example` 同步** — 确认结构与 `.env` 一致（不含真实值），便于他人对照
- [ ] **CI / 单测** — 当前 26 个纯逻辑单测全过；考虑补集成测试（需测试库或 mock 边界）

---

## 已完成 / 已决策

- [x] DeepSeek API Key — `sk-3910cd...` 已配置
- [x] Milvus 地址 — `81.70.235.39:19530` 已配置
- [x] PG / MinIO 真实凭证写入 `.env`（密码 `++` 在 DSN 中编码为 `%2B%2B`）
- [x] Redis — 按决定**跳过**，项目无依赖，不加 Redis 客户端
- [x] 命名空间 — `omnimind` 前缀，MinIO 保持只读
- [x] Phase 1-8 代码全部完成，已提交 main + develop 并推送远程

**最关键阻塞**：仅剩百炼 API Key（🔴 项），拿到后 🟠 集成验证可立刻开展。
