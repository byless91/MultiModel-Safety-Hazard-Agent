# 多模态基层安全隐患智能研判与处置辅助系统

面向社区网格员、厂区安全员、林区巡查员的“拍照输入、智能研判、自动成文、证据溯源、人机复核”系统。当前为 MVP 骨架，无 API Key 时使用 Mock 模式即可跑通完整演示链路。

## 技术栈

- 后端：Python 3.11+、FastAPI、SQLAlchemy、SQLite
- 智能体：LangGraph StateGraph 条件路由工作流（分析、追问、检索、二次研判、融合研判、证据判定、生成/人工复核），模型失败自动回退 Mock
- 模型：Qwen2.5-VL / GLM-4V-Flash（OpenAI 兼容 API），Mock 模式无需 Key
- 检索：FAISS 或 NumPy 兜底向量检索，可选规则重排 Reranker（`RERANKER_ENABLED`，执行 Vector Top-K → 重排 → Top-N）
- 前端：Vue 3、TypeScript、Vite、Element Plus、Pinia

## 目录结构

```text
backend/
  app/api/        FastAPI 路由
  app/core/       配置与数据库
  app/models/     SQLAlchemy 模型
  app/schemas/    Pydantic 输入输出
  app/services/   providers、rag、workflow、report
  data/knowledge/ 演示知识库
  tests/          pytest 接口测试
frontend/
  src/views/      页面
  src/components/ 研判结果组件
  src/stores/     Pinia 状态
```

## 快速启动

### 后端

```bash
cd backend
cp .env.example .env
.\.venv\Scripts\python.exe -m pip install -e ".[faiss]"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8001
```

注意用 `backend\.venv`，项目根目录下的 `.venv` 是旧环境，不要使用。

也可以不安装 faiss-cpu，只安装基础依赖：`.\.venv\Scripts\python.exe -m pip install -e .`，系统会自动回退到 NumPy 检索。

接口文档：`http://localhost:8001/docs`

### 前端

```bash
cd frontend
pnpm install
pnpm dev
```

浏览器访问 `http://localhost:5173`。Vite 已配置 `/api` 代理到 `http://localhost:8001`，可用环境变量 `VITE_API_PROXY` 覆盖。

## 模型接入

默认 `PROVIDER_MODE=auto`：没有配置 API Key 时自动使用 Mock；配置后自动切换到真实模型。

```env
DASHSCOPE_API_KEY=你的阿里云百炼 Key
VISION_MODEL=qwen-vl-plus
TEXT_MODEL=qwen-plus
EMBEDDING_MODEL=text-embedding-v3
```

也支持智谱：配置 `ZHIPU_API_KEY` 与 `ZHIPU_BASE_URL`。

## 部署（B6：Docker 与 PostgreSQL）

```powershell
# 默认（SQLite 单节点）：构建并启动全栈，前端 http://localhost:8080
docker compose up -d --build

# PostgreSQL 变体（多副本/多 worker 部署必须使用）
docker compose -f docker-compose.pg.yml up -d --build

# 首次使用 jwt 认证时建管理员（容器内）
docker compose exec backend python scripts/create_user.py --username admin --role admin
```

- 后端镜像启动时自动执行 `alembic upgrade head`（旧库自动纳入版本管理）；
- `DATABASE_URL` 切 `postgresql+psycopg://...` 即用 PG（安装 `.[pg]` extra），CI 有 PG 全量测试矩阵；
- `/metrics` 供内网监控抓取；健康检查 `/api/v1/health`。

## 质量保障（B6：评测回归门禁）

`scripts/check_eval_baseline.py`：mock 模式跑 60 条评测（v2 数据集）并与
`docs/evaluation` 基线对比——类别准确率、人工复核率劣化 >2pp 或不安全自动
通过率上升 >2pp 即失败。CI 的 `eval-gate` job 每次 push 都会执行；本地：

```powershell
.ackend\.venv\Scripts\python.exe scripts\check_eval_baseline.py
```

## 认证与权限（B4）

`AUTH_MODE` 三档：

