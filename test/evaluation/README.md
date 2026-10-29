# R6 图片工程边界集

`cases.jsonl` 使用数据 schema 2.0、版本 `r6-synthetic-v1`：12 个案例引用 10 张项目内生成的几何 PNG，包含 8 个规格定义隐患、4 个明确负例。图像全部带 synthetic 标记，不含第三方照片；来源与使用授权说明逐行记录。`build_boundary.py` 可重复生成图片和清单。

四类场景为消防、生产安全、社区、林区。`coverage_tags` 覆盖负例、低质量、多隐患、图文矛盾和证据不足。每条有主类别/等级、逐项 finding 真值、标注方法与复核状态；标注者是自动规格 `boundary-spec-v1`，状态为 synthetic_spec，不能当作人工现场复核。低质量图的隐患真值来自底层合成规格，期望行为是拒判并补图。

证据支持标签只有一条 False 的合成规格，其余显式为 null 并说明原因，未取得独立人工法规标签。它不判断真实违法性。报告分别记录系统自评、独立规格标签和排除 synthetic 后的人工标签指标。

## 运行

从仓库根目录执行，每次使用新的输出目录：

```powershell
.\backend\.venv\Scripts\python.exe test/evaluation/run_mock.py --output test/.artifacts/evaluation/my-run
.\backend\.venv\Scripts\python.exe test/evaluation/run_mock.py --output test/.artifacts/evaluation/my-run --ablation
.\backend\.venv\Scripts\python.exe scripts/check_eval_baseline.py
```

隔离入口清除真实 Key、数据库与认证环境，在独立 test/.artifacts 路径从只读开发种子初始化知识库。Mock 用于工程输入/状态回归，不分析像素语义。假 HTTP Provider 用例另行验证实际传出的 base64 图片内容。

正式报告保存在 `docs/evaluation/r6-v2/`，数据仍留在本目录，归档只保留摘要引用。历史 60 条文本集 `backend/data/eval_cases/cases.jsonl` 与旧归档保留；R6 没有把它们重标成真实图像基准。

## 指标、门禁与费用

schema 2 使用 finding 判断检测，人工复核不取消 FP/FN。可用检测 recall 排除缺失，全部隐患 recall 把缺失视为未成功，报告同时展示覆盖率和各分母。失败、信息不足、正确拒判与流程拦截独立统计。当前检测是案例级存在性与主类别指标；虽然多隐患真值逐项列出，尚不声称逐项定位评测达标。

`gate-policy-v2.json` 在本轮评测前登记：回归容差仍为 2pp，不安全自动通过和执行失败上限均为 0；缺失身份、指标、分母或不同实验禁止比较。阈值没有为本轮成绩降低。Mock 基线中的误报和拒判原样保存，门禁通过仅说明工程行为没有相对该基线退化。

通用 `scripts/evaluate.py` / `scripts/ablation.py` 支持 `--cases`、`--dataset-version`、`--gate-policy`、`--pricing` 和新的 `--output`。auto 无 Key 按 Mock 标记；真实调用须另行配置与执行，调用次数包含 embedding、追问、refine 和重试，不能用案例数估算。报告记录每次 HTTP 的原样服务模型标识、用量、错误和耗时。服务未返回用量或没有执行前登记价格时，费用为 N/A；有价格也仅为估算，不替代供应商账单。

价格文件为 `{ "currency": "币种", "models": { "服务模型标识": { "input_per_million": 单价, "output_per_million": 单价 } } }`；单价必须非负有限数。所有报告拒绝覆盖已有结果，应为新批次建立新目录。

## 真实场景验收

见 `real-acceptance-status.json`：真实现场图片 0，独立人工复核案例 0，R6 真实模型批次 0。实际取得授权数据后，逐行补齐来源、授权、图片、真值、人工标注者、reviewed 状态和独立证据标签，在首批执行前另行登记质量目标。真实准确率、误报控制和法规适用性当前仍待验证，继续推进 R7 不会改变这一状态。
