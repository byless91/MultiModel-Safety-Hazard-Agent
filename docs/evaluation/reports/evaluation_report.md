# 正式评测报告

- 数据集版本：v1（安全隐患多模态研判人工标注评测集）
- 案例数：30；本次运行：30
- 评测模式：mock
- 生成时间：2026-09-10T12:20:32.254113+00:00

## Dataset Overview

- 案例数：30，来源：{"curated": 30}
- 类别分布：{"占用疏散通道": 9, "消防器材失效": 6, "电气线路隐患": 4, "危险化学品存储不规范": 3, "公共区域安全隐患": 3, "野外用火风险": 5}
- 等级分布：{"1": 12, "2": 16, "3": 2}
- 场景分布：{"林区": 6, "消防": 10, "生产安全": 7, "社区": 7}
- 有隐患样本：30；无隐患负样本：0
- 含图片案例：0；标注 expected_evidence_supported：0

## 总体指标

| 指标 | 数值 |
| --- | --- |
| 类别准确率 | 1.0 |
| 等级准确率 | 0.7333 |
| 等级 MAE | 0.2667 |
| 等级容差（±1） | 1.0 |
| 法规证据命中率 | 0.4 |
| 证据支持率 | 0.2667 |
| 无依据结论率 | 0.7667 |
| 模型分歧率 | 0.0 |
| 人工复核率 | 1.0 |
| Unsafe Auto-Pass 率 | 0.0 |
| Unsafe Auto-Pass 数 | 0 |
| 平均耗时（秒） | 0.001 |

## 数据集分布

- 类别：{'占用疏散通道': 9, '消防器材失效': 6, '电气线路隐患': 4, '危险化学品存储不规范': 3, '公共区域安全隐患': 3, '野外用火风险': 5}
- 等级：{1: 12, 2: 16, 3: 2}
- 来源：{'curated': 30}

## 场景细分

| 场景 | 案例数 | 类别准确率 | 等级准确率 | 条款命中率 | 复核率 |
| --- | --- | --- | --- | --- | --- |
| 消防 | 10 | 1.0 | 0.8 | 0.4 | 1.0 |
| 生产安全 | 7 | 1.0 | 0.7143 | 0.2857 | 1.0 |
| 社区 | 7 | 1.0 | 0.5714 | 0.5714 | 1.0 |
| 林区 | 6 | 1.0 | 0.8333 | 0.3333 | 1.0 |

## 错误分析汇总

| 错误类型 | 数量 |
| --- | --- |
| 误报（无隐患被判有） | 0 |
| 漏报（有隐患未检出） | 0 |
| Unsafe Auto-Pass（危险自动通过） | 0 |
| 模型冲突 | 0 |
| 证据不足/证据不支持结论 | 22 |
| 等级偏差 | 8 |

## 错误分类粒度

| 类别 | 案例数 | FP | FN | Unsafe | 冲突 | 证据失败 | 等级偏差 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 公共区域安全隐患 | 3 | 0 | 0 | 0 | 0 | 3 | 2 |
| 占用疏散通道 | 9 | 0 | 0 | 0 | 0 | 1 | 4 |
| 危险化学品存储不规范 | 3 | 0 | 0 | 0 | 0 | 3 | 0 |
| 消防器材失效 | 6 | 0 | 0 | 0 | 0 | 6 | 0 |
| 电气线路隐患 | 4 | 0 | 0 | 0 | 0 | 4 | 1 |
| 野外用火风险 | 5 | 0 | 0 | 0 | 0 | 5 | 1 |

## 失败案例清单