| 模式 | 行为 | 适用 |
|---|---|---|
| `none`（默认） | 全部接口开放 | 本地开发/演示 |
| `token` | 静态 `API_BEARER_TOKEN` Bearer（兼容旧部署） | 简单服务间调用 |
| `jwt` | 用户体系 + 角色 + 签名图片 URL（**生产推荐**） | 正式部署 |

jwt 模式使用：

```powershell
# 创建管理员（密码交互输入，至少 8 位）
.ackend\.venv\Scripts\python.exe scripts\create_user.py --username admin --role admin
# 角色可选 admin / reviewer / inspector
```

- 登录：`POST /api/v1/auth/token`（OAuth2 密码流）换取 JWT，前端已内置登录页、路由守卫与 401 自动跳转；
- 角色权限：inspector 提交研判/整改照片，reviewer 确认复核与整改关闭，admin 管理知识库与用户（`GET/POST /api/v1/admin/users`）；
- 审计可信：复核人/整改操作人一律取认证身份，客户端传入的 `reviewer`/`by` 字段在 jwt 模式下不生效；
- 图片保护：`/uploads` 改为短期 HMAC 签名 URL（`UPLOAD_URL_TTL_MINUTES`），浏览器 `<img>` 无需携带凭证，过期/篡改即拒绝；
- 限流（`RATE_LIMIT_ENABLED=true` 开启）：登录 10 次/分/IP（防爆破），研判提交 5 次/分/用户；
- `/health` 与 `/metrics` 保持开放（探活与内网监控）。

## LLM 成本台账与工程化（B5）

- **调用台账**：每次真实模型调用（含失败）逐条落 `llm_calls` 表——provider、模型、用途（analyze/refine/compare/embed）、prompt 版本、tokens 进出、延迟、重试次数、解析失败标记，并携带 request_id 与研判 ID 关联日志；`GET /api/v1/admin/llm-usage`（admin）按天×模型×用途聚合查看；
- **预算熔断**：`DAILY_TOKEN_BUDGET`（默认 0 不限），当日 tokens 超限后新研判返回 429，进行中任务不受影响；
- **并发治理**：跨请求共享模型线程池（`MAX_CONCURRENT_LLM_CALLS`），provider 持久连接池复用（不再每次调用重建 TCP/TLS），重试指数退避 + 抖动并遵循 Retry-After；
- **输出可信**：模型输出 JSON 解析失败不再静默——结果带 `parse_failed` 标记、台账记 `parse_failed` 状态、model_guard 强制人工复核（与"未检出隐患"可区分）；
- **Prompt 版本化**：prompt 集中在 `backend/app/prompts/`（当前 `vision-v2`），改动必须递增版本号，评测与台账据此归因；
- **RAG 修复**：分块按「第X条」边界（多条文法规溯源不再张冠李戴）、语料原子写、重建/查询读写锁、向量 L2 归一化（分数恢复 cosine 语义）、embedding 降级留日志且重建时自动重试真实 API；
- **评测诚实化**：生产置信度公式中的 mock 特判已移除（`MOCK_DEMO_BOOST` 默认关，仅演示场景显式开启），评测数字不再被演示加成污染。

## 异步研判模式（B3，可选）

默认 `WORKFLOW_MODE=sync`：提交后同步等待结果（与历史行为一致）。

设为 `async` 后：

- `POST /assessments` 与 followup 立即返回 `202 + 任务状态`，前端轮询 `GET /api/v1/assessments/{id}/job` 直到 `succeeded`；
- 进程内 worker 串行消费任务，`progress_step` 逐步推进（分析→检索→研判→证据校验→生成），前端已内置轮询与进度提示；
- 追问走 LangGraph checkpointer 断点恢复（`interrupt`/`Command(resume)`），**不再重新调用视觉模型**；进程重启后可从 checkpoint 恢复线程；
- 人工复核结论会回写图线程状态；
- 启动时自动清扫超时僵尸任务（`JOB_STALE_MINUTES`）。

### 幂等与去重

- `POST /assessments` 支持 `Idempotency-Key` 请求头（8-128 位字母数字或 `-_`）：同 key 24 小时内重复请求返回首次结果（响应头 `Idempotency-Replayed: true`），网络重试不再重复付费；
- `POST /assessments/{id}/rectification/compare` 在同整改状态的 `COMPARE_DEDUP_MINUTES` 窗口内复用上次比对结果，不重复调用模型。

