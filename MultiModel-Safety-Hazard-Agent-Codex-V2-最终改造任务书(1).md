# MultiModel-Safety-Hazard-Agent V2 最终改造任务书（Codex 执行版）

> **目标：直接把本文件交给 Codex / Coding Agent 执行。**
>
> 仓库：`https://github.com/byless91/MultiModel-Safety-Hazard-Agent`
>
> 本版本是在 V1 改造任务书基础上，融合新的架构、安全、RAG、工程化建议后的**最终版**。
>
> **核心原则：不要推倒重写，不要为了“高级”而堆技术，不要为了 Agent 而 Agent。**
>
> 最终项目应从“多模态安全隐患识别 MVP”升级为：
>
> **可验证、可追溯、有人机协同、支持整改闭环的多模态安全隐患研判 Agent。**

---

# 0. 最终产品定位

项目最终定位：

> **基于 LangGraph 的多模态安全隐患智能研判与人机协同闭环系统**

核心技术链：

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
自动通过 / 人工复核
    ↓
整改建议与整改工单
    ↓
整改后图片 AI 复查
    ↓
人工确认
    ↓
闭环完成
```

项目核心卖点不是“用了多少 Agent”，而是：

1. **Multi-Model**：两个多模态模型真正并行工作，而不是简单二选一。
2. **Cross Validation**：模型之间互相交叉验证，检测分歧。
3. **Risk Engine**：LLM 负责事实提取，规则负责风险计算。
4. **Evidence RAG**：风险结论和法规依据可追溯。
5. **Guardrail**：输入、模型输出、证据三个层面都有安全约束。
6. **Human-in-the-loop**：高风险、冲突、低置信度、证据不足时人工接管。
7. **Closed Loop**：发现 → 研判 → 整改 → 复查 → 关闭。
8. **Evaluation**：用真实模型实验和消融实验证明 MultiModel 的价值。

---

# 1. 给 Codex 的最高优先级执行规则

在开始修改代码之前，**必须先阅读并理解现有仓库**，禁止直接按照本任务书假设文件一定存在。

## 1.1 必须先检查

至少检查：

```text
README.md
backend/
frontend/
docs/
scripts/
tests/（如果存在）
.env / .env.example（如果存在）
pyproject.toml / requirements.txt
docker*（如果存在）
```

重点寻找：

- FastAPI app
- LangGraph StateGraph
- 当前六节点 workflow
- provider/model 调用
- Qwen / GLM 接入
- Mock fallback
- RAG / FAISS / NumPy
- SQLAlchemy / SQLite
- history/detail
- rectification
- evaluation dataset
- frontend 页面
- API schema
- 测试

## 1.2 第一阶段只做审计，不改业务

先输出一份简短的：

```text
CURRENT_ARCHITECTURE.md
```

说明：

- 当前架构
- 当前 LangGraph 节点
- 当前模型调用方式
- 当前 RAG 流程
- 当前数据库结构
- 当前前端页面
- 当前测试
- 当前缺口
- 哪些功能已经存在
- 哪些功能需要修改
- 哪些功能不需要重复实现

然后再开始修改。

---

# 2. 总体架构

最终建议架构：

```text
                        Vue 3
                          │
                          ▼
                    FastAPI API
                          │
                          ▼
                 ┌─────────────────┐
                 │    LangGraph    │
                 └────────┬────────┘
                          │
                    Input Guard
                          │
                          ▼
              ┌──────────────────────┐
              │ Multi-Model Analysis │
              └──────────┬───────────┘
                         │
                ┌────────┴────────┐
                ▼                 ▼
             Qwen-VL            GLM-V
                │                 │
                └────────┬────────┘
                         ▼
                Standardized Schema
                         │
                         ▼
                 Disagreement Check
                         │
                ┌────────┴─────────┐
                │                  │
             Agreement          Conflict
                │                  │
                ▼                  ▼
           Risk Engine        Human Review
                │
                ▼
            RAG Retrieval
                │
                ▼
             Reranker
                │
                ▼
          Evidence Judge
                │
         ┌──────┴───────┐
         │              │
     Evidence OK    Evidence Weak
         │              │
         ▼              ▼
    Final Result     Human Review
         │
         ▼
   Rectification Work Order
         │
         ▼
  Before/After Image Review
         │
         ▼
   Human Confirmation
         │
         ▼
       Closed
```

---

# 3. P0：真正实现 Multi-Model Ensemble

这是整个 V2 最重要的改造。

## 3.1 目标

当前如果只是：

```text
provider = qwen OR glm
```

不算真正的 MultiModel。

必须变成：

```text
                  Image
                    │
          ┌─────────┴─────────┐
          ▼                   ▼
       Qwen-VL              GLM-V
          │                   │
          └─────────┬─────────┘
                    ▼
              Ensemble Layer
