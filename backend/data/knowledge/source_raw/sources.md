# 法规文本来源清单

本目录存放“原始法规文本”，建议从官方渠道下载 PDF、Word 或网页原文，转成 `.txt` 或 `.md` 后放入本目录，命名格式：

```text
01_消防_消防法.txt
02_生产安全_安全生产法.txt
03_林区_森林防火条例.txt
```

推荐来源：

- 国家法律法规数据库：https://flk.npc.gov.cn
- 应急管理部政策法规：https://www.mem.gov.cn
- 国家消防救援局：https://www.119.gov.cn
- 重庆市应急管理局：https://yjglj.cq.gov.cn
- 重庆市人民政府：https://www.cq.gov.cn
- 国家标准全文公开系统：https://openstd.samr.gov.cn

注意事项：

- 入库前人工核对文号、条款号和版本是否现行有效。
- 文本保留条款编号，便于切片后溯源。
- 文件顶部可使用下面的 YAML 格式记录元数据，构建脚本会自动读取。

```yaml
---
id: law-example-001
title: 示例法规节选
source: 官方来源名称或链接
version: 版本/修正信息
tags: [消防, 疏散通道]
collected_at: 2026-09-05
---
正文内容……
```

当前目录内已有的节选仅用于开发验证，正式使用前必须对照官方原文逐条复核。

