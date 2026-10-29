# 多模态基层安全隐患智能研判与处置辅助系统

面向社区网格员、厂区安全员、林区巡查员，在原 Vue/FastAPI 项目上改造的分类与知识助手。M1 首页提供“照片/描述 → 类别与标签建议 → 参考条款 → 人工录入 → 角色审核”，风险等级由人工选填；也可仅人工录入。原 R0–R8 研判及整改记录继续可读。无 API Key 时为明确标识的 Mock 演示，真实现场识别与法规质量仍待验收。

后续统一按[最终改造计划 v2.0](docs/最终改造计划.md)在本项目上增量实施，整合“知识库与分类助手＋行业数据分析”：分类与人工录入 → 多行业知识版本 → 位置/来源与导入 → 管理统计及同类整改对标 → 更新/趋势提醒 → 部署验证。M0–M6 已完成工程验收；真实质量、业务收益和生产部署另行独立验收，当前交接与备份入口见 [HANDOVER.md](HANDOVER.md)。**打开后怎么用、功能在哪里、哪些可以精简，见[项目使用说明与功能地图](docs/项目使用与功能地图.md)。**

按[《项目完善执行计划书（2026-10-28）》](docs/项目完善执行计划书-2026-10-28.md)完成 R0–R8 工程工作。最终结果、遗留条件和证据见 [R8 验收记录](docs/baselines/r8-2026-10-29.md)，另有[当前架构](CURRENT_ARCHITECTURE.md)、[部署与回退](docs/DEPLOYMENT.md)、[评测索引](docs/evaluation/README.md)。新增或修改的测试统一放在根目录 `test/`；各阶段原始基线保留于 `docs/baselines/`。

## 技术栈

- 后端：Python 3.11+、FastAPI、SQLAlchemy、SQLite / PostgreSQL
- 工作流：分类模式复用主 Provider、RAG 与现有任务队列，失败明确展示并允许人工录入；历史研判保留 LangGraph 条件流程及带标识的 Mock 降级
- 模型：Qwen / GLM（模型名可配置，OpenAI 兼容 API），Mock 模式无需 Key
- 检索：FAISS 或 NumPy 兜底向量检索，可选规则重排 Reranker（`RERANKER_ENABLED`，执行 Vector Top-K → 重排 → Top-N）
- 地图：Leaflet + OpenStreetMap 底图（无需 Key；底图需联网，点位与列表不依赖底图）
- 前端：Vue 3、TypeScript、Vite、Element Plus、Pinia

## 目录结构

```text
backend/
  app/api/        FastAPI 路由
  app/core/       配置与数据库
  app/models/     SQLAlchemy 模型
  app/schemas/    Pydantic 输入输出
  app/services/   providers、rag、workflow、report
  data/knowledge/ 本地知识及开发法规节选
  resources/knowledge_seed/ 镜像只读开发种子
  migrations/     Alembic 增量迁移
  tests/          历史 pytest 测试（保留）
frontend/
  src/views/      页面
  src/components/ 研判结果组件
  src/stores/     Pinia 状态
test/             新增测试、合成评测数据、隔离 E2E
docs/baselines/   各阶段实际验收记录
```

## 快速启动

### 后端

需要 Python 3.11+、uv，以及 Node >=22.13 / pnpm 11.21.0。以下为 Windows PowerShell，从仓库根目录开始：

```powershell
Set-Location backend
Copy-Item .env.example .env
uv sync --frozen --extra dev --extra faiss --extra pg
$env:PROVIDER_MODE = 'mock'
$env:AUTH_MODE = 'none'
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8001
```

注意使用 `backend\.venv`，根目录旧虚拟环境已在瘦身时移除。

不安装 FAISS 时，省略 `--extra faiss`，使用 NumPy 检索。仅演示不开发时可省略 `--extra dev`。不要覆盖已有 `.env`；已有环境先核对配置。

接口文档：`http://localhost:8001/docs`

### 前端

另开终端，从仓库根目录执行：