```

两个模型**独立分析同一输入**。

---

## 3.2 Provider 抽象

检查现有：

```text
backend/app/services/providers/
```

尽可能复用已有实现。

必要时建立：

```text
backend/app/services/providers/
    base.py
    qwen.py
    zhipu.py
    factory.py
```

统一接口，例如：

```python
class VisionProvider:
    async def analyze(
        self,
        images,
        text_context=None,
    ) -> ModelAnalysis:
        ...
```

要求：

- workflow 不直接依赖具体 SDK。
- provider 负责 API 调用。
- provider 负责超时、重试、标准错误。
- 不在 provider 内做最终风险判断。
- API Key 只能来自配置/环境变量。

---

# 4. P0：统一 Structured Schema

两个模型必须输出统一结构。

建议：

```json
{
  "model": "qwen-vl",
  "model_version": "unknown",
  "hazards": [
    {
      "hazard_type": "fire_exit_blocked",
      "description": "消防疏散通道被纸箱占用",
      "severity": 3,
      "confidence": 0.91,
      "observed_facts": [
        "通道存在纸箱",
        "纸箱位于主要通行区域"
      ],
      "uncertainties": [],
      "location": {
        "image_id": "image_01",
        "bbox": [120, 240, 520, 680],
        "location_text": "图片中部偏右"
      }
    }
  ]
}
```

最少字段：

- model
- model_version
- hazards
- hazard_type
- description
- severity
- confidence
- observed_facts
- uncertainties
- location

---

# 5. P0：双模型并行调用

使用 `asyncio.gather` 或项目现有异步机制并行调用。

要求：

```text
Qwen成功 + GLM成功
    → 正常 Ensemble

Qwen成功 + GLM失败
    → 标记 partial_ensemble
    → 不得假装两个模型都成功
    → 根据风险等级决定是否人工复核

Qwen失败 + GLM成功
    → 同上

Qwen失败 + GLM失败
    → 使用现有 Mock / fallback
    → 明确标记 mock/fallback
```

必须记录：

- model
- latency
- status
- error_type
- retry_count

不能记录：

- API Key
- Authorization header
- 完整敏感用户数据

---

# 6. P0：Disagreement / 模型分歧检测

新增：

```text
backend/app/services/ensemble/
    __init__.py
    analyzer.py
    disagreement.py
    judge.py
```

至少检查：

### 6.1 隐患类别

```text
A = 消防通道堵塞
B = 消防通道占用

→ 高度相关，可判定为一致
```

但：

```text
A = 消防隐患
B = 电气隐患

→ 冲突
```

---

### 6.2 风险等级

如果：

```text
abs(A.severity - B.severity) > 1
```

默认进入人工复核。

---

### 6.3 关键事实

例如：

```text
A：发现灭火器
B：未发现灭火器
```

属于关键事实冲突。

---

### 6.4 置信度

不要简单：

```text
confidence >= 0.8 = safe
```

而是结合：

- 两模型 confidence
- category agreement
- severity difference
- factual conflict
- image quality

综合判断。

---

输出：

```json
{
  "agreement_score": 0.88,
  "category_agreement": true,
  "severity_difference": 0,
  "critical_conflict": false,
  "need_human_review": false,
  "reasons": []
}
```

---

# 7. P0：Ensemble Judge

新增：

```text
backend/app/services/ensemble/judge.py
```

Judge 输入：

- Model A structured result
- Model B structured result
- disagreement result
- image/text context
- Risk Engine result
- RAG evidence（如果已有）
- evidence validation result（如果已有）

Judge 输出必须结构化：

```json
{
  "final_findings": [],
  "final_severity": 3,
  "confidence": 0.90,
  "agreement_score": 0.92,
  "need_human_review": false,
  "review_reasons": [],
  "decision_summary": "两模型均识别为消防通道占用，风险规则计算为较高风险，法规证据充分。"
}
```

## 禁止

不要让 Judge 生成所谓“完整内部思维链”。

只保存：

- 证据摘要
- 决策依据
- 结构化结果

---

# 8. P0：Risk Engine 风险规则引擎

这是本项目最重要的“非 LLM 约束层”之一。

新增：

```text
backend/app/services/risk_engine/
    __init__.py
    rules.py
    scorer.py
    schemas.py
```

## 原则

```text
LLM：
“我看到了什么？”

