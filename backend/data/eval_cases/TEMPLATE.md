# 评测数据集模板说明

评测数据位于本目录的 `cases.jsonl`，当前版本 `v1`（30 条）。新增案例时按照
下面字段添加到该文件，或按照同构 JSONL 新建版本文件（例如
`v2_cases.jsonl`）。不要删除、改编号既有案例。

## 字段说明

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| id | 是 | 全局唯一 case_id，字母/数字/_/-，如 `eval-fire-101` |
| scenario | 是 | 场景：消防、生产安全、社区、林区、交通、其他 |
| description | 是 | 发给模型的现场描述 |
| expected_category | 是 | 真值隐患类别（系统标准类别，见 `KNOWN_CATEGORIES`） |
| expected_level | 是 | 真值风险等级，1=最高风险，2=中，3=较低 |
| expected_clause_terms | 否 | 真值法规证据中应包含的条款关键词 |
| expected_source | 否 | 期望命中的法规/条款，如“消防法第二十八条” |
| ground_truth_hazard_present | 否 | 真值是否存在隐患，默认 true；无隐患样本必须显式写 false |
| expected_review_required | 否 | 真值是否应进入人工复核，默认与存在隐患一致 |
| expected_evidence_supported | 否 | 真值法规证据是否应当支持结论；null=未知/不判定 |
| user_text | 否 | 模拟用户补充文字（对应追问），无则为空 |
| image_paths | 否 | 图片相对/绝对路径列表；纯文本评测用例为空 |
| expected_hazard | 否 | 隐患的人工自然语言描述（供错误分析） |
| expected_regulation_refs | 否 | 期望法规条文引用列表 |
| source_type | 否 | curated/donated/official/synthetic，默认 curated |
| dataset_version | 否 | 案例所属数据集版本，默认继承加载时版本（当前 v1） |
| notes | 否 | 标注备注，如拍摄角度、遮挡、光照、边界情况 |

## 与模型输出的关系

所有 `expected_*` / `ground_truth_*` 字段都是人工标注真值。模型输出、Ensemble
结果、Risk Engine 结果写入评测结果文件（`backend/data/eval/results.jsonl`），
绝不写回本数据集。

## 新增案例最小示例

```jsonl
{"id":"eval-fire-101","scenario":"消防","description":"小区单元门口防火卷帘下方堆放杂物","expected_category":"占用疏散通道","expected_level":2,"expected_clause_terms":["疏散通道","防火卷帘"]}
```

## 完整字段示例

```jsonl
{"id":"eval-community-101","scenario":"社区","description":"小区地下车库入口限高杆锈蚀倾斜","expected_category":"公共区域安全隐患","expected_level":3,"expected_clause_terms":["公共设施"],"expected_source":"公共设施维护相关规范","ground_truth_hazard_present":true,"expected_review_required":true,"expected_evidence_supported":true,"user_text":"入口处有儿童经过","image_paths":[],"expected_hazard":"限高杆锈蚀倾斜，存在倾倒伤人风险","expected_regulation_refs":["公共设施维护规范-设施检查"],"source_type":"curated","dataset_version":"v1","notes":"夜间拍摄、存在遮挡"}
```

## 数据来源分类

- `curated`：人工整理并复核的真实场景案例（Web 公开真实案例或采集现场资料）。
- `official`：来自官方通报/裁判文书等可核验来源。
- `donated`：试点单位/受访人员提供并允许脱敏使用的案例。
- `synthetic`：为覆盖边界自动/人工合成的案例。**synthetic 永远不能冒充真实评测数据**；
  用于正式报告时需在报告中单独列出，或运行时用 `include_synthetic=False` 过滤。

## 扩展到 100 / 200 案例

保持上述 JSONL 格式追加案例即可。正式报告按 `dataset_version` 与
`manifest.case_count` 标识数据集大小；不要依赖“恰好 30 条”之类的硬编码。
