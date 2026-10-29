# 当前交接说明

更新：2026-10-29。后续只按 [最终改造计划](docs/最终改造计划.md) 推进。

## 当前基线

- 在原 Vue/FastAPI 项目上增量改造，继续复用登录、上传、任务、知识检索、人工复核、整改和导出。
- 本轮恢复 R8 `583619f` 的可运行应用接入；未接通的 Claude 平行实现、重复脚本和错误阶段清单已备份后清理。
- 新业务 M1–M4 尚未实施；不要把旧组件原稿或旧“完成清单”视为已验收功能。
- 业务数据库、上传、知识库及 `.env` 未清理，数据库未执行降级。原有迁移和回归保留。
- M0 验证：新后端 373 通过/6 个 PG 条件跳过；历史 333 通过/2 个原有 strict xfail；前端 84 通过；静态/类型/生产构建及三条业务浏览器 E2E 通过。一次原有 Windows 临时目录错误的初始日志与成功复测均留在 `test/.artifacts/reports/cleanup-20261029/`。

## 开发入口

- 项目启动：[README](README.md)。后端端口 8001，前端端口 5173。
- 部署与回退：[部署说明](docs/DEPLOYMENT.md)。
- 测试入口：[test/README.md](test/README.md)。新增/修改测试统一放在根目录 test/。
- 原架构与约束：[CURRENT_ARCHITECTURE.md](CURRENT_ARCHITECTURE.md)。单实例、单 worker；SQLite/PG。

## 清理前备份

`test/.artifacts/cleanup-backups/20261029-194753/claude-worktree-before-cleanup.zip`

同目录 manifest.json 记录每个文件的 SHA256、原 HEAD、恢复及删除清单；ZIP 包含原交接文档、已跟踪文件和未提交源码，共 371 文件，已校验 CRC 与 SHA256。此本地备份被 Git 忽略；Claude 已提交部分也保留于 Git 历史。

## 下一步

先完成 M1：在原首页和详情中做通快速录入、AI 建议、人工确认及历史回看；验收后再加位置、管理统计和公开案例导入。模型、地图、图表依赖按该阶段实际需要加入正式锁定清单。