```powershell
Set-Location frontend
pnpm install --frozen-lockfile
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

## 部署（Docker 与 PostgreSQL）

完整认证配置、升级备份和回退步骤见[部署说明](docs/DEPLOYMENT.md)。下面是本机 Mock 演示，两种数据库任选其一，不在同一项目名下混用数据卷：

```powershell
# 默认 SQLite 单节点；绑定本机，前端 http://localhost:8080
$env:PROVIDER_MODE = 'mock'
$env:AUTH_MODE = 'none'
$env:BACKEND_BIND_HOST = '127.0.0.1'
$env:FRONTEND_BIND_HOST = '127.0.0.1'
docker compose -p safety-demo up -d --build --wait --wait-timeout 180

# PostgreSQL 变体（仍限定单实例、单 worker）
docker compose -p safety-pg -f docker-compose.pg.yml up -d --build --wait --wait-timeout 180
```

- 后端 lifespan 自动初始化并升级 Alembic 版本（旧库自动纳入版本管理），迁移错误拒绝启动；
- 默认使用 Mock。新空卷从镜像只读种子离线初始化知识，已有卷不被新版种子覆盖；内置法规节选只供开发验证，正式使用前须人工复核版本与适用性。
- `DATABASE_URL` 切 `postgresql+psycopg://...` 即用 PG（安装 `.[pg]` extra），CI 有 PG 全量测试矩阵；
- 当前仅支持一个后端实例、一个 Uvicorn worker（`--workers 1`）。任务认领已原子化，但本地 SQLite checkpoint、上传目录和检索索引尚不支持多副本；PG 不改变这一限制。异步 worker 启动时通过 checkpoint 旁的 OS 锁拒绝重复启动；部署时保持同一数据目录，禁止通过分离 checkpoint 路径绕开此限制。
- `/api/v1/live` 检查基础存活，`/api/v1/health` 保留元信息；部署应检查 `/api/v1/ready`（数据库、迁移版本、知识/索引、持久存储和 worker），未就绪返回 503。两套 Compose 已使用此健康依赖。

## 质量保障（R6：版本化评测回归门禁）

`scripts/check_eval_baseline.py` 在隔离路径运行 12 条合成图片工程边界案例，与
`docs/evaluation/r6-v2/` 的 schema 2 基线比较。缺失指标、无有效分母，或数据、配置、
模型模式、Prompt/规则版本不一致时明确失败；关键指标劣化 >2pp、出现危险自动通过或执行失败也失败。
高风险复核率使用真值等级 1 隐患为分母。CI 运行 Mock 与假 Provider，不请求真实付费服务。

```powershell
.\backend\.venv\Scripts\python.exe scripts\check_eval_baseline.py
```

## 认证与权限（B4）

`AUTH_MODE` 三档：

| 模式 | 行为 | 适用 |
|---|---|---|
| `none`（默认） | 全部接口开放 | 本地开发/演示 |
| `token` | 静态 `API_BEARER_TOKEN`，无用户与角色体系，前端提供凭证验证入口 | 服务间兼容模式 |
| `jwt` | 用户体系 + 角色 + 签名图片 URL（**生产推荐**） | 正式部署 |

jwt 模式使用：

启用前设置独立随机 `AUTH_JWT_SECRET`（至少 32 字节）。默认开发密钥、文档旧占位值、过短 JWT 密钥，以及 token 模式缺失静态凭证均会拒绝启动。密钥须稳定保存；更换后原 JWT 和图片签名失效。

```powershell
# 创建管理员（密码交互输入，至少 8 位）
.\backend\.venv\Scripts\python.exe scripts\create_user.py --username admin --role admin
# 角色可选 admin / reviewer / inspector
```

