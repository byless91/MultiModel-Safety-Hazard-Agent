# 部署、升级与回退（R8 + M6）

适用范围：一个后端实例、一个 worker；SQLite 或 PostgreSQL；本地持久卷。R8 已在隔离卷验证两种 Compose 的冷启动、JWT 登录、图片研判/复核/导出、重启持久化、依赖故障和迁移失败。M6 用两套隔离应用实例验证云端审核→知识包导出→本地导入、升级保留旧引用和断网本地流程；本轮未重复构建容器镜像，容器部署证据沿用 R8。生产网络、TLS、现场法规库和实际数据恢复演练仍由部署环境验收。

## 本地演示

从仓库根目录执行，Docker Desktop/Engine 须可用：

```powershell
$env:PROVIDER_MODE = 'mock'
$env:AUTH_MODE = 'none'
$env:BACKEND_BIND_HOST = '127.0.0.1'
$env:FRONTEND_BIND_HOST = '127.0.0.1'
docker compose -p safety-demo up -d --build --wait --wait-timeout 180
Invoke-RestMethod http://127.0.0.1:8080/api/v1/ready
```

前端为 http://127.0.0.1:8080。首次空卷从只读开发种子离线生成知识切片，不需要模型 Key。ready 中 development_seed_unreviewed 表示开发节选尚未审核，不能据此判断法规适用性。只读 health/live 正常也不能替代 ready。

## JWT 与管理员

下面以独立项目名 safety-jwt 为例。使用固定项目名升级，避免无意创建另一组空卷。先生成并安全保存独立随机密钥，通过受控环境或仓库根目录未提交的 .env 注入；后续每次 Compose 都必须使用同一个值。不要把密钥写进版本库或报告。

```powershell
# 在已安装 backend/.venv 的开发机生成；赋值不会在终端打印密钥
$env:AUTH_JWT_SECRET = .\backend\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_hex(32))"
$env:AUTH_MODE = 'jwt'
$env:PROVIDER_MODE = 'mock'
$env:WORKFLOW_MODE = 'async'
$env:BACKEND_BIND_HOST = '127.0.0.1'
$env:FRONTEND_BIND_HOST = '127.0.0.1'
docker compose -p safety-jwt up -d --build --wait --wait-timeout 180
docker compose -p safety-jwt exec backend python -m app.cli.create_user --username admin --role admin
```

密码交互输入；自动化可用 --password-stdin，避免命令行参数携带密码。登录后 admin 管理用户/知识，reviewer 执行复核及整改流转，inspector 提交研判和整改照片。none 不提供访问保护，token 只有共享静态凭证；两者不能代替个人身份审计。更换 JWT 密钥会使原会话及签名图片 URL 失效。

真实模型必须显式配置 PROVIDER_MODE 及对应 Key，调用可能计费。容器默认 mock；本地 auto 无 Key 也会标为 Mock。上线前先审核语料来源、版本、生效范围，再用授权现场样本验证质量。

## PostgreSQL

```powershell
# 使用不同项目名，防止与已有 SQLite 卷混用
# JWT 模式沿用上节已安全保存的密钥与环境变量
docker compose -p safety-pg -f docker-compose.pg.yml up -d --build --wait --wait-timeout 180
docker compose -p safety-pg -f docker-compose.pg.yml exec backend python -m app.cli.create_user --username admin --role admin
```

仓库 PG 文件使用 safety/safety 作为本地开发账号。实际部署前须通过私有 Compose override 同时设置 db 的 POSTGRES_PASSWORD 和 backend 的 DATABASE_URL，使用独立强密码；既有 PG 卷改环境变量不会修改数据库已有角色密码，应由 DBA 执行角色改密并同步连接串。不要直接把开发模板暴露到外网。PG 不解除单实例、本地 checkpoint/上传/索引约束。

## 迁移与升级

1. 记录当前 Git SHA、两端镜像 ID、Compose 项目名/文件/环境、卷映射和现有 Alembic 版本；备份后再升级。保留原镜像，不清理业务卷。
2. 停止入口及 backend 后取得一致备份。SQLite 的 app.db、WAL/SHM、checkpoint 及其 WAL/SHM、uploads、knowledge、向量缓存属于同一恢复点，不能只复制正在写入的 app.db。PG 使用 pg_dump 的一致性导出，同时备份停止写入后的 backend-data。
3. 重建或指定已经验收的 BACKEND_IMAGE/FRONTEND_IMAGE，仍用原 Compose 项目名启动单 worker。启动会自动增量迁移，迁移失败拒绝启动，不绕过健康检查。
4. 检查 ready、登录、旧研判人工结论/审计、签名图片、知识、任务以及一次受控业务闭环。旧卷不会被新种子覆盖。