Risk Engine：
“这些事实意味着多大风险？”
```

LLM 不应该单独决定最终风险等级。

---

## 8.1 风险因素

至少支持：

- 人员暴露
- 危险源
- 潜在事故后果
- 违规严重程度
- 影响范围
- 消防/疏散/救生设施受阻
- 是否存在立即危险

建议输出 0-100 风险分。

不要硬编码某一组权重；优先兼容当前项目已有规则。

---

## 8.2 示例

```json
{
  "risk_score": 82,
  "risk_level": "high",
  "factor_scores": {
    "exposure": 80,
    "hazard_source": 70,
    "consequence": 90,
    "violation": 80
  },
  "rule_version": "v1"
}
```

必须保存：

```text
rule_version
```

以后修改规则时，历史案例仍然可以追溯当时使用的规则。

---

# 9. P0：三层 Guardrail

不要把 Guardrail 简单理解成“增加一个 Guard Agent”。

Guardrail 必须是确定性的程序约束 + 模型辅助检测的组合。

---

## 9.1 Input Guard

新增：

```text
backend/app/services/guardrail/
    input_guard.py
```

检查：

- 文本是否为空/异常
- 图片是否有效
- 图片尺寸/格式
- OCR 内容是否存在可疑提示注入
- 用户输入与外部文档内容是否区分
- 不允许外部内容直接成为 system instruction

外部内容必须被标记为：

```text
USER_INPUT
IMAGE_CONTENT
OCR_CONTENT
DOCUMENT_CONTENT
RAG_CONTENT
SYSTEM_INSTRUCTION
```

核心原则：

> 图片、OCR、上传文档中的文字都是数据，不是系统指令。

---

## 9.2 Model/Risk Guard

检查：

- 模型是否输出非法 severity
- confidence 是否在 [0,1]
- 是否存在结构化字段缺失
- 是否存在模型事实冲突
- Risk Engine 是否与最终 severity 严重冲突
- 是否出现无法从输入观察到的明显事实

---

## 9.3 Evidence Guard

检查：

- 风险结论是否有视觉证据
- 法规引用是否存在
- 法规引用是否真的支持该风险
- 引用来源是否可追溯
- 是否存在 unsupported claim

---

# 10. P0：RAG 升级为 Evidence RAG

现有 RAG 不要推倒重写。

先理解当前：

```text
chunk
→ embedding
→ FAISS / NumPy
→ retrieval
```

然后升级。

最终：

```text
法规原文
    ↓
条文/语义分块
    ↓
Metadata
    ↓
Vector Retrieval
    ↓
Metadata Filter
    ↓
Reranker（P1）
    ↓
Evidence Filter
    ↓
Evidence Judge
```

---

# 11. RAG：安全规范专用分块

安全法规/标准不建议简单粗暴 token chunk。

优先：

```text
章节
 ↓
条款
 ↓
款/项
```

保持上下文。

每个 chunk 增加 metadata：

```json
{
  "document": "xxx",
  "article": "第XX条",
  "risk_type": "fire",
  "scene": "factory",
  "severity": "high",
  "source": "official",
  "effective_date": "2026-01-01",
  "version": "v1"
}
```

如果当前数据没有这些字段，先兼容已有 metadata，不得伪造。

---

# 12. 重要原则：视觉证据 ≠ 法规证据

不要实现：

```text
没有 RAG 证据
→ 判定不存在隐患
```

正确逻辑：

```text
视觉证据：
“图片中观察到了什么”

法规证据：
“为什么这个事实可能构成安全隐患/违规”
```

例如：

```text
Finding:
消防通道被纸箱占用

Visual Evidence:
image_01 + bbox

Regulatory Evidence:
document_x + article_y

Risk:
82 / high
```

如果视觉上确实存在明显风险，但没有可靠法规依据：

```text
risk_found = true
evidence_status = insufficient
need_human_review = true
```

而不是：

```text
risk_found = false
```

---

# 13. P1：Reranker

如果现有技术栈和依赖允许，加入 reranker。

优先流程：

```text
Vector Top-K
    ↓
Reranker
    ↓
Top-N
```

目标不是“为了技术名词而加”。

必须通过评测证明：

```text
Vector only
vs
Vector + Reranker
```

在法规命中率/证据相关性上是否提升。

如果提升不明显，可以保留为可选配置。

---

# 14. P0：Evidence Judge

新增：

```text
backend/app/services/evidence/
    judge.py
    matcher.py
    schemas.py