- `/health` 明确返回 `auth_mode`；JWT 使用账号密码登录，静态模式验证 `/auth/check`，none 显示无需登录说明。读取认证配置失败时不会默认为开放模式。
- 登录：仅 JWT 提供 `POST /api/v1/auth/token`（OAuth2 密码流）；token/none 返回明确说明。前端仅按 JWT 会话处理 401，静态凭证 401 不自动删除凭证或循环跳转；候选凭证验证通过才替换保存值。
- 角色权限：inspector 提交记录、补全人工分类/标签及整改照片，reviewer/admin 审核分类及原研判，admin 管理知识库与用户（`GET/POST /api/v1/admin/users`）；
- 审计可信：复核人/整改操作人一律取认证身份，客户端传入的 `reviewer`/`by` 字段在 jwt 模式下不生效；
- 复核保护：仅 `needs_more_info` 可追问，活动任务或已定稿记录不能被追问覆盖；复核只接受允许的终态，相同决定可幂等重放；
- 人工修订：拒绝必须填写意见。分类记录先保存人工类别/标签及可选等级，审核不能直接批准尚未录入的 AI 建议；历史研判仍支持 edits 修订类别、1–3 等级和结论。两者共用追加审计及 AI 快照；详情、历史与导出读取相同有效值；
- 图片保护：`/uploads` 改为短期 HMAC 签名 URL（`UPLOAD_URL_TTL_MINUTES`），浏览器 `<img>` 无需携带凭证，过期/篡改即拒绝；
- 限流（`RATE_LIMIT_ENABLED=true` 开启）：登录 10 次/分/IP（防爆破），研判提交 5 次/分/用户；
- `/health` 与 `/metrics` 保持开放（探活与内网监控）。

容器内创建管理员无需先 HTTP 登录：`docker compose exec backend python -m app.cli.create_user --username admin --role admin`。自动化可使用 `--password-stdin`，避免把密码放入命令行参数。

## LLM 成本台账与工程化（B5）

- **调用台账**：每次真实模型调用（含失败）逐条落 `llm_calls` 表——provider、模型、用途（classification/analyze/refine/compare/embed）、prompt 版本、tokens 进出、延迟、重试次数、解析失败标记，并携带 request_id 与研判 ID 关联日志；`GET /api/v1/admin/llm-usage`（admin）按天×模型×用途聚合查看；
- **预算熔断**：`DAILY_TOKEN_BUDGET`（默认 0 不限），当日 tokens 超限后新研判返回 429，进行中任务不受影响；
- **并发治理**：`MAX_CONCURRENT_LLM_CALLS`（默认 4）统一限制单进程内所有 Provider 的 analyze/refine/compare/embed 实际 HTTP 并发。`LLM_QUEUE_TIMEOUT_SECONDS`（默认 60 秒）限制等待名额的时间，排队超时不发送 HTTP、不在 Provider 内重试；每次 HTTP 重试重新申请名额，退避、解析和台账写入不占名额。双模型线程池仅调度任务。此限制不提供分布式限流或严格日预算预留；
- **输出可信**：模型输出 JSON 解析失败不再静默——结果带 `parse_failed` 标记、台账记 `parse_failed` 状态、model_guard 强制人工复核（与"未检出隐患"可区分）；
- **Prompt 版本化**：prompt 集中在 `backend/app/prompts/`，历史研判保留 `vision-v2`，新增分类使用 `classification-m1-v1`；每类提示词独立递增，成功/失败调用均记录实际版本，不混用历史评测基线；
- **RAG 修复**：分块按「第X条」边界（多条文法规溯源不再张冠李戴）、语料原子写、重建/查询读写锁、向量 L2 归一化（分数恢复 cosine 语义）、embedding 降级留日志且重建时自动重试真实 API；
- **评测诚实化**：生产置信度公式中的 mock 特判已移除（`MOCK_DEMO_BOOST` 默认关，仅演示场景显式开启），评测数字不再被演示加成污染。

## 异步研判模式（B3，可选）

默认 `WORKFLOW_MODE=sync`：提交后同步等待结果（与历史行为一致）。

设为 `async` 后：

- `POST /assessments` 与 followup 立即返回 `202 + 任务状态`，前端轮询 `GET /api/v1/assessments/{id}/job` 直到 `succeeded`；
- 进程内 worker 串行消费任务，`progress_step` 逐步推进（分析→检索→研判→证据校验→生成），前端已内置轮询与进度提示；
- 追问走 LangGraph checkpointer 断点恢复（`interrupt`/`Command(resume)`），**不再重新调用视觉模型**；进程重启后可从 checkpoint 恢复线程；
- 人工复核结论会回写图线程状态；
- 启动及运行时检查执行代次与租约；心跳续租、条件认领和迟到回写保护防止旧执行覆盖新任务。`JOB_STALE_MINUTES` 只承担兼容旧任务的清扫阈值。

