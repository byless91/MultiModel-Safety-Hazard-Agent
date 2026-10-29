# 当前交接说明

更新：2026-10-29。后续只按 [最终改造计划 v2.0](docs/最终改造计划.md) 推进，整合“知识库与分类助手”和“行业数据分析”两条主线。

## 当前基线

- 在原 Vue/FastAPI 项目上增量改造，继续复用登录、上传、任务、知识检索、人工复核、整改和导出。
- 本轮恢复 R8 `583619f` 的可运行应用接入；未接通的 Claude 平行实现、重复脚本和错误阶段清单已备份后清理。
- M1–M3 已在原首页、详情、历史页和知识库页面接通；M4–M6 尚未实施；不要把清理前的旧组件原稿视为已验收功能。
- 业务数据库、上传、知识库及 `.env` 未清理，数据库未执行降级。原有迁移和回归保留。
- M0 验证：新后端 373 通过/6 个 PG 条件跳过；历史 333 通过/2 个原有 strict xfail；前端 84 通过；静态/类型/生产构建及三条业务浏览器 E2E 通过。一次原有 Windows 临时目录错误的初始日志与成功复测均留在 `test/.artifacts/reports/cleanup-20261029/`。
- M1 验证：SQLite 新后端 405 通过/7 条件跳过、历史 333 通过/2 strict xfail；PG 新后端 412 通过、历史 328 通过/3 跳过/2 strict xfail；前端 93 通过。静态、类型、构建及分类/原有业务浏览器回归通过，详情见最终计划。原始证据在 `test/.artifacts/reports/m1/` 与 `m1-classification-*/`。
- M2 验证：SQLite 新后端 425 通过/8 条件跳过、历史 333 通过/2 strict xfail；PG 新后端 433 通过/0 跳过、历史 328 通过/3 跳过/2 strict xfail；前端 101 通过。静态、类型、构建及知识库/分类/复核/研判浏览器回归通过，详情见最终计划。原始证据在 `test/.artifacts/reports/m2-final/` 与 `m2-knowledge-*/`。
- M3 验证：SQLite 新后端 437 通过/9 条件跳过、历史 333 通过/2 strict xfail；PG 新后端 446 通过/0 跳过、历史 328 通过/3 跳过/2 strict xfail；前端 105 通过。静态、类型、构建及位置录入/导入/分类/知识库/复核/研判浏览器回归通过，详情见最终计划。原始证据在 `test/.artifacts/reports/m3/` 与 `m3-location-import-*/`。

## 开发入口

- 项目启动：[README](README.md)。后端端口 8001，前端端口 5173。
- 部署与回退：[部署说明](docs/DEPLOYMENT.md)。
- 测试入口：[test/README.md](test/README.md)。新增/修改测试统一放在根目录 test/。
- 原架构与约束：[CURRENT_ARCHITECTURE.md](CURRENT_ARCHITECTURE.md)。单实例、单 worker；SQLite/PG。

## 清理前备份

`test/.artifacts/cleanup-backups/20261029-194753/claude-worktree-before-cleanup.zip`

同目录 manifest.json 记录每个文件的 SHA256、原 HEAD、恢复及删除清单；ZIP 包含原交接文档、已跟踪文件和未提交源码，共 371 文件，已校验 CRC 与 SHA256。此本地备份被 Git 忽略；Claude 已提交部分也保留于 Git 历史。

## 下一步

下一阶段只推进 M4：一张管理页展示已确认记录的地区/类别/时间分布、历史趋势和一套地图；按类似设施/场景检索其他地点的整改方案及结果。M3 已为记录补充手填位置、区划、设施/场景、坐标来源/坐标系、数据来源和事件时间，并提供按外部编号去重的导入入口；导入记录为 `imported` 状态、未视为人工确认，M4 统计须明确纳入口径。SQLite/PG 升级已加 M3 无损用例。M1 的 `m1-v1` 类别和标签来自一个后端合同；`POST /assessments` 的 `mode=classification|manual` 均保存为分类记录，省略 mode 保留历史研判接口。人工录入使用 revision 防止陈旧覆盖，审核继续限定 reviewer/admin。真实模型质量及效率收益仍待独立验证；地图、统计和更新提醒依次推进。