```

输入：

- hazard finding
- observed facts
- retrieved regulations
- source metadata

输出：

```json
{
  "supported": true,
  "support_score": 0.91,
  "evidence_ids": [
    "doc_001_chunk_12"
  ],
  "unsupported_claims": [],
  "needs_human_review": false
}
```

如果证据不足：

```json
{
  "supported": false,
  "support_score": 0.42,
  "unsupported_claims": [
    "当前法规证据不足以支持该严重程度"
  ],
  "needs_human_review": true
}
```

---

# 15. P0：Human-in-the-loop

人工复核不是“最后随便加一个按钮”。

必须形成明确触发机制。

至少以下情况进入人工复核：

```text
1. 双模型严重冲突
2. 风险等级差 > 1
3. 任一模型置信度过低
4. 图片质量不足
5. Risk Engine 与模型结论严重冲突
6. 法规证据不足
7. 高风险/重大风险
8. 系统处于 partial ensemble
9. 发生 fallback/mock
```

统一：

```json
{
  "need_human_review": true,
  "review_reasons": [
    "model_conflict",
    "insufficient_evidence"
  ]
}
```

---

# 16. P0：LangGraph 条件分支

不要继续单纯：

```text
A → B → C → D → E → F
```

改造成有条件分支的 StateGraph。

建议逻辑：

```text
START
  ↓
Input Guard
  ↓
Vision Analysis
  ↓
Disagreement
  ↓
   ┌──────────────┐
   │              │
 conflict      agreement
   │              │
   ▼              ▼
Human Review    Risk Engine
                   ↓
                 RAG
                   ↓
              Evidence Judge
                   ↓
          ┌────────┴────────┐
          │                 │
       sufficient        insufficient
          │                 │
          ▼                 ▼
      Finalize          Human Review
```

要求：

- 每个节点职责单一。
- 状态字段明确。
- 不要为了“Agent化”把每个节点都变成 LLM Agent。

---

# 17. LangGraph State 重新整理

检查现有 State。

至少区分：

```text
task_id
case_id

user_input
images

model_results
ensemble_result
disagreement_result

risk_result

retrieval_results
evidence_result

human_review
final_result

rectification

status
error
trace_id
```

状态生命周期：

```text
pending
processing
awaiting_human_review
finished
failed
```

要求：

- 不同任务状态隔离。
- 不同用户/Case 不得串状态。
- 每个 RAG result 必须带 source/chunk/document 信息。
- 每个模型结果必须带 model。
- 不得让一个 case 的中间状态污染另一个 case。

---

# 18. P1：结构化最终输出 Schema

最终 API 不要返回一大段自然语言。

推荐：

```json
{
  "case_id": "CASE-001",
  "status": "awaiting_human_review",
  "risk_level": "high",
  "risk_score": 82,
  "confidence": 0.90,

  "findings": [
    {
      "id": "F-001",
      "type": "fire_exit_blocked",
      "description": "消防通道被纸箱占用",

      "visual_evidence": [
        {
          "image_id": "image_01",
          "location_text": "图片中部偏右",
          "bbox": [120, 240, 520, 680]
        }
      ],

      "regulatory_evidence": [
        {
          "document_id": "doc_001",
          "article": "第XX条",
          "source": "official"
        }
      ],

      "risk_score": 82,
      "suggestions": [
        "立即清理通道障碍物"
      ]
    }
  ],

  "model_agreement": 0.92,
  "evidence_status": "supported",

  "human_review_required": true,
  "review_reasons": []
}
```

---

# 19. P1：图片隐患定位

如果当前视觉模型可以稳定输出 bbox，则支持：

```text
image_id
bbox
location_text
```

前端用框选方式展示。

但是：

> **禁止为了生成 bbox 而伪造坐标。**

如果模型无法可靠定位：

```text
bbox = null
location_text = "图片中部"
```

或者：

```text
location_status = "unavailable"
```

不要生成假的精确框。

---

# 20. P1：整改闭环强化

当前项目已有整改相关能力，必须优先复用。

目标：

```text
发现隐患
 ↓
风险分级
 ↓
整改建议
 ↓
整改工单
 ↓
上传整改后图片
 ↓
AI Before/After 对比
 ↓
整改完成度
 ↓
AI 复核
 ↓
人工确认
 ↓
