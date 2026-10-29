# 当前架构（M3 增量改造）

更新：2026-10-29。当前范围和下一阶段见 [最终改造计划](docs/最终改造计划.md)；R0–R8 原能力见 [R8 验收记录](docs/baselines/r8-2026-10-29.md)，部署、备份和回退见 [部署说明](docs/DEPLOYMENT.md)。

## 边界与数据流

M1 主流程是分类与人工录入：原上传/任务设施 → 主 Provider 专用分类请求 → RAG 参考条款 → 人工类别/标签和可选等级 → 原角色审核/审计 → 历史与导出。仅人工录入跳过模型及检索；分类请求不进入风险引擎、融合判级或报告工单生成。分类建议、最终值和体系版本共同保存于原 Assessment，不另建业务记录系统。

M2 在同一知识库上增加版本与发布：知识文档按系列和版本独立保存（来源、版本、适用范围、行业目录、内容 SHA256、审核状态），管理员发布后才进入检索；分类引用的条款以证据快照保存版本、正文和指纹，新版本发布只把旧版本标记为已替代，不改写其内容与历史引用。

M3 在原 Assessment 上增加可选的位置与来源：手填地址、区划、设施、场景、经纬度与坐标系、坐标来源、数据来源（现场上报/公开案例/模拟数据）和事件时间。位置可整体缺失，精度按坐标/地址/区划/未提供推导；事件时间以 UTC 保存，与录入时间分开。管理员可按 JSON 批量导入带稳定外部编号的记录，按（数据来源，外部编号）去重并返回批次与逐行失败清单；导入记录不进入 AI 研判，也不视为人工确认。

以下 LangGraph 数据流保留给历史研判接口及记录。Mock、合成图片和开发法规节选验证工程链路；真实识图、误报控制和法规适用性尚未验收。

```text
Vue 3 / Pinia / 页面任务会话
                ↓ /api/v1（nginx 或 Vite 代理）
FastAPI：认证、角色、输入校验、幂等、审计、有效结论
                ↓
同步执行 / 数据库任务队列 + 单进程 worker
                ↓
LangGraph：analyze → info → retrieve → refine → judge → evidence
                        ↘追问暂停                    ↘ generate / human_review
                ↓
SQLAlchemy：SQLite 或 PostgreSQL
本地文件：上传 / 知识及向量缓存 / SQLite checkpoint
                ↓
人工复核 → 整改照片与 AI 比对 → 人工验证 → 关闭 → 导出
```

只支持一个后端实例、一个 Uvicorn worker。PG 替换业务数据库，不替换本地 checkpoint、文件和索引，不能据此部署多 worker。缺少 LangGraph 时存在共享节点的函数式降级流程；断点恢复依赖 LangGraph/checkpointer。

## 模型、规则与防护

- `services/providers/` 统一 classify/analyze/complete/embed/compare 接口，接入 Qwen、GLM 的兼容 HTTP。分类只调用当前主 Provider，使用禁用判级的专用 Prompt；真实图片字节由原 image_url 传输。分类调用/解析失败不回退为成功建议；auto 无 Key 时仍是明确标识的 Mock。
- 双模型并行分析记录独立状态、延迟和错误，明确 full/partial/fallback。全部失败的 Mock 兜底、解析失败等异常触发人工复核。
- HTTP 入口统一申请单进程并发名额，覆盖分析、refine、compare、embedding 和重试；退避及解析不占名额，排队超时不发送请求。
- 标准化、事实/位置去重、分歧分析和 Ensemble Judge 先于风险及证据判定。稳定、不透明的 finding_id 区分同类不同位置隐患。
- Risk Engine 使用 risk-engine-v1；模型不能指定规则得分。空 finding、未知类别或证据不足不能单凭高置信度自动通过。
- 文本/OCR/知识作为外部数据处理，实施长度、注入、图片格式和大小检查，并校验结构化输出及证据。这不构成消除 Prompt Injection 的保证。
- 真实调用落 llm_calls 台账，关联 request/assessment、用途、Prompt、tokens、重试和错误。日预算是入口软阈值，没有并发预算预留或分布式账本。

## 知识与逐项证据

`services/knowledge.py` 按章节/条款切片，保留来源、条款、版本、生效时间和标签。演示语料不作为正式证据。镜像将 `resources/knowledge_seed/` 作为只读种子，只在空知识目录离线初始化，已有数据不被镜像替换。

`services/knowledge_versions.py` 管理文档系列与版本：上传须标注行业目录、版本标识、来源和适用范围，未审核版本可删除但已发布/被引用/有后续版本的不能删除。发布需管理员明确确认来源核对，校验 HTTP(S) 来源、非占位版本、适用范围和内容指纹；同系列发布在单一事务内完成，旧有效版本转为已替代并保留审核历史。检索前重新核对数据库中的审核状态、内容指纹和条款原文，索引中的陈旧或伪造条目不会成为证据；检索引擎先按审核状态过滤再取 Top-K，避免未审核切片挤占结果。

`services/rag.py` 支持 FAISS/NumPy。真实 embedding 和 hash 兜底使用隔离空间，语料与查询同步切换；真实缓存保留，恢复探测有冷却时间。结果标记 embedding_space/embedding_fallback，hash 相似度不代表真实语义质量。索引格式不兼容时从缓存重建，知识重建/查询受锁保护。

每项 finding 独立保留事实、位置、模型引用、法规证据和支持状态。未查到法规不会抹掉视觉隐患；不支持或不足的结论进入复核。旧 finding_id 重复、映射不明确时只读提示核查，不批量重写历史报告。Reranker 是可选词面/元数据重排，尚无新数据上的效果提升结论。

