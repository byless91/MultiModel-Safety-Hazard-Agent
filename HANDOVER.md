# 当前交接说明

更新：2026-10-29。后续只按 [最终改造计划 v2.0](docs/最终改造计划.md) 推进，整合“知识库与分类助手”和“行业数据分析”两条主线。

## 当前基线

- 在原 Vue/FastAPI 项目上增量改造，继续复用登录、上传、任务、知识检索、人工复核、整改和导出。
- 本轮恢复 R8 `583619f` 的可运行应用接入；未接通的 Claude 平行实现、重复脚本和错误阶段清单已备份后清理。
- M1 分类助手与人工录入已在原首页/详情接通，M2–M6 尚未实施；不要把清理前的旧组件原稿视为已验收功能。
- 业务数据库、上传、知识库及 `.env` 未清理，数据库未执行降级。原有迁移和回归保留。
- M0 验证：新后端 373 通过/6 个 PG 条件跳过；历史 333 通过/2 个原有 strict xfail；前端 84 通过；静态/类型/生产构建及三条业务浏览器 E2E 通过。一次原有 Windows 临时目录错误的初始日志与成功复测均留在 `test/.artifacts/reports/cleanup-20261029/`。
- M1 验证：SQLite 新后端 405 通过/7 条件跳过、历史 333 通过/2 strict xfail；PG 新后端 412 通过、历史 328 通过/3 跳过/2 strict xfail；前端 93 通过。静态、类型、构建及分类/原有业务浏览器回归通过，详情见最终计划。原始证据在 `test/.artifacts/reports/m1/` 与 `m1-classification-*/`。

## 开发入口

- 项目启动：[README](README.md)。后端端口 8001，前端端口 5173。
- 部署与回退：[部署说明](docs/DEPLOYMENT.md)。
- 测试入口：[test/README.md](test/README.md)。新增/修改测试统一放在根目录 test/。
- 原架构与约束：[CURRENT_ARCHITECTURE.md](CURRENT_ARCHITECTURE.md)。单实例、单 worker；SQLite/PG。

## 清理前备份

`test/.artifacts/cleanup-backups/20261029-194753/claude-worktree-before-cleanup.zip`

同目录 manifest.json 记录每个文件的 SHA256、原 HEAD、恢复及删除清单；ZIP 包含原交接文档、已跟踪文件和未提交源码，共 371 文件，已校验 CRC 与 SHA256。此本地备份被 Git 忽略；Claude 已提交部分也保留于 Git 历史。

## 下一步

下一阶段只推进 M2：扩展原知识库的行业目录、文档/条款版本、适用范围与审核状态，并保留历史引用。M1 的 `m1-v1` 类别和标签来自一个后端合同；`POST /assessments` 的 `mode=classification|manual` 均保存为分类记录，省略 mode 保留历史研判接口。人工录入使用 revision 防止陈旧覆盖，审核继续限定 reviewer/admin。真实模型质量及效率收益仍待独立验证；地图和统计依次留到后续阶段。
