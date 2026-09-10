# 评测体系文档

本目录是正式评测体系的说明和结果归档。评测本身由 `scripts/evaluate.py` 与
`scripts/ablation.py` 执行，数据源为 `backend/data/eval_cases/`。

## 评测命令

```powershell
.\backend\.venv\Scripts\python.exe scripts\evaluate.py --provider mock --variant full
.\backend\.venv\Scripts\python.exe scripts\ablation.py --provider mock
```

真实模型评测（按量计费）：把上面 `--provider mock` 换成 `--provider auto`。

## 当前归档

- 数据集版本：`v1`, 案例数：`30`
- 数据来源分布：`{"curated": 30}`
- 执行模式：`mock`（`mock`=确定性 Mock，`auto`=真实模型）
- 归档时间：`2026-09-10T12:21:12.590039+00:00`

- 数据集：`dataset/`
- A-F 对比报告：`reports/ablation_report.md`
- 清洗后的逐条结果：`results/ablation_results.jsonl`
- 单变体正式报告：`reports/evaluation_report.md`（如果存在）

## 消融对比表

| 变体 | 数据模式 | 类别 | 等级 | MAE | 条款 | 证据支持 | 复核 | 分歧 | Unsafe |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Qwen+GLM | mock | 1.0 | 0.0 | None | 0.0 | 0.0 | 1.0 | 0.0 | 0.0 |
| Full system | mock | 1.0 | 0.7333 | 0.2667 | 0.4 | 0.2667 | 1.0 | 0.0 | 0.0 |
| GLM only | mock | 1.0 | 0.0 | None | 0.0 | 0.0 | 1.0 | 0.0 | 0.0 |
| Qwen+GLM+Risk+RAG | mock | 1.0 | 0.7333 | 0.2667 | 0.4 | 0.2667 | 1.0 | 0.0 | 0.0 |
| Qwen+GLM+Risk | mock | 1.0 | 0.7333 | 0.2667 | 0.0 | 0.0 | 1.0 | 0.0 | 0.0 |
| Qwen only | mock | 1.0 | 0.0 | None | 0.0 | 0.0 | 1.0 | 0.0 | 0.0 |
## 来源与模式说明

- `curated / official / donated`：人工整理的**真实标注数据**。
- `synthetic`：合成/边界案例，报告中按 `source_type` 单独统计，不混入真实标注结果。
- `mock`：未配置 API Key 或显式 `--provider mock` 时的确定性 Mock 输出，
  报告中必须标注 `evaluation_mode=mock`，禁止冒充真实评测。

## Dataset Overview

- 类别分布：`{"占用疏散通道": 9, "消防器材失效": 6, "电气线路隐患": 4, "危险化学品存储不规范": 3, "公共区域安全隐患": 3, "野外用火风险": 5}`
- 等级分布：`{"1": 12, "2": 16, "3": 2}`
- 有隐患样本：`30`；无隐患负样本：`0`；含图片：`0`

## Limitations

- 当前数据集缺少无隐患负样本，FP 与正确自动通过能力无法完整评估
- 当前数据集全部为文本场景，尚未验证真实图片输入链路
- 未标注 expected_evidence_supported，证据支持率按系统 Evidence Judge 结果统计