# 正式评测报告

- 数据集版本：r6-synthetic-v1（R6 合成图片工程边界集（非真实现场））
- 案例数：12；本次运行：12
- 评测模式：mock（请求：mock）
- 生成时间：2026-10-29T06:36:51.570856+00:00
- 报告/指标/数据 schema：2.0 / 2.0 / 2.0
- 数据集摘要：aaf382b956a1e3f4cc2417ca6c469b4f3d5c3c83c13b53168ffdab7c92de6ea1；本次样本摘要：aaf382b956a1e3f4cc2417ca6c469b4f3d5c3c83c13b53168ffdab7c92de6ea1
- Prompt：vision-v2；规则版本：['risk-engine-v1']
- 模型标识（服务返回值不保证供应商冻结版本）：['mock:mock-vision']

## Dataset Overview

- 案例数：12，来源：{"synthetic": 12}
- 类别分布：{"占用疏散通道": 4, "无隐患": 4, "电气线路隐患": 1, "公共区域安全隐患": 1, "野外用火风险": 1, "危险化学品存储不规范": 1}
- 等级分布：{"1": 6, "3": 4, "2": 2}
- 场景分布：{"林区": 2, "消防": 5, "生产安全": 3, "社区": 2}
- 有隐患样本：8；无隐患负样本：4
- 含图片案例：12；标注 expected_evidence_supported：1
- 本次声明图片：12；成功加载：12；输入失败案例：0

## 总体指标

| 指标 | 数值 |
| --- | --- |
| 检测 Precision | 0.875 |
| 检测 Recall（可用检测） | 1.0 |
| 检测 Recall（全部隐患） | 0.875 |
| 检测 FP | 1 |
| 检测 FN | 0 |
| 检测缺失数 | 4 |
| 检测覆盖率 | 0.6667 |
| 类别准确率 | 0.75 |
| 等级准确率 | 0.625 |
| 等级 MAE | 0.2857 |
| 等级容差（±1） | 0.875 |
| 法规证据命中率 | N/A |
| 证据支持率（系统自评） | 0.25 |
| 独立证据标签正确率 | 1.0 |
| 独立人工证据标签正确率（排除合成规格） | N/A |
| 无依据结论率 | 0.5 |
| 模型分歧率 | 0.0 |
| 人工复核率 | 0.6667 |
| 高风险实际复核率 | 0.8333 |
| 隐患流程拦截率 | 1.0 |
| 信息不足率 | 0.3333 |
| 正确拒判数（有标签） | 1 |
| 拒判标签正确率 | 0.75 |
| 执行失败率 | 0.0 |
| Unsafe Auto-Pass 率 | 0.0 |
| Unsafe Auto-Pass 数 | 0 |
| 平均耗时（秒） | 0.039 |

### 指标分母与缺失

| 指标 | 分子 | 分母 | 缺失 |
| --- | --- | --- | --- |
| detection_precision | 7 | 8 | 4 |
| detection_recall | 7 | 7 | 1 |
| detection_specificity | 0 | 1 | 3 |
| detection_coverage | 8 | 12 | 4 |
| end_to_end_hazard_recall | 7 | 8 | 1 |
| category_accuracy | 6 | 8 | 1 |
| level_accuracy | 5 | 8 | 1 |
| level_accuracy_tolerance1 | 7 | 8 | 1 |
| severity_mae | 2 | 7 | 1 |
| clause_hit_rate | 0 | 0 | 12 |
| evidence_hit_rate | 0 | 0 | 12 |
| system_evidence_support_rate | 2 | 8 | 4 |
| evidence_support_rate | 2 | 8 | 4 |
| independent_evidence_accuracy | 1 | 1 | 11 |
| independent_human_evidence_accuracy | 0 | 0 | 12 |
| unsupported_claim_rate | 6 | 12 | 0 |
| model_conflict_rate | 0 | 12 | 0 |
| human_review_rate | 8 | 12 | 0 |
| high_risk_review_rate | 5 | 6 | 0 |
| hazard_interception_rate | 8 | 8 | 0 |
| unsafe_auto_pass_rate | 0 | 8 | 0 |
| information_insufficient_rate | 4 | 12 | 0 |
| abstention_accuracy | 9 | 12 | 0 |
| execution_failure_rate | 0 | 12 | 0 |

### 调用与费用

- 实际 HTTP 尝试：0；错误：0；累计 HTTP 耗时：0 ms（可能并发，不等于墙钟时间）
- 返回用量：input=0，output=0；用量缺失尝试：0
- 费用：0.0 ；状态：no_http_calls；缺少计价依据：0
- 费用仅按执行前登记价格估算，不替代供应商账单。

## 数据集分布

- 类别：{'占用疏散通道': 4, '无隐患': 4, '电气线路隐患': 1, '公共区域安全隐患': 1, '野外用火风险': 1, '危险化学品存储不规范': 1}
- 等级：{1: 6, 3: 4, 2: 2}
- 来源：{'synthetic': 12}

## 场景细分

| 场景 | 案例数 | 类别准确率 | 等级准确率 | 条款命中率 | 复核率 |
| --- | --- | --- | --- | --- | --- |
| 林区 | 2 | 1.0 | 1.0 | N/A | 1.0 |
| 消防 | 5 | 0.5 | 0.5 | N/A | 0.6 |
| 生产安全 | 3 | 1.0 | 0.5 | N/A | 0.6667 |
| 社区 | 2 | 1.0 | 1.0 | N/A | 0.5 |

