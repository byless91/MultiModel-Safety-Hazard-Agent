# 评测体系与归档索引

更新：2026-10-29。R8 重新执行 schema 2 Mock 门禁通过；当前工程报告为 [R6 单变体](r6-v2/reports/evaluation_report.md) 和 [R6 消融](r6-v2/reports/ablation_report.md)，数据规范见 [边界集说明](../../test/evaluation/README.md)，验收证据见 [R8 记录](../baselines/r8-2026-10-29.md)。

## 数据集与版本

| 位置 | 范围 | 用途 |
|---|---|---|
| test/evaluation/cases.jsonl | schema 2.0，r6-synthetic-v1，12 案例引用 10 张合成 PNG；8 隐患/4 负例 | 当前离线工程基线 |
| backend/data/eval_cases/cases.jsonl | 60 条文本，图片 0、明确负例 0、独立证据标签 0 | 历史输入与兼容回归 |
| 本目录原 dataset/、reports/、results/ | 旧 30 条批次和历史导出；以对应报告清单为准 | 历史归档，不与 schema 2 直接比较 |

curated/official/donated 等来源字符串不能证明现场授权、图片真实性或人工审核已经完成。当前 12 条全部是 synthetic_spec，证据标签只有一条合成规格 False，其余为 null；独立人工证据正确率为 N/A。真实现场图片、独立人工复核案例及本轮真实模型批次均为 0，见 [真实验收状态](../../test/evaluation/real-acceptance-status.json)。

## 运行与门禁

仓库根目录执行，输出目录每轮使用新名字；所有报告拒绝覆盖已有文件：

```powershell
.\backend\.venv\Scripts\python.exe scripts/check_eval_baseline.py
.\backend\.venv\Scripts\python.exe test/evaluation/run_mock.py --output test/.artifacts/evaluation/new-full
.\backend\.venv\Scripts\python.exe test/evaluation/run_mock.py --output test/.artifacts/evaluation/new-ablation --ablation
```

隔离入口清除真实 Key，使用独立数据库/知识/缓存与 Mock。Mock 不理解像素，图片解码和实际发送内容由假 Provider 合同测试补充验证。通用 evaluate.py/ablation.py 支持 --cases、--dataset-version、--gate-policy、--pricing、--output；直接脚本使用调用者配置，不等同于上述离线隔离入口。

schema 2 把检测 FP/FN、缺失/拒判和流程拦截分开，转人工不能抹去误报。报告同时提供检测覆盖率、条件召回、全部隐患召回及分母；证据自评和独立标签正确率分开，缺标签为 N/A。多隐患清单保留逐项真值，当前汇总仍是案例存在性和主类别，不能声称定位准确率已达标。

门禁预先登记于 test/evaluation/gate-policy-v2.json：关键可比指标容差 2pp，不安全自动通过和执行失败上限 0。数据/指标/配置/模型模式身份不同，或缺指标/有效分母时失败。通过只表示相对已有 Mock 基线未退化，不表示真实质量达到产品标准。

## 真实评测与历史记录

auto 无 Key 也可能运行 Mock，以报告实际 evaluation_mode、服务模型标识和 HTTP 观察为准。真实评测需要先取得授权图片和人工真值，登记质量目标与价格，再独立执行；本轮没有调用付费服务。调用数包括 embedding、追问、refine、重试，不能用案例数估算。缺用量或价格时费用为 N/A。

原 reports/ablation_report.md、results/ablation_results.jsonl、dataset/ 及 README 中曾引用的旧 B5 成绩由相应历史报告/提交保留，不覆盖重算。历史 Mock/auto 的 30 条文本结果与当前 12 条合成图结果既不共享样本，也不共享全部指标口径，不能据此声称质量提高。后续真实批次另建版本目录，不修改旧结果来通过门禁。
