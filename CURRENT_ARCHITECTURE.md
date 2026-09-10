# CURRENT_ARCHITECTURE（V2 P0 快照）

> 本文档是 V2 改造任务书 Phase 0 要求交付的架构说明，随 P0 边界规则完善后更新。
> 更新日期：2026-09-10

## 项目定位

面向基层安全巡查的多模态安全隐患智能研判与人机协同闭环系统：

```text
多模态感知
    ↓
Qwen-VL + GLM-V 双模型交叉验证
    ↓
Disagreement / 一致性分析
    ↓
Risk Engine 风险规则计算
    ↓
RAG 法规证据检索
    ↓
Evidence Judge 证据校验
    ↓
自动完成 / 人工复核
    ↓
整改工单、整改照片复查、人工确认
```

核心原则：模型负责看，规则负责算，知识库负责证，人负责最终把关。

## 总体架构

```text
Vue 3 前端
    ↓ /api/v1
FastAPI
    ↓
LangGraph StateGraph（有 LangGraph 时）
    ↓
Input Guard → MultiModel Analysis → Risk Engine → RAG → Evidence Judge → Human Review
```

未安装 LangGraph 时，`services/workflow.py` 自动退回同构的函数式流程，两者共享节点实现。

## LangGraph 节点

图文件：`backend/app/services/langgraph_flow.py`

| 节点 | 职责 |
| ---- | ---- |
| analyze | 并行调用全部真实 Provider，标记 full/partial/fallback，标准化并做分歧初检 |
| info | 低置信且可追问时输出追问问题 |
| retrieve | 按场景标签与语义检索知识库 |
| refine | 真实模型模式下用最终证据二次研判 |
| judge | Ensemble Judge + Risk Engine + 结构化最终结论 |
| evidence | Evidence Judge 与证据链回写 |
| generate / human_review | 按复核条件路由到完成或人工复核 |

条件边：

- `info → finish/retrieve`
- `evidence → generate/human_review`

## Provider 抽象与真实双模型

目录：`backend/app/services/providers/`

- `base.py`：统一 `analyze/complete/embed/compare` 接口与超时/不可用异常
- `http.py`：OpenAI 兼容 HTTP 实现，接入重试、指数退避、JSON 解析、外部文本数据标签
- `qwen.py` / `zhipu.py`：DashScope 与智谱 BigModel 两套配置
- `factory.py`：按 `.env` 同时构建 Qwen 与 GLM，缺 Key 时自动 Mock
- `mock.py`：确定性 Mock，`hash_embed` 作为嵌入兜底

并行入口：`ensemble/analyzer.py:run_parallel_analysis`

```text
同一图片 + 文字 + OCR + RAG 证据
    ↓ 线程池
Qwen-VL             GLM-V
    ↓                   ↓
latency/status/error_type/retry_count 独立记录
    ↓
full / partial / fallback 明确标记
```

两个模型全部失败时进入 `mock_fallback`，任何 Mock 都由下游强制人工复核。

## 统一结构化 Schema

- `providers/schemas.py`：`ModelAnalysis` / `HazardFinding` / `HazardLocation`
- Mock 与真实输出统一经过 `normalize_analysis` 校验、夹紧、补默认值
- 真实 Provider 的 `rule` / `rule_score` 不再进入工作流，防止模型直接控制风险规则

## 结果标准化、分歧与 Ensemble Judge

- `ensemble/standardize.py`：类别规范化、字段收敛、按“类别+位置+事实”保留不同隐患
- `ensemble/disagreement.py`：类别一致性、严重度差、关键事实冲突、agreement_score
- `ensemble/judge.py`：聚合双模型结果，`FinalFinding` 保留每个模型的 finding 追踪

## Risk Engine

目录：`backend/app/services/risk_engine/`

- 规则版本：`RISK_RULE_VERSION=risk-engine-v1`
- 按类别基础分 + 人员暴露关键词 + 立即危险关键词 + 严重度提示计算 0-100
- 未知类别/缺失严重度强制建议复核
- 没有任何隐患输出时默认 `20/low + review_suggestion=True`，不会自动通过

## 三层 Guardrail

目录：`backend/app/services/guardrail/`

- Input Guard：文本长度、注入正则、图片魔数/大小、OCR 文本逐条检测
- Model Guard：字段校验 + 绝对化“安全”结论识别（`unsolicited_safety_verdict`）
- Evidence Guard：复用 Evidence Judge 判断证据是否支持结论

外部内容一律作为数据标签传入：

```text
<USER_DESCRIPTION> ... </USER_DESCRIPTION>
<OCR_CONTENT> ... </OCR_CONTENT>
<RAG_EVIDENCE> ... </RAG_EVIDENCE>
```

API 已支持可选表单字段 `ocr_texts`（JSON 字符串数组），注入内容直接 400 拒绝。

## RAG 与知识库

- `services/rag.py`：FAISS 可选，NumPy fallback
- `services/knowledge.py`：章节/条款感知分块，保存 `document/article/source/version/effective_date/tags`
- 演示数据（`is_demo` / demo 版本）不作为法规证据
- 管理员上传文档自动重建索引，知识库正文注入检测失败时拒绝入库

## Evidence Judge 与证据链

- 视觉事实与法规证据分开计算
- 输出 `supported / support_score / evidence_ids / unsupported_claims`
- “没有查到法规”不等于“没有安全隐患”，不足时 `needs_human_review=True`

## Human-in-the-loop

`services/human_review.py` 聚合以下触发：

```text
disagreement / ensemble_judge / risk_engine / risk_model_conflict
image_quality / negated_claim / evidence_judge / model_guard
model_safety_verdict / low_confidence / fallback
```

其中 `negated_claim` 是新增规则：模型无 finding 且输入/OCR 宣称“安全、无隐患”时，禁止自动通过。

## 数据库与 API

- SQLite + SQLAlchemy：`Assessment / AssessmentImage / KnowledgeDocument`
- 状态：`pending / needs_more_info / awaiting_human_review / completed / needs_review / confirmed / failed`
- `backend/app/api/routes.py` 保留 `/assessments` 系列接口
- `/system/provider` 暴露 Provider 元数据，不暴露 Key
- 可选 `API_BEARER_TOKEN` 中间件

## 测试

运行：

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=.pytest-tmp
```

覆盖：Provider 抽象、并行调用、OCR 透传、Schema、标准化、分歧、Ensemble Judge、Risk Engine、Guardrail、Evidence RAG/Judge、Human Review、LangGraph 条件路由、API。

## 已知缺口（P1/P2 或安全残余风险）

- Prompt Injection 无法声称“彻底解决”，当前依靠数据标签 + 注入检测 + 强制人工复核兜底
- Reranker、消融实验、Unsafe Auto-Pass Rate、真实评测集放大未做
- 前端暂无独立 Model Comparison / AI Trace 视图
- 整改闭环只有 `under_review / resolved`，未展开完整状态机
- Docker、正式 trace 接口、README 与真实评测结果同步未完成
