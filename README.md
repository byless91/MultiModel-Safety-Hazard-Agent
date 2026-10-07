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

当前 Mock 模式下 30 条评测结果：类别准确率 100%，等级容差准确率 100%，高风险复核率 100%，条款命中率 40%（条款命中率会随真实知识库扩充而提升）。

### 真实模型评测（2026-09-10 实跑）

单轮 30 条、Qwen-VL + GLM-V 双模型并行（`scripts/evaluate.py --provider auto`）：

| 指标 | 值 |
| --- | --- |
| 类别准确率 | 0.5333 |
| 等级准确率 | 0.6667 |
| 等级容差（±1） | 1.0 |
| 条款命中率 | 0.6667 |
| 高风险复核率 | 1.0 |
| 不安全自动通过率 | 0.0 |
| 平均耗时（秒/案例） | 18.2 |

结果落在 `backend/data/eval/report.json` / `report.md`，作为真实模型基线；会随模型版本、知识库更新变化。

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
