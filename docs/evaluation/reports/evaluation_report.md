# 正式评测报告

- 数据集版本：v1（安全隐患多模态研判人工标注评测集）
- 案例数：60；本次运行：60
- 评测模式：mock
- 生成时间：2026-10-24T09:44:26.447773+00:00

## Dataset Overview

- 案例数：60，来源：{"curated": 60}
- 类别分布：{"占用疏散通道": 9, "消防器材失效": 16, "电气线路隐患": 14, "危险化学品存储不规范": 3, "公共区域安全隐患": 13, "野外用火风险": 5}
- 等级分布：{"1": 22, "2": 34, "3": 4}
- 场景分布：{"林区": 6, "消防": 20, "生产安全": 10, "社区": 24}
- 有隐患样本：60；无隐患负样本：0
- 含图片案例：0；标注 expected_evidence_supported：0

## 总体指标

| 指标 | 数值 |
| --- | --- |
| 类别准确率 | 0.7667 |
| 等级准确率 | 0.5167 |
| 等级 MAE | 0.4259 |
| 等级容差（±1） | 0.9 |
| 法规证据命中率 | 0.45 |
| 证据支持率 | 0.1333 |
| 无依据结论率 | 0.7667 |
| 模型分歧率 | 0.0 |
| 人工复核率 | 0.9 |
| Unsafe Auto-Pass 率 | 0.0 |
| Unsafe Auto-Pass 数 | 0 |
| 平均耗时（秒） | 0.008 |

## 数据集分布

- 类别：{'占用疏散通道': 9, '消防器材失效': 16, '电气线路隐患': 14, '危险化学品存储不规范': 3, '公共区域安全隐患': 13, '野外用火风险': 5}
- 等级：{1: 22, 2: 34, 3: 4}
- 来源：{'curated': 60}

## 场景细分

| 场景 | 案例数 | 类别准确率 | 等级准确率 | 条款命中率 | 复核率 |
| --- | --- | --- | --- | --- | --- |
| 消防 | 20 | 0.75 | 0.55 | 0.6 | 0.9 |
| 生产安全 | 10 | 0.8 | 0.5 | 0.4 | 0.9 |
| 社区 | 24 | 0.7083 | 0.4167 | 0.2083 | 0.875 |
| 林区 | 6 | 1.0 | 0.8333 | 1.0 | 1.0 |

## 错误分析汇总

| 错误类型 | 数量 |
| --- | --- |
| 误报（无隐患被判有） | 0 |
| 漏报（有隐患未检出） | 6 |
| Unsafe Auto-Pass（危险自动通过） | 0 |
| 模型冲突 | 0 |
| 证据不足/证据不支持结论 | 46 |
| 等级偏差 | 17 |

## 错误分类粒度

| 类别 | 案例数 | FP | FN | Unsafe | 冲突 | 证据失败 | 等级偏差 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 公共区域安全隐患 | 13 | 0 | 2 | 0 | 0 | 11 | 5 |
| 占用疏散通道 | 9 | 0 | 0 | 0 | 0 | 4 | 4 |
| 危险化学品存储不规范 | 3 | 0 | 0 | 0 | 0 | 3 | 0 |
| 消防器材失效 | 16 | 0 | 2 | 0 | 0 | 11 | 2 |
| 电气线路隐患 | 14 | 0 | 2 | 0 | 0 | 12 | 5 |
| 野外用火风险 | 5 | 0 | 0 | 0 | 0 | 5 | 1 |

## 失败案例清单