当前数据库 head 为 `f6a2c91d4e70`。R3/R4 的迁移依次为：

| 版本 | 增量 |
|---|---|
| c21a7db8e401 | assessment_jobs 的 worker_id、attempt_token、lease_expires_at |
| e9c31a57db02 | assessments.followup_token |
| f04b62a9c310 | idempotency_keys.request_hash |

M1–M6 继续增量增加：`a12f083bcd71` 分类记录、`b27e619ac430` 知识文档版本与审核、`d5e2f7a91c04` 记录位置/来源/事件时间、`e91c4f7a2d68` 权威来源与趋势提示、`f6a2c91d4e70` 知识包导入记录。新增列允许历史 null；无指纹旧 key 可 GET 恢复，但 POST 重放要求明确冲突处理。复核历史保留在原 JSON，不重写已确认结果。空库、R3 前已版本化库和未版本化旧库的 SQLite/PG 升级及重复执行已验证；这不能替代对实际部署备份的恢复演练。

如需手工迁移，在 backend 目录执行，环境必须指向计划内目标库：

```powershell
Set-Location backend
.\.venv\Scripts\python.exe -m alembic current
.\.venv\Scripts\python.exe -m alembic upgrade head
```

容器对应命令为 `docker compose -p <项目名> exec backend python -m alembic current`。PG 命令额外指定同一个 -f docker-compose.pg.yml。不要在运行的业务库上执行测试命令。

## 知识包同步与离线边界

单组织建议只在云端审核知识版本，再由本地管理员在“知识库”页导入。导出只包含每个系列最新的已审核版本，包内清单记录文档数量和 SHA256；导入在写入前校验格式、审核策略、数量、清单摘要、逐篇内容指纹、行业目录和演示标记。导入保留云端审核历史并追加导入事件，同系列旧有效版本转为已替代，既有研判的证据快照不变。知识库页显示本地知识包版本和最后同步时间；接口为 `/api/v1/knowledge/pack/export|import|status`（admin）。

无外网时，本地已部署实例仍可完成知识检索、人工录入、历史/详情访问和已有记录导出；地图底图、权威来源检查、真实模型调用需要网络。Mock 分类只用于演示，不能作为离线 AI 能力。断开外网后的本地流程由 `test/e2e/m6-delivery.mjs` 验证；两套隔离实例的云端审核→导出→本地导入、升级保留旧引用和篡改包拒绝也在同一脚本中验证。

`test/e2e/m6-timing.mjs` 记录查询、录入、Mock 分类和复核（含一次退回与人工更正）的工程基线，仅用于流程耗时对照，不代表真实模型质量或业务收益。

## 备份与回退

备份至少包含业务数据库、整个 backend-data、本轮配置与稳定密钥，以及可定位的镜像/Git 版本。PG 数据卷与 SQLite 文件不要相互替换。备份需存放在独立受控位置，并在新的隔离项目中恢复校验，不覆盖原卷；验证人工审计、用户、图片、知识和任务后再切换入口。不要使用 down --volumes 或 volume prune 回退业务部署。

优先修复后向前升级。R8 相对 R7 只增加验收/CI/文档，数据库 head 和业务代码相同，可保留当前数据库，使用 R7 `00879c4` 对应且已保存的镜像回退应用。更早版本是否兼容新增字段、状态与 JSON 审计必须另验，不能默认安全。禁止用 Alembic downgrade 删除租约、幂等或审计数据。若必须恢复数据，停止写入并整体恢复同一时点的数据库、文件与 checkpoint，避免旧任务与新文件混合。

上述为运维操作约定；R8 验证了隔离容器重启/替换后的持久化，没有对实际生产备份执行恢复或切换。

## 可重复的隔离部署验收

```powershell
docker build --pull=false -t safety-r8-backend:test backend
docker build --pull=false -t safety-r8-frontend:test frontend
.\backend\.venv\Scripts\python.exe test/e2e/compose_smoke.py --variant sqlite --backend-image safety-r8-backend:test --frontend-image safety-r8-frontend:test
.\backend\.venv\Scripts\python.exe test/e2e/compose_smoke.py --variant pg --backend-image safety-r8-backend:test --frontend-image safety-r8-frontend:test
.\backend\.venv\Scripts\python.exe test/e2e/container_bootstrap.py --image safety-r8-backend:test
```

脚本只移除自身随机项目/带测试标签的卷，生成 test/.artifacts/reports/r5-*.json（沿用既有脚本文件名）。R8 已将本轮结果另存并汇入 [验收摘要](baselines/r8-2026-10-29.json)，文件名中的 R5 不表示复用旧运行结果。
