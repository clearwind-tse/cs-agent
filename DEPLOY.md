
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
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# 启动（后台，日志写入日志文件）
nohup uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000 > /tmp/agent-cs-playbook-backend.log 2>&1 &

# 停止后台进程
lsof -ti:8000 | xargs kill


cd /Users/clearwind/workspace/ai-sale-course/frontend

# 启动（前台，Ctrl+C 停止）
npm run dev

# 启动（后台）
nohup npm run dev > /tmp/agent-cs-playbook-frontend.log 2>&1 &

# 停止后台进程
lsof -ti:3000 | xargs kill