| 案例 | 场景 | 期望 | 预测 | 状态 | 错误类型 | 原因 |
| --- | --- | --- | --- | --- | --- | --- |
| eval-fire-003 | 消防 | 占用疏散通道/2 | 占用疏散通道/1 | awaiting_human_review | evidence_failure,severity_error | evidence_failure: 结论缺少法规证据支持（insufficient）：占用疏散通道；severity_error: 类别正确但等级偏差（期望 2，预测 1） |
| eval-fire-004 | 消防 | 占用疏散通道/2 | 占用疏散通道/1 | awaiting_human_review | evidence_failure,severity_error | evidence_failure: 结论缺少法规证据支持（insufficient）：占用疏散通道；severity_error: 类别正确但等级偏差（期望 2，预测 1） |
| eval-fire-005 | 消防 | 消防器材失效/2 | 消防器材失效/2 | awaiting_human_review | evidence_failure | evidence_failure: 结论缺少法规证据支持（insufficient）：观察事实“压力表”缺少法规依据 |
| eval-fire-007 | 消防 | 消防器材失效/2 | 消防器材失效/2 | awaiting_human_review | evidence_failure | evidence_failure: 结论缺少法规证据支持（insufficient）：消防器材失效 |
| eval-fire-008 | 消防 | 电气线路隐患/2 | 电气线路隐患/2 | awaiting_human_review | evidence_failure | evidence_failure: 结论缺少法规证据支持（insufficient）：法规文本未覆盖该类隐患的禁止性行为，需人工复核 |
| eval-fire-009 | 消防 | 电气线路隐患/2 | 电气线路隐患/2 | awaiting_human_review | evidence_failure | evidence_failure: 结论缺少法规证据支持（insufficient）：法规文本未覆盖该类隐患的禁止性行为，需人工复核；观察事实“配电箱”缺少法规依据 |
| eval-fire-010 | 消防 | 电气线路隐患/2 | 电气线路隐患/2 | awaiting_human_review | evidence_failure | evidence_failure: 结论缺少法规证据支持（insufficient）：法规文本未覆盖该类隐患的禁止性行为，需人工复核；观察事实“超负荷”缺少法规依据 |
| eval-factory-001 | 生产安全 | 危险化学品存储不规范/1 | 危险化学品存储不规范/1 | awaiting_human_review | evidence_failure | evidence_failure: 结论缺少法规证据支持（insufficient）：法规文本未覆盖该类隐患的禁止性行为，需人工复核；观察事实“危化品”缺少法规依据 |
| eval-factory-002 | 生产安全 | 危险化学品存储不规范/1 | 危险化学品存储不规范/1 | awaiting_human_review | evidence_failure | evidence_failure: 结论缺少法规证据支持（insufficient）：法规文本未覆盖该类隐患的禁止性行为，需人工复核 |
| eval-factory-003 | 生产安全 | 危险化学品存储不规范/1 | 危险化学品存储不规范/1 | awaiting_human_review | evidence_failure | evidence_failure: 结论缺少法规证据支持（insufficient）：法规文本未覆盖该类隐患的禁止性行为，需人工复核 |
| eval-factory-005 | 生产安全 | 占用疏散通道/2 | 占用疏散通道/1 | awaiting_human_review | evidence_failure,severity_error | evidence_failure: 结论缺少法规证据支持（insufficient）：占用疏散通道；severity_error: 类别正确但等级偏差（期望 2，预测 1） |
| eval-factory-006 | 生产安全 | 消防器材失效/2 | 消防器材失效/2 | awaiting_human_review | evidence_failure | evidence_failure: 结论缺少法规证据支持（insufficient）：消防器材失效 |
| eval-factory-007 | 生产安全 | 公共区域安全隐患/3 | 公共区域安全隐患/2 | awaiting_human_review | evidence_failure,severity_error | evidence_failure: 结论缺少法规证据支持（insufficient）：法规文本未覆盖该类隐患的禁止性行为，需人工复核；severity_error: 类别正确但等级偏差（期望 3，预测 2） |
| eval-community-001 | 社区 | 电气线路隐患/2 | 电气线路隐患/1 | awaiting_human_review | evidence_failure,severity_error | evidence_failure: 结论缺少法规证据支持（insufficient）：法规文本未覆盖该类隐患的禁止性行为，需人工复核；观察事实“电表箱”缺少法规依据；severity_error: 类别正确但等级偏差（期望 2，预测 1） |
| eval-community-002 | 社区 | 消防器材失效/2 | 消防器材失效/2 | awaiting_human_review | evidence_failure | evidence_failure: 结论缺少法规证据支持（insufficient）：消防器材失效 |
| eval-community-004 | 社区 | 公共区域安全隐患/2 | 公共区域安全隐患/2 | awaiting_human_review | evidence_failure | evidence_failure: 结论缺少法规证据支持（insufficient）：法规文本未覆盖该类隐患的禁止性行为，需人工复核 |
| eval-community-005 | 社区 | 占用疏散通道/2 | 占用疏散通道/1 | awaiting_human_review | evidence_failure,severity_error | evidence_failure: 结论缺少法规证据支持（insufficient）：占用疏散通道；severity_error: 类别正确但等级偏差（期望 2，预测 1） |
| eval-community-006 | 社区 | 公共区域安全隐患/3 | 公共区域安全隐患/2 | awaiting_human_review | evidence_failure,severity_error | evidence_failure: 结论缺少法规证据支持（insufficient）：法规文本未覆盖该类隐患的禁止性行为，需人工复核；severity_error: 类别正确但等级偏差（期望 3，预测 2） |
| eval-forest-001 | 林区 | 野外用火风险/1 | 野外用火风险/1 | awaiting_human_review | evidence_failure | evidence_failure: 结论缺少法规证据支持（insufficient）：野外用火风险 |
| eval-forest-002 | 林区 | 野外用火风险/1 | 野外用火风险/1 | awaiting_human_review | evidence_failure | evidence_failure: 结论缺少法规证据支持（insufficient）：野外用火风险 |
| eval-forest-003 | 林区 | 野外用火风险/1 | 野外用火风险/1 | awaiting_human_review | evidence_failure | evidence_failure: 结论缺少法规证据支持（insufficient）：野外用火风险 |
| eval-forest-004 | 林区 | 野外用火风险/2 | 野外用火风险/1 | awaiting_human_review | evidence_failure,severity_error | evidence_failure: 结论缺少法规证据支持（insufficient）：野外用火风险；severity_error: 类别正确但等级偏差（期望 2，预测 1） |
| eval-forest-005 | 林区 | 野外用火风险/1 | 野外用火风险/1 | awaiting_human_review | evidence_failure | evidence_failure: 结论缺少法规证据支持（insufficient）：野外用火风险 |
| eval-forest-006 | 林区 | 消防器材失效/2 | 消防器材失效/2 | awaiting_human_review | evidence_failure | evidence_failure: 结论缺少法规证据支持（insufficient）：消防器材失效 |
| eval-fire-ext-001 | 消防 | 消防器材失效/1 | 消防器材失效/2 | awaiting_human_review | evidence_failure,severity_error | evidence_failure: 结论缺少法规证据支持（insufficient）：观察事实“压力表”缺少法规依据；severity_error: 类别正确但等级偏差（期望 1，预测 2） |
| eval-fire-ext-002 | 消防 | 消防器材失效/1 | 消防器材失效/2 | awaiting_human_review | evidence_failure,severity_error | evidence_failure: 结论缺少法规证据支持（insufficient）：消防器材失效；severity_error: 类别正确但等级偏差（期望 1，预测 2） |
| eval-fire-ext-003 | 消防 | 消防器材失效/2 | 占用疏散通道/1 | awaiting_human_review | evidence_failure | evidence_failure: 结论缺少法规证据支持（insufficient）：占用疏散通道 |
| eval-fire-ext-004 | 消防 | 消防器材失效/1 | None/None | needs_more_info | false_negative | false_negative: 真值存在隐患，系统未检出（已拦截或复核） |
| eval-fire-ext-005 | 消防 | 消防器材失效/2 | 消防器材失效/2 | awaiting_human_review | evidence_failure | evidence_failure: 结论缺少法规证据支持（insufficient）：法规文本未覆盖该类隐患的禁止性行为，需人工复核 |
| eval-fire-ext-007 | 消防 | 消防器材失效/2 | None/None | needs_more_info | false_negative | false_negative: 真值存在隐患，系统未检出（已拦截或复核） |
| eval-fire-ext-008 | 消防 | 消防器材失效/2 | 消防器材失效/2 | awaiting_human_review | evidence_failure | evidence_failure: 结论缺少法规证据支持（insufficient）：消防器材失效 |
| eval-fire-ext-010 | 消防 | 消防器材失效/2 | 消防器材失效/2 | awaiting_human_review | evidence_failure | evidence_failure: 结论缺少法规证据支持（insufficient）：消防器材失效 |
| eval-public-001 | 社区 | 公共区域安全隐患/1 | 公共区域安全隐患/2 | awaiting_human_review | evidence_failure,severity_error | evidence_failure: 结论缺少法规证据支持（insufficient）：法规文本未覆盖该类隐患的禁止性行为，需人工复核；severity_error: 类别正确但等级偏差（期望 1，预测 2） |
| eval-public-002 | 社区 | 公共区域安全隐患/3 | 公共区域安全隐患/2 | awaiting_human_review | evidence_failure,severity_error | evidence_failure: 结论缺少法规证据支持（insufficient）：法规文本未覆盖该类隐患的禁止性行为，需人工复核；severity_error: 类别正确但等级偏差（期望 3，预测 2） |
| eval-public-003 | 社区 | 公共区域安全隐患/1 | None/None | needs_more_info | false_negative | false_negative: 真值存在隐患，系统未检出（已拦截或复核） |
| eval-public-004 | 社区 | 公共区域安全隐患/2 | None/None | needs_more_info | false_negative | false_negative: 真值存在隐患，系统未检出（已拦截或复核） |
| eval-public-005 | 社区 | 公共区域安全隐患/2 | 公共区域安全隐患/2 | awaiting_human_review | evidence_failure | evidence_failure: 结论缺少法规证据支持（insufficient）：法规文本未覆盖该类隐患的禁止性行为，需人工复核 |
| eval-public-006 | 社区 | 公共区域安全隐患/2 | 公共区域安全隐患/2 | awaiting_human_review | evidence_failure | evidence_failure: 结论缺少法规证据支持（insufficient）：法规文本未覆盖该类隐患的禁止性行为，需人工复核 |
| eval-public-007 | 社区 | 公共区域安全隐患/3 | 公共区域安全隐患/2 | awaiting_human_review | evidence_failure,severity_error | evidence_failure: 结论缺少法规证据支持（insufficient）：法规文本未覆盖该类隐患的禁止性行为，需人工复核；severity_error: 类别正确但等级偏差（期望 3，预测 2） |
| eval-public-008 | 社区 | 公共区域安全隐患/2 | 消防器材失效/2 | awaiting_human_review | evidence_failure | evidence_failure: 结论缺少法规证据支持（insufficient）：消防器材失效 |
| eval-public-009 | 社区 | 公共区域安全隐患/1 | 消防器材失效/2 | awaiting_human_review | evidence_failure | evidence_failure: 结论缺少法规证据支持（insufficient）：法规文本未覆盖该类隐患的禁止性行为，需人工复核 |
| eval-public-010 | 社区 | 公共区域安全隐患/2 | 占用疏散通道/1 | awaiting_human_review | evidence_failure | evidence_failure: 结论缺少法规证据支持（insufficient）：占用疏散通道 |
| eval-electric-001 | 社区 | 电气线路隐患/1 | 电气线路隐患/1 | awaiting_human_review | evidence_failure | evidence_failure: 结论缺少法规证据支持（insufficient）：法规文本未覆盖该类隐患的禁止性行为，需人工复核 |
| eval-electric-002 | 社区 | 电气线路隐患/1 | 电气线路隐患/2 | awaiting_human_review | evidence_failure,severity_error | evidence_failure: 结论缺少法规证据支持（insufficient）：法规文本未覆盖该类隐患的禁止性行为，需人工复核；观察事实“配电箱”缺少法规依据；severity_error: 类别正确但等级偏差（期望 1，预测 2） |
| eval-electric-003 | 社区 | 电气线路隐患/2 | 电气线路隐患/1 | awaiting_human_review | evidence_failure,severity_error | evidence_failure: 结论缺少法规证据支持（insufficient）：法规文本未覆盖该类隐患的禁止性行为，需人工复核；severity_error: 类别正确但等级偏差（期望 2，预测 1） |
| eval-electric-004 | 生产安全 | 电气线路隐患/2 | None/None | needs_more_info | false_negative | false_negative: 真值存在隐患，系统未检出（已拦截或复核） |
| eval-electric-005 | 社区 | 电气线路隐患/1 | 电气线路隐患/1 | awaiting_human_review | evidence_failure | evidence_failure: 结论缺少法规证据支持（insufficient）：法规文本未覆盖该类隐患的禁止性行为，需人工复核 |
| eval-electric-006 | 生产安全 | 电气线路隐患/2 | 电气线路隐患/1 | awaiting_human_review | evidence_failure,severity_error | evidence_failure: 结论缺少法规证据支持（insufficient）：法规文本未覆盖该类隐患的禁止性行为，需人工复核；severity_error: 类别正确但等级偏差（期望 2，预测 1） |
| eval-electric-007 | 社区 | 电气线路隐患/2 | 电气线路隐患/1 | awaiting_human_review | evidence_failure,severity_error | evidence_failure: 结论缺少法规证据支持（insufficient）：法规文本未覆盖该类隐患的禁止性行为，需人工复核；severity_error: 类别正确但等级偏差（期望 2，预测 1） |
| eval-electric-008 | 社区 | 电气线路隐患/2 | None/None | needs_more_info | false_negative | false_negative: 真值存在隐患，系统未检出（已拦截或复核） |
| eval-electric-009 | 生产安全 | 电气线路隐患/1 | 公共区域安全隐患/2 | awaiting_human_review | evidence_failure | evidence_failure: 结论缺少法规证据支持（insufficient）：公共区域安全隐患 |
| eval-electric-010 | 社区 | 电气线路隐患/2 | 公共区域安全隐患/2 | awaiting_human_review | evidence_failure | evidence_failure: 结论缺少法规证据支持（insufficient）：法规文本未覆盖该类隐患的禁止性行为，需人工复核 |