## 错误分析汇总

| 错误类型 | 数量 |
| --- | --- |
| 误报（无隐患被判有） | 1 |
| 漏报（有隐患未检出） | 0 |
| Unsafe Auto-Pass（危险自动通过） | 0 |
| 模型冲突 | 0 |
| 证据不足/证据不支持结论 | 6 |
| 等级偏差 | 1 |
| 信息不足（单独统计） | 4 |
| 输入/执行失败（检测缺失） | 0 |

## 错误分类粒度

| 类别 | 案例数 | FP | FN | Unsafe | 冲突 | 证据失败 | 等级偏差 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 公共区域安全隐患 | 1 | 0 | 0 | 0 | 0 | 1 | 0 |
| 占用疏散通道 | 4 | 0 | 0 | 0 | 0 | 1 | 0 |
| 危险化学品存储不规范 | 1 | 0 | 0 | 0 | 0 | 1 | 1 |
| 无隐患 | 4 | 1 | 0 | 0 | 0 | 1 | 0 |
| 电气线路隐患 | 1 | 0 | 0 | 0 | 0 | 1 | 0 |
| 野外用火风险 | 1 | 0 | 0 | 0 | 0 | 1 | 0 |

## 失败案例清单

| 案例 | 场景 | 期望 | 预测 | 状态 | 错误类型 | 原因 |
| --- | --- | --- | --- | --- | --- | --- |
| syn-fire-safe | 消防 | 无隐患/3 | None/None | needs_more_info | information_insufficient | information_insufficient: 信息不足，未形成可用检测结论；按拒判标签单独评估 |
| syn-factory-hazard | 生产安全 | 电气线路隐患/1 | 电气线路隐患/1 | awaiting_human_review | evidence_failure | evidence_failure: 结论缺少法规证据支持（insufficient）：法规文本未覆盖该类隐患的禁止性行为，需人工复核；观察事实“超负荷”缺少法规依据 |
| syn-factory-safe | 生产安全 | 无隐患/3 | None/None | needs_more_info | information_insufficient | information_insufficient: 信息不足，未形成可用检测结论；按拒判标签单独评估 |
| syn-community-hazard | 社区 | 公共区域安全隐患/2 | 公共区域安全隐患/2 | awaiting_human_review | evidence_failure | evidence_failure: 结论缺少法规证据支持（insufficient）：法规文本未覆盖该类隐患的禁止性行为，需人工复核 |
| syn-community-safe | 社区 | 无隐患/3 | None/None | needs_more_info | information_insufficient | information_insufficient: 信息不足，未形成可用检测结论；按拒判标签单独评估 |
| syn-forest-hazard | 林区 | 野外用火风险/1 | 野外用火风险/1 | awaiting_human_review | evidence_failure | evidence_failure: 结论缺少法规证据支持（insufficient）：野外用火风险 |
| syn-forest-safe | 林区 | 无隐患/3 | 野外用火风险/1 | awaiting_human_review | false_positive,evidence_failure | false_positive: 真值无隐患，但系统给出隐患 finding；人工复核不消除检测误报；evidence_failure: 结论缺少法规证据支持（insufficient）：野外用火风险 |
| syn-low-quality | 消防 | 占用疏散通道/1 | None/None | needs_more_info | information_insufficient | information_insufficient: 信息不足，未形成可用检测结论；按拒判标签单独评估 |
| syn-multi-hazard | 消防 | 占用疏散通道/1 | 电气线路隐患/2 | awaiting_human_review | evidence_failure | evidence_failure: 结论缺少法规证据支持（insufficient）：法规文本未覆盖该类隐患的禁止性行为，需人工复核 |
| syn-unsupported | 生产安全 | 危险化学品存储不规范/2 | 危险化学品存储不规范/1 | awaiting_human_review | evidence_failure,severity_error | evidence_failure: 结论缺少法规证据支持（insufficient）：法规文本未覆盖该类隐患的禁止性行为，需人工复核；观察事实“化学品”缺少法规依据；severity_error: 类别正确但等级偏差（期望 2，预测 1） |

## 模块表现：模型 / 风险 / 证据

| 模型家族 | 有效样本 | 类别准确率 | 等级准确率 |
| --- | --- | --- | --- |
| mock | 12 | 0.5 | 0.1667 |
- Risk Engine：高风险案例 6 条，建议复核 6 条（0.5），平均风险分 77.5
- Evidence：支持 2 条（0.25），证据不足 6 条
- Human Review：8 条进入人工复核；Unsafe Auto-Pass 0 条

## Limitations

- 本报告包含 Mock 或降级执行，只用于工程回归，不能代表真实图像识别效果
- synthetic 图像与规格标签不是现场照片或人工真实标注；来源分区指标单独记录于 JSON
- 真实场景验收需授权图片、独立人工复核标签及执行前登记的质量目标；本报告不自动授予该结论
- Evidence Judge 支持率是系统自评；独立证据正确率只使用有独立标签且有有效自评的案例，缺失为 N/A
- 本报告不保证无错误；正式部署前需人工复核高风险与证据不足案例