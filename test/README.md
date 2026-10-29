# 根目录回归测试

本目录承载 2026-10-28 完善计划起新增或修改的测试、数据及辅助代码。历史测试保留原位置，通过独立进程继续执行。

## 后端

从仓库根目录运行，使用 `backend/.venv`，不要使用项目根目录的旧虚拟环境：

```powershell
# 新测试和历史测试分别启动应用，生成各自的 JUnit 报告
.\backend\.venv\Scripts\python.exe test/run_backend.py --suite all -q

# 单独运行新目录；也可直接指定 test/backend 下的聚焦文件
.\backend\.venv\Scripts\python.exe -m pytest test/backend -q

# 分别检查新旧测试的发现情况，不覆盖执行报告
.\backend\.venv\Scripts\python.exe test/run_backend.py --suite all --collect-only -q

# Python 静态检查覆盖新目录
.\backend\.venv\Scripts\python.exe -m ruff check backend test
```

`run_backend.py --suite new|legacy|all` 使用同一早期隔离插件。不要在同一 pytest 进程混跑新旧目录；应用配置、数据库 engine 和 Provider 存在导入时单例。

R1/T03 起，历史 `test_async_second_followup_falls_back_to_full_rerun` 要求完成后仍可追问，与新状态合同冲突，在根目录插件中标记为严格预期失败（xfail，意外通过会使运行失败）。历史文件未改动；正确的 409 行为由 `test/backend/test_review_state_guards.py` 显式回归。该项必须在结果中单独报告，不能计入通过数。

R6/T16 起，历史 `test_safe_ground_truth_is_not_silently_auto_passed` 要求转人工后不计误报，同样标记为 strict xfail；替代合同在 `test/backend/test_eval_detection_metrics.py`。最终报告中两项均不计通过数。

测试在应用导入前固定 Mock，清空真实模型 Key，并将数据库、上传、知识库副本、向量缓存、checkpoint 和临时目录设置到 `test/.artifacts/`。真实 httpx HTTP 传输被阻止；`httpx.MockTransport` 与 FastAPI TestClient 可以使用。

普通 `DATABASE_URL` 不作为新入口的数据库来源。只有显式提供 `TEST_DATABASE_URL` 才可覆盖默认测试库：

- SQLite 必须是 `test/.artifacts/` 内的绝对文件路径，禁止 URI 查询参数。
- PG 限定 `postgresql+psycopg`、本机地址、以 `test_` 开头或 `_test` 结尾的专用数据库名；必须事先创建专用测试库。
- PG CI 已接入这一参数；R8 已完成本地 PG 运行验证，见 [最终记录](../docs/baselines/r8-2026-10-29.md)。
- 不要把生产库改名后交给测试；显式测试库内的数据仍会被历史测试创建或清理。

历史 `backend/tests/conftest.py` 未修改，仍会操作其原有固定测试文件名。推荐统一使用上述入口，以便在其导入前缓存隔离配置；不要把任何业务数据放进历史 `test.db` 或 `langgraph-test.db`。

运行 PG 矩阵时，创建本机专用测试库后设置 `TEST_DATABASE_URL`，另把 `R3_TEST_POSTGRES_URL`、`R4_TEST_POSTGRES_URL`、`R8_TEST_POSTGRES_URL` 指向该专用库，分别启用独立 schema 的认领/幂等/发布迁移用例。未设置时这些条件用例跳过。不得指向业务库；全量套件会创建/清理测试数据。CI PG 任务已设置全部四个入口。

历史 PG 套件包含固定幂等键；重复验收应新建空的专用测试库，避免重放上轮记录而误报失败。不要为运行测试清理业务库或共用数据库。

R8 新增 `test/backend/test_release_migrations.py`：SQLite/PG 各三条路径（空库、R3 前旧库、未版本化旧库），验证到 head、重复执行和人工结果/审计/任务/幂等保留。历史 SQLite 专用迁移测试在 PG 模式跳过，由此矩阵补足。

所有运行产物均忽略提交。保留运行目录便于排查；本轮不提供自动递归清理命令。

## 前端

```powershell
pnpm --dir frontend test
pnpm --dir frontend type-check
pnpm --dir frontend lint
pnpm --dir frontend build

# 生成基线使用的实际前端执行报告
pnpm --dir frontend test --reporter=default --reporter=json --outputFile=../test/.artifacts/reports/frontend.json
```