关闭 Case
```

建议状态：

```text
OPEN
→ ASSIGNED
→ RECTIFYING
→ PENDING_VERIFICATION
→ VERIFIED
→ CLOSED
```

如果 AI 判断整改完成但人工未确认：

```text
PENDING_VERIFICATION
```

不能自动宣称正式关闭。

---

# 21. P1：前端改造成“可解释 AI 工作台”

不需要新增 Streamlit。

项目已经有 Vue 3，直接强化 Vue。

建议页面：

## 21.1 研判页面

```text
┌──────────────────────────────────────┐
│ 上传图片 / 输入描述                   │
├──────────────────────────────────────┤
│ AI分析进度                            │
│ ✓ 图片解析                            │
│ ✓ Qwen-VL                             │
│ ✓ GLM-V                               │
│ ✓ 模型一致性分析                      │
│ ✓ 风险规则计算                        │
│ ✓ 法规检索                            │
│ ✓ 证据验证                            │
├──────────────────────────────────────┤
│ 风险等级：高                          │
│ 风险分：82                             │
│                                      │
│ [图片 + 隐患框]                       │
│                                      │
│ 隐患：消防通道被占用                  │
│                                      │
│ 视觉证据                              │
│ 法规依据                              │
│ 风险计算                              │
│                                      │
│ [自动通过] / [进入人工复核]           │
└──────────────────────────────────────┘
```

---

# 22. P1：证据链 UI

用户必须能看到：

```text
隐患
 ↓
图片
 ↓
模型观察
 ↓
风险规则
 ↓
法规
 ↓
最终结论
```

不要只显示：

```text
AI说：高风险
```

---

# 23. P1：评测体系升级

这是竞赛项目非常重要的一部分。

不要只展示 Mock 的 100% 准确率。

Mock 只能作为：

> workflow/regression test

不能作为真实模型能力证明。

---

# 24. 建立真实 Evaluation Dataset

建议阶段：

```text
30 cases
 ↓
100 high-quality cases
 ↓
200 cases
```

不要为了数量随便生成大量样本。

每条样本尽量包含：

```text
image
scene
ground_truth_hazard
ground_truth_severity
ground_truth_risk_level
expected_evidence
expected_action
```

类别至少覆盖：

- 消防
- 生产安全
- 社区
- 森林/户外
- 正常无隐患
- 边界案例
- 图片质量差
- 多隐患
- 对抗/提示注入

---

# 25. 必须做 Ablation Study

至少比较：

```text
A: Qwen only
B: GLM only
C: Qwen + GLM
D: Qwen + GLM + Risk Engine
E: Qwen + GLM + Risk Engine + Evidence RAG
F: Full System
```

核心指标：

### 分类

- hazard category accuracy

### 风险等级

- exact accuracy
- ±1 level accuracy
- MAE

### RAG

- evidence hit rate
- evidence support rate

### 幻觉

- unsupported claim rate

### Ensemble

- model disagreement rate
- conflict detection rate

### 人工复核

- review rate
- high-risk recall
- unsafe auto-pass rate

---

# 26. 特别增加一个安全指标：Unsafe Auto-Pass Rate

这是本项目非常有价值的指标。

定义：

> 系统自动通过，但人工 Ground Truth 判断实际上存在高风险隐患的比例。

目标：

```text
Unsafe Auto-Pass Rate ↓
```

比单纯：

```text
Accuracy ↑
```

更符合安全场景。

---

# 27. P1：测试

至少增加：

```text
tests/
    unit/
        test_risk_engine.py
        test_disagreement.py
        test_schema.py
        test_evidence.py
        test_guardrail.py

    integration/
        test_workflow.py
        test_fallback.py
        test_human_review.py
```

必须覆盖：

### 正常

- 正常图片
- 单隐患
- 多隐患

### 异常

- 损坏图片
- 空图片
- 模型超时
- API 失败
- RAG 失败

### 安全

- Prompt Injection 文本
- OCR 注入
- 恶意文档内容

### Ensemble

- 两模型一致
- 两模型冲突
- 单模型失败
- 双模型失败

---

# 28. P2：配置与工程化

检查：

```text
.env
.env.example
```

统一配置：

```text
MODEL_API_KEY
MODEL_BASE_URL
MODEL_TIMEOUT
MODEL_RETRY
RAG_TOP_K
RISK_RULE_VERSION
LOG_LEVEL
```

禁止：

```python
API_KEY = "sk-xxxxx"
```

必须：

```python
settings.model_api_key
```

同时检查 `.gitignore`。

---

# 29. P2：异常与降级

统一异常体系。

建议：

```text
ModelTimeoutError
ModelUnavailableError
RAGUnavailableError
InvalidImageError
SchemaValidationError
EvidenceValidationError
```

模型策略：

```text
retry
 ↓
fallback provider
 ↓
partial result
 ↓
