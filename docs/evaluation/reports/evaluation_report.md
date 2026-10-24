# 正式评测报告

- 数据集版本：v1（安全隐患多模态研判人工标注评测集）
- 案例数：30；本次运行：30
- 评测模式：auto
- 生成时间：2026-10-24T09:39:06.136477+00:00

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
| 类别准确率 | 0.4 |
| 等级准确率 | 0.6333 |
| 等级 MAE | 0.3667 |
| 等级容差（±1） | 1.0 |
| 法规证据命中率 | 0.8 |
| 证据支持率 | 0.2333 |
| 无依据结论率 | 0.7667 |
| 模型分歧率 | 1.0 |
| 人工复核率 | 1.0 |
| Unsafe Auto-Pass 率 | 0.0 |
| Unsafe Auto-Pass 数 | 0 |
| 平均耗时（秒） | 17.168 |

## 数据集分布

- 类别：{'占用疏散通道': 9, '消防器材失效': 6, '电气线路隐患': 4, '危险化学品存储不规范': 3, '公共区域安全隐患': 3, '野外用火风险': 5}
- 等级：{1: 12, 2: 16, 3: 2}
- 来源：{'curated': 30}

## 场景细分

| 场景 | 案例数 | 类别准确率 | 等级准确率 | 条款命中率 | 复核率 |
| --- | --- | --- | --- | --- | --- |
| 消防 | 10 | 0.7 | 0.8 | 1.0 | 1.0 |
| 生产安全 | 7 | 0.4286 | 0.5714 | 0.5714 | 1.0 |
| 社区 | 7 | 0.2857 | 0.8571 | 0.7143 | 1.0 |
| 林区 | 6 | 0.0 | 0.1667 | 0.8333 | 1.0 |

## 错误分析汇总

| 错误类型 | 数量 |
| --- | --- |
| 误报（无隐患被判有） | 0 |
| 漏报（有隐患未检出） | 0 |
| Unsafe Auto-Pass（危险自动通过） | 0 |
| 模型冲突 | 30 |
| 证据不足/证据不支持结论 | 23 |
| 等级偏差 | 2 |

## 错误分类粒度

| 类别 | 案例数 | FP | FN | Unsafe | 冲突 | 证据失败 | 等级偏差 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 公共区域安全隐患 | 3 | 0 | 0 | 0 | 3 | 3 | 0 |
| 占用疏散通道 | 9 | 0 | 0 | 0 | 9 | 3 | 2 |
| 危险化学品存储不规范 | 3 | 0 | 0 | 0 | 3 | 3 | 0 |
| 消防器材失效 | 6 | 0 | 0 | 0 | 6 | 5 | 0 |
| 电气线路隐患 | 4 | 0 | 0 | 0 | 4 | 4 | 0 |
| 野外用火风险 | 5 | 0 | 0 | 0 | 5 | 5 | 0 |

## 失败案例清单