## 已实现能力

- 多图上传 + 文字描述的多模态研判
- Mock 模式全链路演示：解析、检索、分级、成文
- 信息不足时追问，最多可追问 2 轮
- 置信度分级：>=0.8 自动完成，否则转人工复核
- 依据溯源：每条结论展示来源、原文、版本与相关度
- LangGraph 工作流：解析、追问、检索、研判、证据检查、生成六节点编排
- 模型失败回退：真实模型调用异常时自动降级到 Mock 分析并标记
- 整改工单、简报、结论导出
- 知识库管理页：上传文档、内容预览、删除、一键切片重建
- 报告下载：一键导出 Markdown 版整改工单与研判简报
- 整改照片回传：上传整改后照片、前后对比展示、AI 完成度评分、确认整改完成
- 历史记录与详情页
- 管理员上传知识文档接口（文本格式）
- 可选 Reranker：词面重叠 + 条款元数据加权重排，可用 `RERANKER_ENABLED=false` 关闭

## 测试

```bash
cd backend
python -m pytest
```

## 数据库迁移（Alembic）

自 B2 起所有表结构变更走 Alembic，不再手写 ALTER：

```powershell
# 模型改动后生成增量迁移（自动 diff 模型与库结构）
.\backend\.venv\Scripts\python.exe -m alembic revision --autogenerate -m "add jobs table"

# 部署/升级时执行
.\backend\.venv\Scripts\python.exe -m alembic upgrade head
```

- 连接串与应用一致：读取 `backend/.env` 或 `DATABASE_URL` 环境变量，无需在 `alembic.ini` 里单独配置
- 全新空库：`upgrade head` 完整建表（与 `create_all` 产物一致，有测试保障）
- 旧库（`ensure_columns` 时代的结构）：baseline 带存在检查，直接 `upgrade head` 即可无损纳入版本管理，无需手工 stamp
- 应用启动时的 `create_all` 只为开发/测试补齐缺失的表，**不会**修改已有表结构——列级变更必须提交迁移文件


## 知识库与向量重建

法规原文放在 `backend/data/knowledge/source_raw/`，文件顶部使用 YAML 形式的元数据记录来源、版本和标签，模板见 `source_raw/sources.md`。

新增或修改语料后，在项目根目录执行：

```powershell
.\backend\.venv\Scripts\python.exe scripts\ingest_knowledge.py
```

脚本会完成清洗、切片、向量化和检索验证：

- 输入：`backend/data/knowledge/source_raw/*.txt|*.md`
- 输出：`backend/data/knowledge/chunks/real_chunks.jsonl`
- 验证：加载全部知识切片，抽样检索并打印命中来源

重新生成知识库后重启后端即可生效：

```powershell
cd backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8001
```

注意：当前切入的法规节选仅用于开发验证，正式使用前请逐条对照官方原文核对版本。

### 向量缓存与索引持久化

切片向量按「文本内容哈希 + embedding 模型」缓存在 `backend/data/faiss/`：

```
backend/data/faiss/
  embeddings_<provider>_<model>.npz   # 内容哈希 → 向量
  vector_index.faiss                  # FAISS 索引
  vector_index.json                   # 语料签名、维度、切片数
```

行为：

- 语料未变化时，重启直接加载已持久化的索引，**不调用 embedding 接口**。
- 新增文档时，只对新增切片调用 embedding，已有切片走缓存。
- 语料或 embedding 模型变化时，签名不匹配，自动重建。
- 切换 provider / 模型会使用不同的缓存文件，不会串用不同维度的向量。

清除缓存可强制全量重建：

```powershell
Remove-Item -Recurse -Force backend\data\faiss
```

安装 `faiss-cpu` 才会启用索引持久化；未安装时回退到 NumPy 检索，embedding 缓存仍然生效。

## 离线评测

评测案例位于 `backend/data/eval_cases/cases.jsonl`，当前共 30 条，覆盖消防、生产安全、社区、林区四类场景。

运行 Mock 模式评测：

```powershell
.\backend\.venv\Scripts\python.exe scripts\evaluate.py --provider mock
```