human review
```

不要：

```text
API失败 → 整个系统500崩溃
```

---

# 30. P2：模型熔断/重试

实现简单版本即可，不需要复杂微服务。

建议：

```text
timeout = configurable
max_retry = 1~2
exponential backoff
```

如果连续失败：

```text
provider_status = degraded
```

必要时切换备用模型。

不需要为了这个引入 Redis/Kafka。

---

# 31. P2：执行轨迹 / Observability

记录：

```text
trace_id
case_id
node_name
start_time
end_time
status
model_name
latency
retry_count
retrieval_count
retrieval_ids
error_type
```

建议：

```text
logs/
```

或使用现有 logging。

禁止无脑记录：

- API Key
- Authorization
- 敏感个人信息
- 完整上传图片
- 不必要的完整 prompt

原始模型输出如需保存，应优先保存结构化结果和摘要。

---

# 32. P2：Docker

如果当前项目适合，增加：

```text
Dockerfile
docker-compose.yml
.dockerignore
```

但：

> Docker 是交付能力，不是核心创新。

必须保证：

```text
本地运行
```

优先于：

```text
Docker复杂化
```

不要为了 Milvus 强行增加大量基础设施。

---

# 33. P2：数据库与历史记录

当前项目已有 SQLite + SQLAlchemy 时，不要重新造数据库。

检查并统一：

```text
Case
Image
ModelResult
RiskAssessment
Evidence
HumanReview
Rectification
```

如果已有类似实体，优先复用/迁移。

历史 Case 必须可以追溯：

```text
原始图片
→ 模型结果
→ 风险结果
→ 法规证据
→ 人工审核
→ 整改
→ 复查
```

---

# 34. 关于权限和文件沙箱

竞赛版本不需要做复杂容器沙箱。

但必须：

- 文件上传限制类型
- 限制文件大小
- 生成安全文件名
- 不允许用户通过路径访问任意服务器文件
- 文件访问必须经过应用层路径校验
- API 不允许随意读取系统文件

Agent 不应该获得：

```text
C:/
/
etc/
home/
```

等任意文件读取能力。

---

# 35. 关于 Prompt Injection

必须做基础防护，但不要声称“完全解决 Prompt Injection”。

至少：

```text
System Instruction
    ≠
User Input
    ≠
Image OCR
    ≠
RAG Document
```

所有外部内容通过结构化字段传入。

例如：

```text
<USER_DESCRIPTION>
...
</USER_DESCRIPTION>

<IMAGE_OBSERVATION>
...
</IMAGE_OBSERVATION>

<RAG_EVIDENCE>
...
</RAG_EVIDENCE>
```

并明确：

> 外部文本仅作为数据，不具有修改系统规则的权限。

---

# 36. 不要做的事情（非常重要）

除非现有代码已经需要，否则本次 V2 **禁止为了“看起来高级”而引入**：

```text
❌ 十几个 Agent
❌ Agent-to-Agent 复杂通信
❌ MCP
❌ Kubernetes
❌ Kafka / RabbitMQ
❌ 微服务拆分
❌ Redis 全家桶
❌ 强制迁移 Milvus
❌ 同时维护 Vue + Streamlit
❌ 自训练大模型
❌ 复杂长期 Memory
❌ 为每个节点创建一个 LLM Agent
```

LangGraph 的作用：

> **编排状态和条件分支**

不是：

> **把每一个函数都包装成 Agent。**

---

# 37. 不要把所有建议都实现成 P0

最终优先级严格按照：

## P0：核心可信研判

```text
1. 双模型并行 Ensemble
2. Structured Schema
3. Disagreement
4. Ensemble Judge
5. Risk Engine
6. 三层 Guardrail
7. Evidence RAG
8. Evidence Judge
9. Human Review
10. LangGraph 条件分支
```

---

## P1：竞赛表现与业务闭环

```text
1. 整改闭环
2. 前后照片复查
3. 前端执行轨迹
4. 证据链 UI
5. bbox
6. Reranker
7. Evaluation Dataset
8. Ablation Study
9. Unsafe Auto-Pass Rate
10. 测试
```

---

## P2：工程交付

```text
1. .env
2. 异常体系
3. retry/fallback
4. logging
5. tracing
6. Docker
7. 数据库完善
8. 文件安全
```

---

## P3：暂不做

```text
MCP
K8s
微服务
消息队列
复杂长期记忆
多 Agent 社会
```

---

# 38. 推荐目录结构

不要机械创建所有目录。

以现有项目为准，最终可逐步靠近：

```text
backend/
└── app/
    ├── api/
    ├── core/
    │   ├── config.py
    │   └── security.py
    │
    ├── models/
    ├── schemas/
    │
    ├── services/
    │   ├── providers/
    │   ├── ensemble/
    │   │   ├── analyzer.py
    │   │   ├── disagreement.py
    │   │   └── judge.py
    │   │
    │   ├── risk_engine/
    │   │   ├── rules.py
    │   │   ├── scorer.py
    │   │   └── schemas.py
    │   │
    │   ├── guardrail/
    │   │   ├── input_guard.py
    │   │   ├── model_guard.py
    │   │   └── evidence_guard.py
    │   │
    │   ├── retrieval/
    │   ├── evidence/
    │   │   ├── judge.py
    │   │   └── matcher.py
    │   │
    │   ├── rectification/
    │   └── evaluation/
    │
    └── workflow/
        └── graph.py