| 案例 | 场景 | 期望 | 预测 | 状态 | 错误类型 | 原因 |
| --- | --- | --- | --- | --- | --- | --- |
| eval-fire-003 | 消防 | 占用疏散通道/2 | 占用疏散通道/1 | awaiting_human_review | severity_error | severity_error: 类别正确但等级偏差（期望 2，预测 1） |
| eval-fire-004 | 消防 | 占用疏散通道/2 | 占用疏散通道/1 | awaiting_human_review | evidence_failure,severity_error | evidence_failure: 结论缺少法规证据支持（insufficient）：占用疏散通道；severity_error: 类别正确但等级偏差（期望 2，预测 1） |
| eval-fire-005 | 消防 | 消防器材失效/2 | 消防器材失效/2 | awaiting_human_review | evidence_failure | evidence_failure: 结论缺少法规证据支持（insufficient）：法规文本未覆盖该类隐患的禁止性行为，需人工复核；观察事实“灭火器”缺少法规依据 |
| eval-fire-006 | 消防 | 消防器材失效/2 | 消防器材失效/2 | awaiting_human_review | evidence_failure | evidence_failure: 结论缺少法规证据支持（insufficient）：法规文本未覆盖该类隐患的禁止性行为，需人工复核；观察事实“灭火器”缺少法规依据 |
| eval-fire-007 | 消防 | 消防器材失效/2 | 消防器材失效/2 | awaiting_human_review | evidence_failure | evidence_failure: 结论缺少法规证据支持（insufficient）：法规文本未覆盖该类隐患的禁止性行为，需人工复核；观察事实“消防栓”缺少法规依据 |
| eval-fire-008 | 消防 | 电气线路隐患/2 | 电气线路隐患/2 | awaiting_human_review | evidence_failure | evidence_failure: 结论缺少法规证据支持（insufficient）：法规文本未覆盖该类隐患的禁止性行为，需人工复核 |
| eval-fire-009 | 消防 | 电气线路隐患/2 | 电气线路隐患/2 | awaiting_human_review | evidence_failure | evidence_failure: 结论缺少法规证据支持（insufficient）：法规文本未覆盖该类隐患的禁止性行为，需人工复核；观察事实“配电箱”缺少法规依据 |
| eval-fire-010 | 消防 | 电气线路隐患/2 | 电气线路隐患/2 | awaiting_human_review | evidence_failure | evidence_failure: 结论缺少法规证据支持（insufficient）：法规文本未覆盖该类隐患的禁止性行为，需人工复核；观察事实“超负荷”缺少法规依据 |
| eval-factory-001 | 生产安全 | 危险化学品存储不规范/1 | 危险化学品存储不规范/1 | awaiting_human_review | evidence_failure | evidence_failure: 结论缺少法规证据支持（insufficient）：法规文本未覆盖该类隐患的禁止性行为，需人工复核；观察事实“危化品”缺少法规依据 |
| eval-factory-002 | 生产安全 | 危险化学品存储不规范/1 | 危险化学品存储不规范/1 | awaiting_human_review | evidence_failure | evidence_failure: 结论缺少法规证据支持（insufficient）：法规文本未覆盖该类隐患的禁止性行为，需人工复核 |
| eval-factory-003 | 生产安全 | 危险化学品存储不规范/1 | 危险化学品存储不规范/1 | awaiting_human_review | evidence_failure | evidence_failure: 结论缺少法规证据支持（insufficient）：法规文本未覆盖该类隐患的禁止性行为，需人工复核 |
| eval-factory-005 | 生产安全 | 占用疏散通道/2 | 占用疏散通道/1 | awaiting_human_review | severity_error | severity_error: 类别正确但等级偏差（期望 2，预测 1） |
| eval-factory-006 | 生产安全 | 消防器材失效/2 | 消防器材失效/2 | awaiting_human_review | evidence_failure | evidence_failure: 结论缺少法规证据支持（insufficient）：法规文本未覆盖该类隐患的禁止性行为，需人工复核；观察事实“灭火器”缺少法规依据 |
| eval-factory-007 | 生产安全 | 公共区域安全隐患/3 | 公共区域安全隐患/2 | awaiting_human_review | evidence_failure,severity_error | evidence_failure: 结论缺少法规证据支持（insufficient）：法规文本未覆盖该类隐患的禁止性行为，需人工复核；severity_error: 类别正确但等级偏差（期望 3，预测 2） |
| eval-community-001 | 社区 | 电气线路隐患/2 | 电气线路隐患/1 | awaiting_human_review | evidence_failure,severity_error | evidence_failure: 结论缺少法规证据支持（insufficient）：法规文本未覆盖该类隐患的禁止性行为，需人工复核；观察事实“电表箱”缺少法规依据；severity_error: 类别正确但等级偏差（期望 2，预测 1） |
| eval-community-002 | 社区 | 消防器材失效/2 | 消防器材失效/2 | awaiting_human_review | evidence_failure | evidence_failure: 结论缺少法规证据支持（insufficient）：消防器材失效 |
| eval-community-004 | 社区 | 公共区域安全隐患/2 | 公共区域安全隐患/2 | awaiting_human_review | evidence_failure | evidence_failure: 结论缺少法规证据支持（insufficient）：法规文本未覆盖该类隐患的禁止性行为，需人工复核 |
| eval-community-005 | 社区 | 占用疏散通道/2 | 占用疏散通道/1 | awaiting_human_review | severity_error | severity_error: 类别正确但等级偏差（期望 2，预测 1） |
| eval-community-006 | 社区 | 公共区域安全隐患/3 | 公共区域安全隐患/2 | awaiting_human_review | evidence_failure,severity_error | evidence_failure: 结论缺少法规证据支持（insufficient）：法规文本未覆盖该类隐患的禁止性行为，需人工复核；severity_error: 类别正确但等级偏差（期望 3，预测 2） |
| eval-forest-001 | 林区 | 野外用火风险/1 | 野外用火风险/1 | awaiting_human_review | evidence_failure | evidence_failure: 结论缺少法规证据支持（insufficient）：野外用火风险 |
| eval-forest-002 | 林区 | 野外用火风险/1 | 野外用火风险/1 | awaiting_human_review | evidence_failure | evidence_failure: 结论缺少法规证据支持（insufficient）：野外用火风险 |
| eval-forest-003 | 林区 | 野外用火风险/1 | 野外用火风险/1 | awaiting_human_review | evidence_failure | evidence_failure: 结论缺少法规证据支持（insufficient）：野外用火风险 |
| eval-forest-004 | 林区 | 野外用火风险/2 | 野外用火风险/1 | awaiting_human_review | evidence_failure,severity_error | evidence_failure: 结论缺少法规证据支持（insufficient）：野外用火风险；severity_error: 类别正确但等级偏差（期望 2，预测 1） |
| eval-forest-005 | 林区 | 野外用火风险/1 | 野外用火风险/1 | awaiting_human_review | evidence_failure | evidence_failure: 结论缺少法规证据支持（insufficient）：野外用火风险 |
| eval-forest-006 | 林区 | 消防器材失效/2 | 消防器材失效/2 | awaiting_human_review | evidence_failure | evidence_failure: 结论缺少法规证据支持（insufficient）：消防器材失效 |

## 模块表现：模型 / 风险 / 证据

| 模型家族 | 有效样本 | 类别准确率 | 等级准确率 |
| --- | --- | --- | --- |
| mock | 30 | 0.0 | 0.0 |
- Risk Engine：高风险案例 18 条，建议复核 18 条（0.6），平均风险分 76.17
- Evidence：支持 8 条（0.2667），证据不足 22 条
- Human Review：30 条进入人工复核；Unsafe Auto-Pass 0 条

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