## 状态、人工结论与整改

研判状态包括 pending、needs_more_info、awaiting_human_review、completed、needs_review、confirmed、failed；任务状态与整改状态独立。

- 只有 needs_more_info 可追问，活动任务、已完成或定稿记录拒绝覆盖。
- 分类记录允许 inspector/reviewer/admin 保存类别、标签、可空等级及现场备注，以 revision/条件更新拒绝陈旧覆盖；reviewer/admin 只能在人工录入后批准，也可带意见拒绝。前端有未保存修改时禁用审核。历史研判仍可由 reviewer/admin 修订类别、1–3 整数等级和结论。JWT 操作人取认证身份。
- human_review 保存首次复核前 AI 快照及追加历史，相同审批可幂等重放。详情、工单、导出读取同一有效结果，不冒充重新计算 AI 风险因子。
- 整改状态为 open / assigned / rectifying / pending_verification / verified / closed，允许受控退回/重开。照片成对比对和 rectification-assessment-v1 完成度仅辅助判断，必须人工 verified 才能 closed。
- inspector 可提交研判及整改照片；复核和整改状态流转由 reviewer/admin 执行；知识及用户管理需要 admin。none/token 无个人角色身份保证，前端标识兼容模式。

## 异步、幂等与页面恢复

sync 保留同步响应；async 在研判和任务同事务落库后返回 202，由单进程 worker 串行消费。

- 条件 UPDATE 原子认领任务，worker_id、attempt_token、lease_expires_at 隔离执行代次。运行时心跳、监测及进程锁处理失联，旧执行迟到不能回写新代次。
- 追问在接受时预留次数及 followup_token，失败/恢复按代次释放。checkpoint 恢复已暂停线程，通常不重跑原视觉分析。
- Idempotency-Key 绑定初始录入模式、文字/OCR/图片指纹；相同内容复用原记录/任务，不同内容或模式 409。GET /assessment-submissions/{key} 只查询；无指纹旧映射可查，但拒绝不明确的 POST 重放。
- 前端 sessionStorage 只保留恢复元信息，响应丢失后先查原 key，刷新不自动重传照片或重新调用模型。
- useAssessmentSession 按页面和记录持有任务、定时器和 AbortController。刷新、历史入口、路由换 id 查询记录与最新任务；离开停止本地轮询。两分钟是本地等待窗口，继续查询不重建任务，终态停止轮询。

## 持久化、认证与运行

模型包括 Assessment、AssessmentImage、AssessmentJob、IdempotencyKey、KnowledgeDocument、User、LLMCall。Alembic head 为 `d5e2f7a91c04`；M1 只给原 Assessment 增加 record_mode/classification_json，M2 给知识文档增加系列/版本/行业/适用范围/审核状态/内容指纹，M3 给 Assessment 增加位置/来源/事件时间列及（data_source, source_ref）唯一索引，旧知识记录保持未审核、旧记录位置字段为空，旧人工结果和审计不重算。启动接管未版本化库并增量升级；任何迁移失败拒绝启动。

R3/R4 新增任务 worker/代次/租约、追问预留 token、幂等初始指纹列，允许历史值为 null。人工历史和 AI 快照使用既有 JSON 字段，没有迁移重写存量人工结论。

认证支持 none、静态 token、JWT。token 缺凭证，JWT 使用默认/占位/过短密钥时拒绝启动。图片 URL 签名与凭证/密钥关联；nginx 代理 `/api` 和 `/uploads`。管理员通过容器内 `python -m app.cli.create_user` 初始化。

| 入口 | 含义 |
|---|---|
| /api/v1/live | 进程存活 |
| /api/v1/health | Provider/auth 元信息，不能代替就绪 |
| /api/v1/ready | DB、迁移 head、非演示知识/持久切片、索引、可写目录、适用异步 worker；异常 503 |
| /metrics | Prometheus 指标，按部署网络策略限制可见范围 |
| /api/v1/admin/llm-usage | 管理员调用台账汇总 |
| /api/v1/evaluation/reports | 评测归档，不代表单条研判完整分布式 Trace |

## 评测与验收

- 当前工程集：test/evaluation/cases.jsonl，r6-synthetic-v1、schema 2.0，12 案例引用 10 张合成 PNG，8 隐患/4 负例，独立人工标签为 0。
- 历史源码文本集 60 条，无图片/明确负例/独立证据标签；旧归档有 30 条批次。各批次样本数不能互相替代。
- FP/FN、拒判、流程拦截分开统计；证据自评和独立标签正确率分开，缺标签为 N/A。当前聚合为案例存在性和主类别，尚非逐项定位成绩。
- 报告保留数据/配置/Prompt/规则/模型/源码摘要，不同口径禁止比较；缺指标或分母使门禁失败。Mock 门禁只比较 R6 工程基线。
- 新增测试统一在 test/；新旧后端分进程隔离，离线单测禁止真实 HTTP。本轮 SQLite/PG、容器、浏览器实测数及产物摘要见 R8 验收记录。

## 尚未支持或验收

真实现场图片质量、独立法规正确率、真实模型多批次稳定性和成本；自动地理编码、地图展示与管理统计；组织级数据隔离；多副本/多 worker；分布式预算；法规自动更新审核；完整分布式 Trace；真实移动设备触摸验收。前端主 JS 仍有 >500 kB 构建警告，优化需另设可测目标。外部条件见 [真实验收清单](test/evaluation/real-acceptance-status.json)。