| 案例 | 场景 | 期望 | 预测 | 状态 | 错误类型 | 原因 |
| --- | --- | --- | --- | --- | --- | --- |
| eval-fire-001 | 消防 | 占用疏散通道/1 | 占用疏散通道/1 | awaiting_human_review | model_conflict | model_conflict: 双模型配置下仅一个模型成功，无法交叉验证 |
| eval-fire-002 | 消防 | 占用疏散通道/1 | 占用疏散通道/1 | awaiting_human_review | model_conflict,evidence_failure | model_conflict: 双模型配置下仅一个模型成功，无法交叉验证；evidence_failure: 结论缺少法规证据支持（insufficient）：法规文本未覆盖该类隐患的禁止性行为，需人工复核 |
| eval-fire-003 | 消防 | 占用疏散通道/2 | 占用疏散通道/1 | awaiting_human_review | model_conflict,severity_error | model_conflict: 双模型配置下仅一个模型成功，无法交叉验证；severity_error: 类别正确但等级偏差（期望 2，预测 1） |
| eval-fire-004 | 消防 | 占用疏散通道/2 | 占用疏散通道/1 | awaiting_human_review | model_conflict,severity_error | model_conflict: 双模型配置下仅一个模型成功，无法交叉验证；severity_error: 类别正确但等级偏差（期望 2，预测 1） |
| eval-fire-005 | 消防 | 消防器材失效/2 | 消防器材失效/2 | awaiting_human_review | model_conflict,evidence_failure | model_conflict: 双模型配置下仅一个模型成功，无法交叉验证；evidence_failure: 结论缺少法规证据支持（insufficient）：观察事实“压力表指针在红区”缺少法规依据 |
| eval-fire-006 | 消防 | 消防器材失效/2 | 消防器材失效/2 | awaiting_human_review | model_conflict | model_conflict: 双模型配置下仅一个模型成功，无法交叉验证 |
| eval-fire-007 | 消防 | 消防器材失效/2 | 消防器材失效/2 | awaiting_human_review | model_conflict,evidence_failure | model_conflict: 双模型配置下仅一个模型成功，无法交叉验证；evidence_failure: 结论缺少法规证据支持（insufficient）：观察事实“缺少水枪”缺少法规依据；法规文本未覆盖该类隐患的禁止性行为，需人工复核 |
| eval-fire-008 | 消防 | 电气线路隐患/2 | 电气火灾风险/2 | awaiting_human_review | model_conflict,evidence_failure | model_conflict: 双模型配置下仅一个模型成功，无法交叉验证；evidence_failure: 结论缺少法规证据支持（insufficient）：法规文本未覆盖该类隐患的禁止性行为，需人工复核 |
| eval-fire-009 | 消防 | 电气线路隐患/2 | 电气安全隐患/2 | awaiting_human_review | model_conflict,evidence_failure | model_conflict: 双模型配置下仅一个模型成功，无法交叉验证；evidence_failure: 结论缺少法规证据支持（insufficient）：法规文本未覆盖该类隐患的禁止性行为，需人工复核；观察事实“配电箱门破损”缺少法规依据 |
| eval-fire-010 | 消防 | 电气线路隐患/2 | 电气火灾风险/2 | awaiting_human_review | model_conflict,evidence_failure | model_conflict: 双模型配置下仅一个模型成功，无法交叉验证；evidence_failure: 结论缺少法规证据支持（insufficient）：法规文本未覆盖该类隐患的禁止性行为，需人工复核；观察事实“电线发烫”缺少法规依据 |
| eval-factory-001 | 生产安全 | 危险化学品存储不规范/1 | 易燃易爆危险品违规存放/2 | awaiting_human_review | model_conflict,evidence_failure | model_conflict: 双模型配置下仅一个模型成功，无法交叉验证；evidence_failure: 结论缺少法规证据支持（insufficient）：法规文本未覆盖该类隐患的禁止性行为，需人工复核；观察事实“无合规标识”缺少法规依据 |
| eval-factory-002 | 生产安全 | 危险化学品存储不规范/1 | 危险化学品存储不规范/1 | awaiting_human_review | model_conflict,evidence_failure | model_conflict: 双模型配置下仅一个模型成功，无法交叉验证；evidence_failure: 结论缺少法规证据支持（insufficient）：危险化学品存储不规范；法规文本未覆盖该类隐患的禁止性行为，需人工复核 |
| eval-factory-003 | 生产安全 | 危险化学品存储不规范/1 | 危险化学品存储不规范/1 | awaiting_human_review | model_conflict,evidence_failure | model_conflict: 双模型配置下仅一个模型成功，无法交叉验证；evidence_failure: 结论缺少法规证据支持（insufficient）：观察事实“明显的气味”缺少法规依据 |
| eval-factory-004 | 生产安全 | 占用疏散通道/1 | 占用疏散通道/1 | awaiting_human_review | model_conflict | model_conflict: 双模型配置下仅一个模型成功，无法交叉验证 |
| eval-factory-005 | 生产安全 | 占用疏散通道/2 | 物品堆积阻碍紧急通道/1 | awaiting_human_review | model_conflict,evidence_failure | model_conflict: 双模型配置下仅一个模型成功，无法交叉验证；evidence_failure: 结论缺少法规证据支持（insufficient）：法规文本未覆盖该类隐患的禁止性行为，需人工复核 |
| eval-factory-006 | 生产安全 | 消防器材失效/2 | 物品堆积/2 | awaiting_human_review | model_conflict,evidence_failure | model_conflict: 双模型配置下仅一个模型成功，无法交叉验证；evidence_failure: 结论缺少法规证据支持（insufficient）：法规文本未覆盖该类隐患的禁止性行为，需人工复核；观察事实“配电房内有大量杂物堆积”缺少法规依据 |
| eval-factory-007 | 生产安全 | 公共区域安全隐患/3 | 道路安全隐患/2 | awaiting_human_review | model_conflict,evidence_failure | model_conflict: 双模型配置下仅一个模型成功，无法交叉验证；evidence_failure: 结论缺少法规证据支持（insufficient）：法规文本未覆盖该类隐患的禁止性行为，需人工复核 |
| eval-community-001 | 社区 | 电气线路隐患/2 | 电气火灾风险/2 | awaiting_human_review | model_conflict,evidence_failure | model_conflict: 双模型配置下仅一个模型成功，无法交叉验证；evidence_failure: 结论缺少法规证据支持（insufficient）：法规文本未覆盖该类隐患的禁止性行为，需人工复核；观察事实“电线暴露在外部环境中，存在短路或过载的风险”缺少法规依据 |
| eval-community-002 | 社区 | 消防器材失效/2 | 设备老化/2 | awaiting_human_review | model_conflict,evidence_failure | model_conflict: 双模型配置下仅一个模型成功，无法交叉验证；evidence_failure: 结论缺少法规证据支持（insufficient）：法规文本未覆盖该类隐患的禁止性行为，需人工复核 |
| eval-community-003 | 社区 | 占用疏散通道/1 | 占用疏散通道/1 | awaiting_human_review | model_conflict | model_conflict: 双模型配置下仅一个模型成功，无法交叉验证 |
| eval-community-004 | 社区 | 公共区域安全隐患/2 | 基础设施损坏/2 | awaiting_human_review | model_conflict,evidence_failure | model_conflict: 双模型配置下仅一个模型成功，无法交叉验证；evidence_failure: 结论缺少法规证据支持（insufficient）：法规文本未覆盖该类隐患的禁止性行为，需人工复核；观察事实“井盖有明显裂缝和缺失部分。”缺少法规依据 |
| eval-community-005 | 社区 | 占用疏散通道/2 | 易燃物质/2 | awaiting_human_review | model_conflict,evidence_failure | model_conflict: 双模型配置下仅一个模型成功，无法交叉验证；evidence_failure: 结论缺少法规证据支持（insufficient）：法规文本未覆盖该类隐患的禁止性行为，需人工复核 |
| eval-community-006 | 社区 | 公共区域安全隐患/3 | 结构稳定性问题/2 | awaiting_human_review | model_conflict,evidence_failure | model_conflict: 双模型配置下仅一个模型成功，无法交叉验证；evidence_failure: 结论缺少法规证据支持（insufficient）：法规文本未覆盖该类隐患的禁止性行为，需人工复核；观察事实“护栏表面出现明显锈迹”缺少法规依据 |
| eval-community-007 | 社区 | 占用疏散通道/1 | 占用疏散通道/1 | awaiting_human_review | model_conflict | model_conflict: 双模型配置下仅一个模型成功，无法交叉验证 |
| eval-forest-001 | 林区 | 野外用火风险/1 | 火灾隐患/2 | awaiting_human_review | model_conflict,evidence_failure | model_conflict: 双模型配置下仅一个模型成功，无法交叉验证；evidence_failure: 结论缺少法规证据支持（insufficient）：法规文本未覆盖该类隐患的禁止性行为，需人工复核 |
| eval-forest-002 | 林区 | 野外用火风险/1 | 火灾隐患/2 | awaiting_human_review | model_conflict,evidence_failure | model_conflict: 双模型配置下仅一个模型成功，无法交叉验证；evidence_failure: 结论缺少法规证据支持（insufficient）：法规文本未覆盖该类隐患的禁止性行为，需人工复核 |
| eval-forest-003 | 林区 | 野外用火风险/1 | 火灾风险/2 | awaiting_human_review | model_conflict,evidence_failure | model_conflict: 双模型配置下仅一个模型成功，无法交叉验证；evidence_failure: 结论缺少法规证据支持（insufficient）：法规文本未覆盖该类隐患的禁止性行为，需人工复核；观察事实“烟头被随意丢弃”缺少法规依据 |
| eval-forest-004 | 林区 | 野外用火风险/2 | 易燃物堆积/1 | awaiting_human_review | model_conflict,evidence_failure | model_conflict: 双模型配置下仅一个模型成功，无法交叉验证；evidence_failure: 结论缺少法规证据支持（insufficient）：法规文本未覆盖该类隐患的禁止性行为，需人工复核 |
| eval-forest-005 | 林区 | 野外用火风险/1 | 火灾风险/2 | awaiting_human_review | model_conflict,evidence_failure | model_conflict: 双模型配置下仅一个模型成功，无法交叉验证；evidence_failure: 结论缺少法规证据支持（insufficient）：法规文本未覆盖该类隐患的禁止性行为，需人工复核 |
| eval-forest-006 | 林区 | 消防器材失效/2 | 设备故障/2 | awaiting_human_review | model_conflict,evidence_failure | model_conflict: 双模型配置下仅一个模型成功，无法交叉验证；evidence_failure: 结论缺少法规证据支持（insufficient）：法规文本未覆盖该类隐患的禁止性行为，需人工复核 |

## 模块表现：模型 / 风险 / 证据

| 模型家族 | 有效样本 | 类别准确率 | 等级准确率 |
| --- | --- | --- | --- |
| glm-v | 30 | 0.0 | 0.0 |
- Risk Engine：高风险案例 11 条，建议复核 28 条（0.9333），平均风险分 66.07
- Evidence：支持 7 条（0.2333），证据不足 23 条
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