## 模块表现：模型 / 风险 / 证据

| 模型家族 | 有效样本 | 类别准确率 | 等级准确率 |
| --- | --- | --- | --- |
| mock | 60 | 0.0 | 0.0 |
- Risk Engine：高风险案例 27 条，建议复核 27 条（0.45），平均风险分 64.53
- Evidence：支持 8 条（0.1333），证据不足 46 条
- Human Review：54 条进入人工复核；Unsafe Auto-Pass 0 条

## Ablation Study（独立消融运行）

| 变体 | 类别 | 等级 | UA-P |
| --- | --- | --- | --- |
| Qwen only | 1.0 | 0.0 | 0.0 |
| GLM only | 1.0 | 0.0 | 0.0 |
| Qwen+GLM | 1.0 | 0.0 | 0.0 |
| Qwen+GLM+Risk | 1.0 | 0.7333 | 0.0 |
| Qwen+GLM+Risk+RAG | 1.0 | 0.7333 | 0.0 |
| Full system | 1.0 | 0.7333 | 0.0 |
说明：消融结果在独立运行时生成，仅供横向比较，不改变本次单变体结论。

## Limitations

- 当前数据集缺少无隐患负样本，FP 与正确自动通过能力无法完整评估
- 当前数据集全部为文本场景，尚未验证真实图片输入链路
- 未标注 expected_evidence_supported，证据支持率按系统 Evidence Judge 结果统计
- 模型输出未经过真实场景图片评测，文本场景仅覆盖当前知识库范围
- 法规证据支持率以系统 Evidence Judge 为准，存在知识库覆盖不足时结果偏保守
- 本报告不保证无错误；正式部署前需人工复核高风险与证据不足案例