### 幂等与去重

- `POST /assessments` 支持 `Idempotency-Key`（8-128 位字母数字或 `-_`）：同 key 在重放窗口内校验初始描述、补充回答、OCR 和图片指纹；内容不同返回 409，内容相同复用原研判/初始任务。默认窗口 24 小时，pending/failed 不会因过期自动重跑；已完成终态过期后直接 POST 可新建，调用方应为新提交生成新 key。
- `GET /assessment-submissions/{key}` 只读查询原提交，无模型调用、不删除过期映射；原 create job 排队/执行中为 202，其他情况为 Assessment 200，始终提供 Assessment-Id / Location。旧 key 无指纹时 POST 明确冲突，仍可 GET 恢复。
- 前端每次新建生成独立 key；结果不确定时先查询，明确未找到才按内存中的原内容和原 key 重发。页面提供查询、原内容重试及记录入口；sessionStorage 仅保留恢复元数据，刷新后不自动重传照片。同步失败保留原记录，需要再次执行时明确新建研判。
- `POST /assessments/{id}/rectification/compare` 在同整改状态的 `COMPARE_DEDUP_MINUTES` 窗口内复用上次比对结果，不重复调用模型。

## M1 分类录入合同

- `GET /api/v1/classification/taxonomy` 返回 `m1-v1` 的类别和通用标签，前端不另维护一份分类表。
- `POST /api/v1/assessments` 沿用原图片、描述、幂等键与异步响应。表单 `mode=classification` 请求主 Provider 生成建议，`mode=manual` 不调用模型或向量检索；省略 mode 仍为历史研判接口。
- `record_mode=classification` 时，`classification.suggested_category/suggested_tags` 是不可变建议，`hazard_category` 和 `classification.final_tags` 为人工值；`risk_level=null` 表示未分级，不生成 AI 风险分数或整改工单。
- `POST /api/v1/assessments/{id}/classification` 保存 category、tags、可空 risk_level、note、taxonomy_version、revision；陈旧 revision 返回 409。保存不等于审核，定稿仍走原 `/confirm` 权限和审计，定稿后不能覆盖。
- 同一幂等键不能切换录入模式。未知类别、模型失败、检索不足及 Mock 演示均明确展示；参考条款仍须核对来源、版本和适用性。

## M2 知识版本与发布合同

- 知识库按通用/消防/生产/社区/林区目录组织；`GET /api/v1/knowledge/catalog` 返回目录，文档列表与检索均支持 `industry` 过滤。
- `POST /api/v1/knowledge/documents` 上传即创建独立版本（标题、来源、版本标识、适用范围、演示标记、`supersedes_id`）；同系列重复版本由数据库拒绝。上传后为未审核，管理员审核发布后进入检索。
- `POST /api/v1/knowledge/documents/{id}/review` 支持 approve/reject/retire，须携带 `revision`、审核意见；发布还必须明确勾选 `source_checked`。发布时校验可定位 HTTP(S) 来源、非占位版本、适用范围和内容指纹，演示资料拒绝发布；同系列旧有效版本标记为已替代，其正文与指纹不变。
- 检索只返回已审核且指纹、文本与数据库一致的条款；被替代、停用、未审核或伪造索引条目不会成为研判依据。无结果时明示“未找到已审核的有效条款”。
- 分类记录的证据快照保存引用时的 `document_id`、版本、条款文本、适用范围与内容 SHA256；后续发布新版本不覆盖旧引用，详情、历史和 Markdown 导出一致展示。

## M3 位置、来源与导入合同