frontend/
└── src/
    ├── views/
    ├── components/
    │   ├── AnalysisTrace.vue
    │   ├── EvidenceChain.vue
    │   ├── HazardOverlay.vue
    │   ├── ModelComparison.vue
    │   └── RiskSummary.vue
    └── stores/
```

**注意：如果现有目录命名不同，不要为了匹配这个树而进行大规模重命名。**

---

# 39. 数据流必须统一

建议最终内部数据流：

```text
Case
 ↓
Input
 ↓
VisionAnalysis[]
 ↓
EnsembleResult
 ↓
DisagreementResult
 ↓
RiskAssessment
 ↓
RetrievalResult[]
 ↓
EvidenceAssessment
 ↓
HumanReview?
 ↓
FinalAssessment
 ↓
Rectification
 ↓
Verification
```

每一步都必须带：

```text
case_id
trace_id
created_at
status
source
```

必要时：

```text
version
```

---

# 40. API 最终建议

检查现有 API，尽量复用。

至少应支持：

```text
POST /cases
POST /cases/{id}/analyze

GET /cases/{id}
GET /cases/{id}/trace
GET /cases/{id}/evidence

POST /cases/{id}/review
POST /cases/{id}/rectification

POST /cases/{id}/verification
```

不要为了 REST “完美”而大规模重构。

---

# 41. 安全输出原则

最终系统所有结果都必须明确：

```text
AI辅助研判
```

高风险结果：

```text
建议人工确认
```

不能出现：

```text
AI已确认不存在任何安全隐患
```

这种绝对化表述。

更合理：

```text
当前模型未发现明显隐患，但图片质量/证据存在一定限制，
建议结合人工现场检查。
```

---

# 42. README 必须同步升级

README 必须解释：

## 42.1 项目定位

多模态安全隐患智能研判与人机协同闭环。

## 42.2 核心架构

展示：

```text
Qwen + GLM
↓
Ensemble
↓
Risk Engine
↓
Evidence RAG
↓
Human Review
↓
Rectification
```

## 42.3 为什么 MultiModel

说明：

> 双模型并行不是为了增加模型数量，而是为了降低单模型误判，并通过 disagreement 检测发现不确定案例。

## 42.4 为什么 Risk Engine

说明：

> LLM负责感知与事实提取，规则引擎负责风险计算，降低模型自由决定风险等级带来的不确定性。

## 42.5 为什么 Human-in-the-loop

说明：

> 高风险、模型冲突、证据不足、低置信度等情况下，系统不会强制自动决策。

## 42.6 Evaluation

README必须展示真实评测方法。

Mock 结果必须明确标注：

```text
Mock / workflow regression only
```

不能冒充真实模型性能。

---

# 43. 评测结果禁止作弊

Codex 必须遵守：

```text
禁止：
为了提高准确率修改 ground truth
为了通过测试硬编码答案
为了得到好看的指标删除困难样本
把 Mock 指标写成真实模型指标
```

可以：

```text
修复 bug
优化 prompt
优化 retrieval
优化规则
增加测试样本
```

但必须保留实验可追溯性。

---

# 44. 最终验收标准

完成后至少满足：

## A. MultiModel

- [ ] Qwen 与 GLM 可以并行调用
- [ ] 两者结果统一 Schema
- [ ] 单模型失败不会导致整个流程崩溃
- [ ] 两模型冲突能够检测
- [ ] conflict 能触发人工复核
- [ ] 能看到两个模型的结果

## B. Risk Engine

- [ ] 风险等级不完全由 LLM 决定
- [ ] 有独立规则模块
- [ ] 有 risk_score
- [ ] 有 rule_version
- [ ] 历史结果可追溯规则版本

## C. Guardrail

- [ ] 有输入校验
- [ ] 有 Prompt Injection 基础防护
- [ ] 有模型输出校验
- [ ] 有 Evidence Guard
- [ ] 不把外部内容当系统指令
- [ ] 不允许任意文件读取

## D. RAG

- [ ] 保留现有 RAG 能力
- [ ] 法规 chunk 支持条文/语义粒度
- [ ] metadata 完整
- [ ] evidence 可追溯
- [ ] Reranker 如果实现必须可配置
- [ ] Evidence Judge 可以判断支持/不足

## E. Human Review

- [ ] 高风险可以人工复核
- [ ] 模型冲突可以人工复核
- [ ] 证据不足可以人工复核
- [ ] fallback/mock 可以人工复核
- [ ] 人工确认后才可正式关闭高风险 Case

## F. Rectification

- [ ] 可以生成整改建议
- [ ] 可以创建整改任务
- [ ] 可以上传整改后图片
- [ ] 可以进行前后对比
- [ ] 可以 AI 复查
- [ ] 可以人工确认

## G. Evaluation

- [ ] 有真实评测集
- [ ] 有 Ground Truth
- [ ] 有 Qwen-only
- [ ] 有 GLM-only
- [ ] 有 Qwen+GLM
- [ ] 有完整系统
- [ ] 有至少 5 个核心指标
- [ ] 有 Unsafe Auto-Pass Rate
- [ ] Mock 与真实模型指标分开

## H. Engineering

- [ ] `.env` / `.env.example`
- [ ] 无 API Key 硬编码
- [ ] 异常统一处理
- [ ] retry/fallback
- [ ] 单元测试
- [ ] 集成测试
- [ ] README 同步
- [ ] 项目可以按 README 从零启动

---

# 45. Codex 最终执行顺序

严格按照下面顺序推进。

## Phase 0：代码审计

```text
读取现有仓库
↓
CURRENT_ARCHITECTURE.md
↓
确定复用点
```

不要立即重构。

---

## Phase 1：P0 核心链路

```text
Provider abstraction
↓
Structured Schema
↓
Qwen + GLM parallel
↓
Disagreement
↓
Ensemble Judge
↓
Risk Engine
↓
Evidence RAG
↓
Evidence Judge
↓
Human Review
↓
LangGraph conditional routing
```

每完成一个阶段：

```text
pytest
```

并修复回归。

---

## Phase 2：P1 业务与竞赛表现

```text
Rectification Loop
↓
Before/After
↓
Evidence UI
↓
Model Comparison UI
↓
AI Trace UI
↓
bbox
↓
Reranker
↓
Evaluation
↓
Ablation
```

---

## Phase 3：P2 工程完善

```text
.env
↓
Exception handling
↓
Retry/Fallback
↓
Logging
↓
Tracing
↓
File security
↓
Docker
↓
README
```

---

# 46. 每个阶段结束必须给出报告

Codex 每完成一个 Phase，输出：

```text
1. 修改了哪些文件
2. 新增了哪些文件
3. 为什么修改
4. 当前架构变化
5. 测试结果
6. 未完成项
7. 风险/兼容性问题
```

不要只回复：

```text
Done.
```

---

# 47. 最终 Codex 自检

完成后必须执行：

```text
pytest
```

以及项目已有的 lint/type/test 命令。

如果有 frontend：

```text
npm install
npm run build
```

或根据现有 package.json 使用对应命令。

检查：

```text
API启动
Frontend启动
数据库初始化
RAG加载
Mock fallback
Qwen provider
GLM provider
Human review
Rectification
```

---

# 48. 最终答辩叙事

完成以后，项目不要介绍成：

> “这是一个使用 LangGraph 调用大模型识别安全隐患的系统。”

应该介绍成：

> **“这是一个面向基层安全巡查场景的多模态安全隐患智能研判系统。系统通过 Qwen-VL 与 GLM-V 两个视觉模型并行分析同一现场，通过模型交叉验证发现分歧；随后使用风险规则引擎对模型提取的客观事实进行风险计算，再通过法规知识库检索和 Evidence Judge 验证法规依据。对于高风险、模型冲突、证据不足等情况，系统不会直接自动决策，而是进入人工复核。最终系统还将隐患研判延伸到整改工单、整改后图片复查和人工确认，实现从发现到闭环的安全治理流程。”**

这个故事比：

> “我们用了很多 Agent”

更有说服力。

---

# 49. 最终核心架构一句话

最终项目的核心不是：

```text
更多模型
更多 Agent
更多技术名词
```

而是：

```text
多模型感知
    +
交叉验证
    +
规则约束
    +
法规证据
    +
人工复核
    +
整改闭环
    +
真实评测
```

最终形成：

> **“模型负责看，规则负责算，知识库负责证，人负责最终把关，系统负责形成闭环。”**

这就是 V2 的最终目标。