运行真实模型评测（会调用 30 次模型接口，按量计费）：

```powershell
.\backend\.venv\Scripts\python.exe scripts\evaluate.py --provider auto
```

单独对比 Reranker 开关（只跑知识库检索，不调用模型）：

```powershell
.\backend\.venv\Scripts\python.exe scripts\evaluate_reranker.py
```

输出 `backend/data/eval/reranker_report.json`。当前 30 条评测中 Reranker 未带来条款命中率的可测量提升，因此保留为可选配置，不默认强制。

## 消融评测

运行 A（Qwen only）→ B（GLM only）→ C（Qwen+GLM）→ D（+Risk Engine）→ E（+Evidence RAG）→ F（完整系统）六组对比：

```powershell
.\backend\.venv\Scripts\python.exe scripts\ablation.py --provider mock
```

真实模型版本（会额外调用模型接口，按量计费）：

```powershell
.\backend\.venv\Scripts\python.exe scripts\ablation.py --provider auto
```

输出：`backend/data/eval/ablation_report.json`、`ablation_report.md`、`ablation_results.jsonl`。Mock 模式下 A/B/C 共用同一个确定性 Mock，模型间差异需 `--provider auto` 验证。

输出文件：

- `backend/data/eval/report.json`：整体指标
- `backend/data/eval/report.md`：可直接查看的人工可读报告（总体指标、场景细分、逐条结果）
- `backend/data/eval/results.jsonl`：逐条命中详情

指标定义：

- 类别准确率：预测隐患类别与标注一致的比例
- 等级准确率：预测等级与标注完全一致的比例
- 等级容差准确率：预测等级与标注相差不超过 1 级的比例
- 条款命中率：预期条款关键词出现在检索证据中的比例
- 幻觉率：检索证据未覆盖预期条款关键词的比例，作为无依据输出的代理指标
- 高风险复核率：地面真值高风险案例中进入人工复核的比例
- 不安全自动通过率（Unsafe Auto-Pass Rate）：地面真值高风险却被系统自动通过的比例，越低越好

当前 Mock 模式 30 条评测（B5 基线，2026-10-24，移除置信度 mock 特判后）：类别准确率 100%，等级容差准确率 100%，高风险复核率 100%，条款命中率 63.3%（B5 条文感知分块 + 向量归一化后由 40% 提升），人工复核率 100%（诚实数字：演示加成已移除，复核阈值不再被隐性抬高）。

### 真实模型评测（B5 基线，2026-10-24 实跑）

单轮 30 条、Qwen-VL + GLM-V 双模型并行（`scripts/evaluate.py --provider auto`）：

| 指标 | 2026-09-10 旧基线 | 2026-10-24 B5 基线 |
| --- | --- | --- |
| 类别准确率 | 0.5333 | 0.4000 |
| 等级准确率 | 0.6667 | 0.6333 |
| 等级容差（±1） | 1.0 | 1.0 |
| 条款命中率 | 0.6667 | **0.8000** |
| 高风险复核率 | 1.0 | 1.0 |
| 不安全自动通过率 | 0.0 | 0.0 |
| 人工复核率 | — | 1.0 |
| 平均耗时（秒/案例） | 18.2 | 17.2 |

变化说明：条款命中率显著提升来自 B5 的条文感知分块与向量 L2 归一化；类别准确率下降是模型行为漂移（在线模型版本变化）与检索结果变化的综合结果，属诚实基线——此后指标变化均可归因到具体批次（评测门禁见计划书 B6）。结果落在 `backend/data/eval/report.json`，正式基线同步至 `docs/evaluation/`。

## 下一步

- 扩充法规条款覆盖灭火器、井盖、电气等场景，提升条款命中率
- 增加知识库审核发布流程、法规版本自动监测
- 开展试点试用并持续维护评测集

## 浏览器 E2E

以 Mock 模式启动后端（8001）与前端（5173）后运行：

```powershell
node scripts\verify_e2e.mjs
```

脚本使用 Playwright + Edge 无头浏览器创建一条研判，并断言 P1 的 8 个前端面板（模型 A/B 对比、分歧可视化、风险引擎解释、法规证据、证据链、隐患定位、人工复核、整改回传）均已渲染。