- `POST /api/v1/assessments` 增加可选表单字段：`address`、`district`、`facility`、`scene`、`latitude`、`longitude`、`coordinate_system`（wgs84/gcj02/bd09）、`data_source`（report/public_case/simulated）、`event_time`。地址可手填，无地图 Key 也能录入；经纬度可整体留空，填写时须成对并提供坐标系。
- `event_time` 以 UTC 保存并返回，与 `created_at` 录入时间分开；前端按本地时区展示。`location_precision` 按坐标/地址/区划/未提供返回，位置缺失时不伪造精度。
- 坐标来源记录为 `manual`（表单）或 `import`（导入）；`data_source` 默认 `report`，历史记录为 `null`，页面显示“未标注”。
- `POST /api/v1/assessments/import`（admin）接受 `{"rows": [...]}`，每行须有 `source_ref`、`description`、`data_source`，可选位置字段。按（`data_source`, `source_ref`）去重；返回 `batch_id`、`imported`、重复行号 `duplicates` 和逐行 `failures`（行号、外部编号、原因）。导入记录的 `record_mode` 与 `status` 均为 `imported`，保留批次号和外部编号，不进入 AI 研判、不视为人工确认。
- 历史页管理员可上传 JSON 文件执行导入并查看失败清单；巡查员/复核员无导入入口。

## M4 管理分析与对标合同

- `GET /api/v1/analytics/options`（reviewer/admin）返回已确认记录中可用的区划、类别、设施和场景。
- `GET /api/v1/analytics/overview` 仅统计 `confirmed=true` 记录，支持 `district`、`category`、`facility`、`scene` 和 `start`/`end`（YYYY-MM）筛选；返回地区/类别分布、风险等级（未分级单列）、补齐零月份的月度趋势、地图点位，以及按来源统计的“收集到的案例数”（导入记录，不并入已确认统计）。
- 时间口径为事件时间，未填写时使用录入时间。地图点位按 WGS84 输出，GCJ-02/BD-09 坐标先转换再展示；无坐标记录仍进入统计和列表。底图使用 OpenStreetMap，需要联网；点位和列表不依赖底图。
- `GET /api/v1/analytics/benchmarks` 按设施和/或场景查询其他地点的已确认整改记录，返回样本量、筛选条件、来源计数、匹配方式和可比性说明，并链接原记录；接口与页面均提示不能据此直接作出处置决定。
- 已确认统计中的模拟数据显式提示；数量展示不代表风险排名。管理分析入口对 reviewer/admin 显示，巡查员直接访问返回 403。
- 统计单位为已确认记录条数；评估记录当前不带行业字段，管理页按区划/类别/设施/场景和月份统计，行业维度仍由知识库目录承载。

## M5 来源提醒与趋势提示合同

- `GET/POST/DELETE /api/v1/knowledge/sources`（admin）登记权威来源（HTTP(S) 链接、行业）；`POST .../{id}/check` 拉取内容并比较 SHA256，首次成功检查建立基线，内容变化保持 `pending` 直到 `POST .../{id}/ack`；不可达或 HTTP 错误记录在 `last_status`/`last_error`。检查不会创建或发布知识文档，新版本仍须走 M2 的上传、审核和发布。
- `GET /api/v1/analytics/trend-alerts`（reviewer/admin）返回规则、回测、资料充分性和提示列表；`POST .../refresh` 评估上一个完整月份并持久化新提示，重复评估不重复创建；`POST .../{id}` 标记 `acknowledged` 或 `false_positive`，保留处理备注、人员和误报记录。
- 规则 `trend-rule-v1`：按类别，前 6 个月月均的 2 倍、当月不少于 5 条、窗口样本不少于 10 条；排除模拟数据，只使用已确认记录。资料不足时返回原因，不生成提示。回测是历史触发回放，不是预测准确率。
- 来源检查与趋势评估由页面手动触发；当前没有后台定时任务、外部通知或自动发布。

## M6 知识包与离线边界合同

- `GET /api/v1/knowledge/pack/export`（admin）只导出每个文档系列最新的已审核版本，包含格式/审核策略、包版本、清单和每篇内容 SHA256；`POST /api/v1/knowledge/pack/import`（admin）先校验数量、清单摘要、逐篇指纹、行业和演示标记，再写入并保留云端审核历史与导入事件；同系列旧有效版本转为已替代，正文不变。导入记录保存包版本、摘要、计数和人员，`GET /api/v1/knowledge/pack/status` 返回最后同步；知识库页显示本地知识包版本和最后同步时间。
- 升级保留旧引用：知识包导入不改写既有研判的证据快照；新版本生效只影响后续检索。
- 离线边界：无外网时本地知识检索、人工录入、历史/详情和已有记录访问可用；底图、权威来源检查和真实模型调用需要网络。Mock 分类仅用于演示，不是离线 AI 能力。
- 本轮以两套隔离应用实例验证云端审核→导出→本地导入、v1→v2 引用保留、篡改包拒绝和断网流程；容器镜像冷启动沿用 R8 部署证据。计时脚本记录查询、录入、Mock 分类与复核（含一次退回和更正），仅作工程基线。

