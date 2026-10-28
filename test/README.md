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

测试在应用导入前固定 Mock，清空真实模型 Key，并将数据库、上传、知识库副本、向量缓存、checkpoint 和临时目录设置到 `test/.artifacts/`。真实 httpx HTTP 传输被阻止；`httpx.MockTransport` 与 FastAPI TestClient 可以使用。

普通 `DATABASE_URL` 不作为新入口的数据库来源。只有显式提供 `TEST_DATABASE_URL` 才可覆盖默认测试库：

- SQLite 必须是 `test/.artifacts/` 内的绝对文件路径，禁止 URI 查询参数。
- PG 限定 `postgresql+psycopg`、本机地址、以 `test_` 开头或 `_test` 结尾的专用数据库名；必须事先创建专用测试库。
- PG CI 已接入这一参数。本地 R0 尚未执行 PG 运行验证。
- 不要把生产库改名后交给测试；显式测试库内的数据仍会被历史测试创建或清理。

历史 `backend/tests/conftest.py` 未修改，仍会操作其原有固定测试文件名。推荐统一使用上述入口，以便在其导入前缓存隔离配置；不要把任何业务数据放进历史 `test.db` 或 `langgraph-test.db`。

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

## 记录实施基线

先生成后端两份 JUnit 和前端 JSON 报告，再运行：

```powershell
.\backend\.venv\Scripts\python.exe test/record_baseline.py
```

默认输出 `docs/baselines/r0-2026-10-28.json`。记录器要求实际执行且通过的测试报告，并核对后端的 SQLite/Mock 元信息；缺失报告/字段、失败、全跳过或环境不一致均不能形成绿色基线。

记录内容包括 Git 修订、工作区是否有改动、`backend/app` 和 `frontend/src` 源文件指纹、测试数量、现有评测集哈希和覆盖摘要。记录器不导入应用设置，不读取 `.env`、API Key、数据库密码。

新阶段如需新基线，使用 `--output docs/baselines/<新名称>.json`，保留旧文件。报告产物留在 `test/.artifacts/reports/`，不提交运行时数据库或原始日志。

R0 的缺陷回归设计见 [R0 实施基线与回归清单](../docs/baselines/r0-2026-10-28.md)。
