
### 3. 上传微信数据

将本地微信 SQLite 数据上传到服务器：

```bash
# 在服务器上创建目录
mkdir -p /opt/ai-wx-chat/Msg/Msg

# 在本地电脑执行上传（替换为你的数据路径）
rsync -avz --progress /path/to/Msg/Msg/ root@<SERVER_IP>:/opt/ai-wx-chat/Msg/Msg/
```

### 4. 构建并启动

```bash
cd /opt/ai-wx-chat
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

首次构建约 2-3 分钟（已配置国内镜像源加速）。

> **素材文件持久化**：AI 创作素材库默认落 `./data/media`（容器内 `/app/data/media`），
> `docker-compose.yml` 已挂卷。**不要删这个卷**——删了不是丢缓存，是丢用户上传的原图；
> 数据库里的记录还在，会变成一片「文件丢失」占位。
> 备份时把 `./data/media` 和 PostgreSQL 备份一起做，两者缺一不可。
>
> 容器重启会打断进程内的出图后台任务：后端启动时会自动把这些 `generating` 任务标成
> `failed`（提示重跑），不会永远转圈。若中断发生在「文件已落盘、记录未提交」之间，
> 会留下无主文件，用 `GET /api/media/files-check` 查看、`POST /api/media/files-cleanup?apply=true`
> 清理（默认 dry-run，只删表里查不到的文件）。
>
> **旧库升级到两级目录**：后端启动时会 `CREATE TABLE IF NOT EXISTS` 建 `media_categories`
> 与 `media_kind_labels`、给 `media_assets` 补 `category` 列与索引（`ensure_media_asset_schema`），
> 并 seed 预置二级目录。已有素材的 `category` 为空，会统一显示在「未归类」节点里，
> 可在素材库预览弹层中移动；一级显示名没被改过时用代码默认值，不需要预置数据。
> 这一步只加表加列不删数据，无需停机迁移。
>
> **旧库升级到「设置 · 模型信息」**：后端启动时会 `CREATE TABLE IF NOT EXISTS` 建
> `model_settings`（只存「板块 → provider + 模型名」，**不存密钥**）。旧库没有记录时所有板块
> 走 `services/model_registry.py` 的代码默认值，行为与升级前一致，无需手工导入数据。
> API Key / base_url 仍从容器环境变量（`.env`）注入，不要把密钥写进数据库或镜像；
> 多实例部署时所有实例共用同一份环境变量，设置页保存的模型选择存在共享 PG 里，
> 其余实例最多 20 秒后自动跟上（registry 缓存 TTL）。
>
> **旧库升级到「AI 创作 · 图像端点池」**：启动时 `CREATE TABLE IF NOT EXISTS` 建
> `image_endpoints` / `image_endpoint_bindings` / `image_process_jobs` 三张表，并 seed
> 一个 `_mock` 兜底端点与每个服务的默认候选链（**只补缺失**，不覆盖自建端点 / 绑定）。
> 只加表不加列，无需停机；没配真实端点时出图仍走占位图兜底，但链路完整。
>
> **图像端点密钥**：推荐 `env` 模式 —— 端点里只填环境变量名（如 `COMFY_TOKEN`），
> 真实值从容器环境变量注入，接口只回掩码。`inline` 会把密钥写进 PG，备份会一起带走，
> 生产不建议。仓库里 3 个 `demo-*` 示例端点缺密钥且停用，只用于展示端点池与绑定链界面，
> **不会被网关真的调用**；上线前改成自己的真实配置或直接删掉。
>
> **自托管端点与代理**：环境里设了 `HTTP_PROXY` / `HTTPS_PROXY` 时，指向
> `127.0.0.1` / `localhost` 的端点（本地 ComfyUI、内部 webhook）会自动绕过代理直连，
> 外部端点仍走代理。注意容器内的 `127.0.0.1` 指容器自身，跨容器调用要写服务名或宿主机 IP。
>
> 出图任务与单图即席处理都跑在进程内 `BackgroundTasks`：容器重启会打断执行，
> 出图任务启动时自动标 `failed`（前端点「重跑」恢复），即席处理异常会落 `failed` 并打印堆栈，
> 不会静默卡在 `running`。

### 5. 导入数据

启动完成后，触发 ETL 将微信数据导入 PostgreSQL：

```bash
# 等待后端完全启动（约 10 秒）
sleep 10

# 触发数据导入
curl -X POST http://localhost:8000/api/admin/etl
```

## 📝 常用运维命令

```bash
# 查看容器状态
docker ps -a

# 查看后端日志
docker logs -f agent-cs-playbook-backend

# 重启单个服务
docker compose restart backend

# 更新代码并重新部署
cd /opt/ai-wx-chat && git pull && docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build

# 只重建后端（不影响前端和数据库）
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build backend

# 进入数据库
docker exec -it agent-cs-playbook-db psql -U postgres -d agent_cs_playbook

# 查看数据库表
docker exec agent-cs-playbook-db psql -U postgres -d agent_cs_playbook -c "\dt"

# 清理 Docker 缓存
docker system prune -a -f
```

cd /Users/clearwind/workspace/ai-sale-course/backend

# 启动（前台，Ctrl+C 停止 —— 日常开发推荐）
# --reload-dir app 必须带：否则出图写入 data/media 会触发 reload，打断后台任务
uv run uvicorn app.main:app --reload --reload-dir app --host 0.0.0.0 --port 8000

# 启动（后台，日志写入日志文件）
nohup uv run uvicorn app.main:app --reload --reload-dir app --host 0.0.0.0 --port 8000 > /tmp/agent-cs-playbook-backend.log 2>&1 &

# 停止后台进程
lsof -ti:8000 | xargs kill


cd /Users/clearwind/workspace/ai-sale-course/frontend

# 启动（前台，Ctrl+C 停止）
npm run dev

# 启动（后台）
nohup npm run dev > /tmp/agent-cs-playbook-frontend.log 2>&1 &

# 停止后台进程
lsof -ti:3000 | xargs kill