## 历史研判与共用能力（R0–R8）

- 多图上传 + 文字描述的多模态研判
- Mock 模式全链路演示：解析、检索、分级、成文
- 信息不足时追问，最多可追问 2 轮
- 结合置信度、分歧、风险、模型/证据防护决定完成或人工复核；高置信度不能覆盖异常复核条件
- 依据溯源：每条结论展示来源、原文、版本与相关度
- LangGraph 工作流：分析、追问、检索、refine、融合研判、证据、生成/人工复核八节点
- 模型失败回退：真实模型调用异常时自动降级到 Mock 分析并标记
- 整改工单、简报、结论导出
- 知识库管理页：行业目录、文档/条款版本、适用范围、审核发布与索引重建
- 报告下载：一键导出 Markdown 版整改工单与研判简报
- 整改照片回传：上传整改后照片、前后对比展示、AI 完成度评分、确认整改完成
- 历史记录与详情页
- 管理员上传知识文档接口（文本格式）
- 可选 Reranker：词面重叠 + 条款元数据加权重排，可用 `RERANKER_ENABLED=false` 关闭

## 测试

从仓库根目录运行新旧后端测试（分进程隔离）及前端检查：

```powershell
.\backend\.venv\Scripts\python.exe test/run_backend.py --suite all -q
pnpm --dir frontend test
pnpm --dir frontend lint
pnpm --dir frontend type-check
pnpm --dir frontend build
```

聚焦测试、PG 测试参数和可重复基线记录见 [test/README.md](test/README.md)。

## 数据库迁移（Alembic）

自 B2 起所有表结构变更走 Alembic，不再手写 ALTER：

```powershell
# 以下迁移命令在 backend 目录执行
Set-Location backend
# 模型改动后生成增量迁移（自动 diff 模型与库结构）
.\.venv\Scripts\python.exe -m alembic revision --autogenerate -m "describe schema change"

# 部署/升级时执行
.\.venv\Scripts\python.exe -m alembic upgrade head
```

- 连接串与应用一致：读取 `backend/.env` 或 `DATABASE_URL` 环境变量，无需在 `alembic.ini` 里单独配置
- 全新空库：`upgrade head` 完整建表（与 `create_all` 产物一致，有测试保障）
- 旧库（`ensure_columns` 时代的结构）：baseline 带存在检查，直接 `upgrade head` 即可无损纳入版本管理，无需手工 stamp
- 应用启动时的 `create_all` 只为开发/测试补齐缺失的表，**不会**修改已有表结构——列级变更必须提交迁移文件


## 知识库与向量重建

检索发生 embedding 故障时，语料与查询会同时降级至独立 hash 空间，保留真实模型缓存；默认 `EMBEDDING_RECOVERY_SECONDS=60` 控制恢复探测间隔。检索/证据结果携带 `embedding_space` 与 `embedding_fallback`；hash 分数不代表已验证的真实语义质量。索引格式升级会从 embedding 缓存重建旧索引。

融合结果的 `finding_id` 为不透明的稳定标识，不应当作类别名解析。同类不同位置的隐患独立保存证据状态；旧记录标识重复且对应关系不明时，页面只读提示核查，不重写已有报告与复核历史。

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

## 离线与消融评测

历史文本回归集 `backend/data/eval_cases/cases.jsonl` 保留 60 条；R6 新建了 12 条 synthetic 图片边界案例，覆盖四类场景、负例、低质量图、多隐患、图文矛盾和证据不足。来源、授权与标注状态见 [数据说明](test/evaluation/README.md)；真实现场图片和独立人工标签仍待取得。

运行隔离 Mock 评测与六变体消融，每次使用新的输出目录：

```powershell
.\backend\.venv\Scripts\python.exe test/evaluation/run_mock.py --output test/.artifacts/evaluation/my-run
.\backend\.venv\Scripts\python.exe test/evaluation/run_mock.py --output test/.artifacts/evaluation/my-run --ablation
```

