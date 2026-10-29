# 评测体系文档

本目录是正式评测体系的说明和结果归档。评测本身由 `scripts/evaluate.py` 与
`scripts/ablation.py` 执行，数据源为 `test/evaluation/cases.jsonl`。

## 评测命令

```powershell
.\backend\.venv\Scripts\python.exe scripts\evaluate.py --provider mock --variant full --cases "test/evaluation/cases.jsonl" --output test/.artifacts/evaluation/manual-single
.\backend\.venv\Scripts\python.exe scripts\ablation.py --provider mock --cases "test/evaluation/cases.jsonl" --output test/.artifacts/evaluation/manual-ablation
```
每次执行使用新的 --output 目录；已有结果禁止覆盖。隔离 Mock 门禁请运行 scripts/check_eval_baseline.py。

真实模型评测（按量计费）：把上面 `--provider mock` 换成 `--provider auto`。

## 当前归档

- 数据集版本：`r6-synthetic-v1`, 案例数：`12`
- 数据来源分布：`{"synthetic": 12}`
- 执行模式：`mock`（以 evaluation_mode 为准；auto 无 Key 可降级 Mock）
- 归档时间：`2026-10-29T06:36:54.951272+00:00`

- 数据集：`dataset/`
- A-F 对比报告：`reports/ablation_report.md`
- 清洗后的逐条结果：`results/ablation_results.jsonl`
- 单变体正式报告：`reports/evaluation_report.md`（如果存在）

## 消融对比表

| 变体 | 数据模式 | 类别 | 等级 | MAE | 条款 | 证据支持 | 复核 | 分歧 | Unsafe |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Qwen+GLM | mock | 0.75 | 0.0 | N/A | N/A | 0.0 | 0.6667 | 0.0 | 0.0 |
| Full system | mock | 0.75 | 0.625 | 0.2857 | N/A | 0.25 | 0.6667 | 0.0 | 0.0 |
| GLM only | mock | 0.75 | 0.0 | N/A | N/A | 0.0 | 0.6667 | N/A | 0.0 |
| Qwen+GLM+Risk+RAG | mock | 0.75 | 0.625 | 0.2857 | N/A | 0.25 | 0.6667 | 0.0 | 0.0 |
| Qwen+GLM+Risk | mock | 0.75 | 0.625 | 0.2857 | N/A | 0.0 | 0.6667 | 0.0 | 0.0 |
| Qwen only | mock | 0.75 | 0.0 | N/A | N/A | 0.0 | 0.6667 | N/A | 0.0 |
## 来源与模式说明

- `curated / official / donated`：人工整理的**真实标注数据**。
- `synthetic`：合成/边界案例，报告中按 `source_type` 单独统计，不混入真实标注结果。
- `mock`：未配置 API Key 或显式 `--provider mock` 时的确定性 Mock 输出，
  报告中必须标注 `evaluation_mode=mock`，禁止冒充真实评测。

## 可比性与版本

- 报告 schema：2.0；指标 schema：2.0
- 数据摘要：aaf382b956a1e3f4cc2417ca6c469b4f3d5c3c83c13b53168ffdab7c92de6ea1
- schema 2 与历史报告不可直接比较；Mock 与 synthetic 仅证明工程链路，真实场景验收另行执行。

## Dataset Overview

- 类别分布：`{"占用疏散通道": 4, "无隐患": 4, "电气线路隐患": 1, "公共区域安全隐患": 1, "野外用火风险": 1, "危险化学品存储不规范": 1}`
- 等级分布：`{"1": 6, "3": 4, "2": 2}`
- 有隐患样本：`8`；无隐患负样本：`4`；含图片：`12`

## Limitations

- 尚未进行真实模型完整回归与多场景图片评测