Vitest 同时发现 `frontend/src/**/*.spec.ts` 和 `test/frontend/**/*.spec.ts`，新测试依赖复用前端的 node_modules。仅在测试模式开放外部测试目录；类型检查和 ESLint 包含新目录。生产构建仍从前端应用入口出发，不包含测试 fixture。

若 Corepack 离线不能启动 pnpm，在已安装依赖的 frontend 目录可直接执行本地 CLI：

```powershell
node node_modules/vitest/vitest.mjs run
node ../test/frontend/lint.mjs
node node_modules/vue-tsc/bin/vue-tsc.js --noEmit
node node_modules/vue-tsc/bin/vue-tsc.js --noEmit -p ../test/frontend/tsconfig.json
node node_modules/vite/bin/vite.js build
```

## 浏览器、容器与评测

仓库根目录运行以下隔离浏览器回归，Windows 使用已安装 Edge，Linux 需先安装 Playwright Chromium。默认 Python 为 backend/.venv，可设置 PYTHON 覆盖：

```powershell
node test/e2e/viewport-layout.mjs
node test/e2e/human-review.mjs
node test/e2e/async-resume.mjs
node test/e2e/assessment-lifecycle.mjs
node test/e2e/classification.mjs
node test/e2e/submission-recovery.mjs
node test/e2e/auth_modes.mjs
.\backend\.venv\Scripts\python.exe scripts/check_eval_baseline.py
```

这些入口自建隔离后端，固定 Mock 并清除模型 Key。认证/幂等和旧部署入口仍沿用 r4/r5 产物文件名，每轮验收应核对修改时间并保存独立摘要；R7 浏览器产物目录自带 UUID。容器验收命令见 [部署说明](../docs/DEPLOYMENT.md)，合成集与真实标签边界见 [评测索引](../docs/evaluation/README.md)。

M1 的后端合同/流程测试在 `test/backend/test_classification_*.py`，前端在 `test/frontend/classification.spec.ts`；发布迁移矩阵增加 R8 head → M1 的无损升级。`classification.mjs` 从真实首页上传合成图片，验证建议/人工值分离、未分级、巡查员录入/复核员审核、刷新、重复保存、历史/Markdown 导出及桌面/手机布局。原 `assessment-lifecycle.mjs` 通过兼容 API 创建历史研判，再验证原追问和整改页面；默认首页分类上传由 M1 用例覆盖。HTTP 请求合同使用 MockTransport 检查 Qwen/GLM 收到的图片字节，不能当作真实模型识别质量成绩。

两分钟恢复 E2E 使用浏览器虚拟时钟推进本地等待窗口，并暂停测试 worker；不等于真实模型运行两分钟的稳定性或费用验证。

视口检查等待 ResizeObserver 等响应式布局更新，最多 5 秒，仍严格要求 scrollWidth 不超过视口。viewport-layout.mjs 用真实浏览器覆盖即时正常、延迟恢复和永久溢出；永久溢出必须失败并附越界元素，不通过增大宽度容差掩盖缺陷。

## 记录实施基线

先生成后端两份 JUnit 和前端 JSON 报告，再运行：

```powershell
.\backend\.venv\Scripts\python.exe test/record_baseline.py
```

默认输出 `docs/baselines/r0-2026-10-28.json`。记录器要求实际执行且通过的测试报告，并核对后端的 SQLite/Mock 元信息；缺失报告/字段、失败、全跳过或环境不一致均不能形成绿色基线。

记录内容包括 Git 修订、工作区是否有改动、`backend/app` 和 `frontend/src` 源文件指纹、测试数量、现有评测集哈希和覆盖摘要。记录器不导入应用设置，不读取 `.env`、API Key、数据库密码。

新阶段如需新基线，使用 `--output docs/baselines/<新名称>.json`，保留旧文件。报告产物留在 `test/.artifacts/reports/`，不提交运行时数据库或原始日志。

记录器初始 scope 字段来自 R0 模板；后续阶段必须按实际 PG/容器/浏览器证据补充范围，不能只改标题。R8 采用独立 reports/r8-final 目录，并将原始产物摘要及校验值汇总到新基线，保留旧阶段文件。

R0 的缺陷回归设计见 [R0 实施基线与回归清单](../docs/baselines/r0-2026-10-28.md)。