[当前报告](docs/evaluation/r6-v2/reports/evaluation_report.md) 使用报告/指标 schema 2.0，记录图片声明/加载/失败、配置摘要、模型标识、Prompt/规则版本、内容摘要与指标分母。检测 FP/FN 不因转人工消失，信息不足与失败单列，证据自评和独立人工正确率分开；缺少标签为 N/A。多隐患清单保留逐项真值，当前汇总指标仍为案例存在性与主类别。

通用脚本 `scripts/evaluate.py` 和 `scripts/ablation.py` 支持 `--cases`、`--dataset-version`、`--output`、`--gate-policy`、`--pricing`。auto 没有可用 Key 时仍是 Mock；真实模型批次需使用已授权且已人工复核的数据，并在执行前登记质量目标和价格。调用次数包括 embedding、追问、refine 与重试，按实际 HTTP 统计，不能用案例数估计费用。缺少用量或价格时费用为 N/A。报告与归档均拒绝覆盖已有结果。

Reranker 历史脚本 `scripts/evaluate_reranker.py` 保留。过去 30 条样本未测得提升的结论仅适用于当时的批次；R6 不据此声称新数据上的检索效果。

### 历史 B5 记录（与 R6 不可直接比较）

以下原始成绩与解释保留用于追溯，不作为 R6 图片识别、来源授权、独立证据或真实场景验收结论。

当前 Mock 模式 30 条评测（B5 基线，2026-10-24，移除置信度 mock 特判后）：类别准确率 100%，等级容差准确率 100%，高风险复核率 100%，条款命中率 63.3%（B5 条文感知分块 + 向量归一化后由 40% 提升），人工复核率 100%（诚实数字：演示加成已移除，复核阈值不再被隐性抬高）。

### 历史 B5 真实模型文本批次（归档自述，非本轮验收）

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

以上为历史记录引用，原报告位于 `backend/data/eval/report.json` 与 `docs/evaluation/`，不是 R8 重跑结果。历史上对条款分块、模型漂移的解释没有构成本轮受控因果实验；不能据此证明当前真实图片质量或与 schema 2 比较提升。

## 下一步

计划内 M0–M6 已完成工程验收，后续只做真实质量、业务收益、生产部署与授权数据的独立验收，不再自动扩展功能。

## 浏览器 E2E

历史面板冒烟需要预先启动后端（8001）和前端（5173），会向该实例写入记录，只能用于专用测试实例：

```powershell
node scripts\verify_e2e.mjs
```

脚本使用 Playwright + Edge 无头浏览器创建一条研判，并断言 P1 的 8 个前端面板（模型 A/B 对比、分歧可视化、风险引擎解释、法规证据、证据链、隐患定位、人工复核、整改回传）均已渲染。

## 人工复核与任务恢复（R7）

复核员和管理员可批准、拒绝或修订类别/等级/结论，拒绝必须填写意见；巡查员只能查看复核信息。已定稿记录展示人工最终结论、原 AI 快照及追加历史，工单和导出使用同一份有效结论。none/token 保持兼容操作并标明未绑定个人身份，不代替 JWT 角色审计。

详情和首页按当前记录恢复最新任务。刷新、从历史进入、换记录后可继续查询；离开页面只停止本地轮询。两分钟本地等待结束不会把服务端任务标为失败，可点击“继续查询”。任务失败时保留记录、原结果和原因，页面不会自动重新付费执行。

浏览器工程回归使用独立 SQLite、仓库开发种子和 Mock，不需要 API Key：

```powershell
node test/e2e/human-review.mjs
node test/e2e/async-resume.mjs
node test/e2e/assessment-lifecycle.mjs
node test/e2e/m6-delivery.mjs
node test/e2e/m6-timing.mjs
```

Windows 使用已安装的 Edge headless；CI 安装 Chromium。默认使用 backend/.venv 的 Python，可用 PYTHON 指向已装依赖的解释器。每轮结果与失败截图位于独立的 test/.artifacts/reports/r7-*/ 目录。测试图片为明确标注的合成几何图，流程通过不代表真实识图或法规质量已经验收。
