# Agent CS

**面向客服场景的 Agent 工程实现**：多轮对话状态管理、意图与情绪识别、工单自动闭环、资金类动作的人在环审批，以及从聊天记录到知识库、质检、训练数据的离线流水线。

一套后端同时提供两套可替换的 Agent 编排引擎（deepagents / LangGraph），切换只改一个环境变量。

<p>
<img alt="license" src="https://img.shields.io/badge/license-Apache--2.0-blue">
<img alt="python" src="https://img.shields.io/badge/Python-3.11%2B-3776AB">
<img alt="react" src="https://img.shields.io/badge/React-18-61DAFB">
<img alt="fastapi" src="https://img.shields.io/badge/FastAPI-0.109%2B-009688">
<img alt="postgres" src="https://img.shields.io/badge/PostgreSQL-17%20%2B%20pgvector-4169E1">
</p>

---

## 目录

- [项目简介](#项目简介)
- [功能特性](#功能特性)
- [界面预览](#界面预览)
- [系统架构](#系统架构)
- [技术栈](#技术栈)
- [快速开始](#快速开始)
- [配置](#配置)
- [目录结构](#目录结构)
- [核心设计](#核心设计)
- [API 概览](#api-概览)
- [生产部署](#生产部署)
- [已知限制](#已知限制)
- [许可证](#许可证)

---

## 项目简介

客服 Agent 的难点不在"接个大模型回话"，而在四件真正会出事的事：

| 问题 | 本项目的处理方式 |
| --- | --- |
| 多轮对话中客户说过的信息会丢 | **DST 状态机作为唯一真相源**，每轮 prompt 由状态渲染，信息结构化保存 |
| 一句话判"投诉"就转人工 | **多信号累积打分**，≥3 分才转接，转接时携带已登记信息 |
| 工单建了但与对话失联 | 工单挂在 `session_id` 上，挂起时把 `thread_id` 写入工单 |
| 退款等不可逆动作由模型直接执行 | 工具真实出号 + 正则校验 + **人在环审批闸门**，未批准不执行 |

代码分两条主线，共用同一套后端与数据模型：

- **在线链路**：客户对话 → 意图路由 → 工具调用 → 建单 → 挂起等人审 → 转人工
- **离线链路**：聊天记录 → 清洗标注 → 知识库 → 质检与校准 → 训练数据（SFT / DPO）

---

## 功能特性

**在线客服**

- SSE 流式对话，回复带意图与情绪徽章
- 意图识别两级策略：词典初筛 + LLM 精判
- 七阶段对话状态机（intake → info_gathering → diagnosis → solution → action → closing → escalation）
- 工具调用：订单查询、物流查询、建单、知识库检索、退款受理
- **审批闸门**：退款类动作自动挂起，坐席批准后图从断点恢复执行（跨进程可恢复）
- 子 Agent 委派：投诉处理 / 工单处理 / FAQ / 多轮对话
- Skill 与 MCP 动态挂载，SOP 文本可直接包成工具

**离线数据**

- 聊天记录 ETL 入库（PostgreSQL）
- 会话清洗 → 人工审核 → 标注，AI 只能推进到 staging，进 labeled 必须过人
- 知识提炼与向量化（pgvector），供 RAG 检索
- 自动质检评分、人工复核、AI 与人工标注的校准对比
- 训练数据管理：SFT 样本提取、DPO 偏好对生成与标注、微调数据集导出

**AI 创作**（独立工作区，与客服数据体系并列）

- 本地磁盘素材库：上传 / sha256 去重 / 两级分类目录 / 一级显示名可改 / 静态直出
- 五个并列出图目标（套图 / 风格 / SKU 替换 / 服装组图 / 精修）各有专属输入契约，弹窗按目录选图或就地上传
- 两阶段任务：同步产出逐图规划 → 人工确认闸门 → 后台执行 → 进度轮询 → 成图入库
- **图像端点池**：任意多个端点（webhook / OpenAI 兼容 / 火山方舟 / mock），声明能力标签与密钥模式；按服务绑定有序候选链，可按动作覆盖
- **动态分派**：镜头标题翻译成能力标签，网关逐个尝试候选端点、失败自动 fallback，全失败才回落占位图；任务内可临时指定本次端点而不砍掉兜底链
- 素材库单图即席处理：对任意一张图直接选动作 + 选端点，走同一网关，结果回写素材库

---

## 界面预览

> 截图为本地运行画面，采用「流体极光」视觉主题与四工作区信息架构（在线服务 / 数据治理 / 模型优化 / AI 创作）；对话与数据均为演示数据。「04 AI 创作」已接通**素材库（本地磁盘 · 两级目录）**、**两阶段出图任务链路**（规划 → 人工确认 → 后台执行 → 产出入库）与**图像端点池**（端点可任意多个、按服务绑定候选链、运行时按动作动态分派）；出图功能的素材角色在**弹窗**里按目录选图或就地上传，一次确认写回。规划仍是规则引擎；仓库不内置图像模型凭证，在「端点池」页注册自己的端点即可出真图，未配端点或全链失败时才回落内置占位图，页面上逐项标注实际命中的端点。

**工作台** —— 登录后的行动起点：三条待办队列（待处理工单 / 待审对话 / 未达合格线质检）各取最新记录，点条目直接进模块处理；下方按导航 IA 分组直达各功能

![工作台](docs/screenshots/workbench.png)

**全局数据看板** —— 跨工作区汇总 KPI、数据闭环健康度与图表，一眼掌握全局（顶部「全局总览」入口）

![全局数据看板](docs/screenshots/overview.png)

**设置 · 模型信息** —— 全局工具里的新入口：上半部分是各 Provider 的连接状态（只显示「已配置 / 未配置」和环境变量名，不回显密钥），下半部分按三个组列出 13 个业务板块，每个板块单独选 provider 与模型名；改动按草稿暂存，统一保存后即时生效。每行可先测试连通性、也可一键恢复代码默认

![设置 · 模型信息](docs/screenshots/settings.png)

**智能客服工作台** —— 意图识别、工具调用、退款挂起待审批（位于「01 在线服务」工作区）

![智能客服对话](docs/screenshots/agent-chat.png)

**工单** —— Agent 在对话中自动创建，与来源会话关联

![工单](docs/screenshots/agent-ticket.png)

**AI 创作** —— 「04 AI 创作」工作区按「创作工作台 / 出图能力 / 后期编排 / 素材底座 / 图像端点」五组组织。这些功能是**并列的出图目标**，不是要依次走完的流水线；上下文条显示功能组身份，不伪造「下一步该去哪个功能」

![AI 创作](docs/screenshots/studio.png)

**五个功能各自的表单** —— 输入结构真的不同：SKU 替换要区分「底图 / 新商品图」，服装组图要区分「上装 / 下装 / 模特」，精修按勾选的修复项逐项出图。每个功能由 `studioKinds.ts` 描述素材角色与专属选项，后端按同一份 key 白名单生成各自的逐图规划

![五个出图功能的配置页对比](docs/screenshots/studio-kinds.png)

**出图任务工作台** —— 三步流程：配置输入 → 逐图规划（可审、可改，卡片带该功能的专属元信息）→ 确认后后台执行并轮询进度，产出自动进素材库。素材角色不再在配置页里平铺缩略图：每个槽位只显示已选内容，点「选择素材」打开**选图弹窗**，左侧两级目录树、右侧大图网格、可搜索、可多选，一次确认写回；弹窗另一个 Tab 可**就地上传新图**，落到该角色的默认目录，传完自动进入待选。功能头卡按端点池实际情况显示「网关已就位」或「占位图兜底」，不会让人把占位图误认成真成图

![出图任务 · 配置输入](docs/screenshots/studio-task.png)

**选图弹窗** —— 目录树、网格、搜索与多选集中在一处，选好一次确认；上传 Tab 与素材库 Tab 共用同一份待选草稿

![选图弹窗 · 按目录选图](docs/screenshots/studio-picker.png)

![选图弹窗 · 就地上传](docs/screenshots/studio-slot-upload.png)

确认后进入后台执行，进度按张数推进，产出自动入库：

![出图任务 · 执行结果](docs/screenshots/studio-result.png)

**素材库 · 两级分类目录** —— 一级是五个固定 key（商品图 / 风格参考 / 成图 / 参考图 / 其他），**显示名可以在左侧目录树里双击或点铅笔直接改**，改完存 `media_kind_labels` 表，重启后仍生效，也能一键恢复默认；key 不变，所以出图功能的默认目录、后端白名单、生成结果归类都不受影响。二级目录由 `media_categories` 表维护：启动时 seed 预置目录，也可在左侧目录树里自建；「未归类」是可点的虚拟节点。上传默认落到当前选中目录，预览弹层里可把素材移动到别的目录。删目录只把素材移到「未归类」，**不删文件**；改一级时自动清掉旧的二级目录，避免素材藏进看不见的组合。底层仍是本地磁盘落盘（`backend/data/media`）+ sha256 去重

![素材库](docs/screenshots/studio-assets.png)

![按二级目录筛选](docs/screenshots/studio-categories.png)

![一级目录改名（key 不变）](docs/screenshots/studio-kind-rename.png)

**图像端点池与运行时选择** —— 端点是一等数据，可任意多个，每个声明协议、能力标签、密钥模式、参数与优先级；每个出图服务绑定一条**有序候选链**（顺序就是 fallback 顺序），还能按具体动作单独配一条覆盖链。真正用哪个在运行时定：镜头标题翻译成能力标签，网关只把这次任务交给能做该动作的端点，失败自动试下一个，全失败才回落内置占位图。端点页支持增删改、连通性自检、链上移 / 下移；密钥推荐 `env` 模式只填变量名，接口不回显明文

![图像端点池与服务绑定](docs/screenshots/studio-endpoints.png)

![注册端点 · 协议 / 能力 / 密钥模式](docs/screenshots/studio-endpoint-add.png)

![按能力覆盖候选链](docs/screenshots/studio-endpoint-bindings.png)

**在对应服务里选端点** —— 出图功能的配置页与规划页都能选「本次用哪个端点」，只是把选中项提前到链首，**不砍掉后续 fallback**；规划阶段每张镜头就摊开「要做什么动作 / 将交给谁」，确认前可以改端点并重新规划，执行后逐镜头记录实际命中端点与失败尝试

![任务内运行时端点选择](docs/screenshots/studio-task-endpoint.png)

![规划卡提前标注端点](docs/screenshots/studio-plan-endpoint.png)

![执行结果与逐镜头路由](docs/screenshots/studio-result-endpoint.png)

**单图即席处理** —— 素材库里对任意一张图直接选动作 + 选端点处理，不需要走完整出图任务；走的是同一个网关，结果回写素材库并留下 `image_process_jobs` 记录

![素材库单图 AI 处理](docs/screenshots/studio-image-process.png)

![单图处理完成 · 结果回写素材库](docs/screenshots/studio-image-process-done.png)

<details>
<summary><b>展开更多界面截图</b></summary>

**Skill & MCP 管理 / Agent 配置**

![Skill & MCP](docs/screenshots/agent-skill.png)
![Agent 配置](docs/screenshots/agent-config.png)

**数据质检中心**：清洗审核 → 质检评分 → 校准对比（「02 数据治理」工作区）

![会话清洗与审核](docs/screenshots/qc-clean.png)
![质检评分](docs/screenshots/qc-score.png)
![校准对比](docs/screenshots/qc-calibration.png)

**其他模块**

会话台与聊天记录：
![会话台](docs/screenshots/chat-home.png)
![聊天记录](docs/screenshots/chat-record.png)

全文搜索：
![全文搜索](docs/screenshots/search.png)

RAG 智能助手：
![智能助手](docs/screenshots/ai-assistant.png)

知识提炼 / AI 考核：
![知识提炼](docs/screenshots/extractor.png)
![AI 考核](docs/screenshots/quiz.png)

数据管理与导出：
![自定义对话数据](docs/screenshots/custom-data.png)
![导出](docs/screenshots/export.png)

</details>

---

## 系统架构

```mermaid
flowchart TB
    subgraph FE["前端 React 18 + Vite + TS"]
        W1["会话台<br/>聊天记录 / 搜索"]
        W2["智能客服工作台<br/>对话 · 工单 · Skill/MCP · 配置"]
        W3["数据质检中心<br/>清洗审核 · 质检评分 · 校准对比"]
        W4["训练数据管理<br/>SFT · DPO · 数据集导出"]
        W5["AI 创作工作区<br/>素材库 · 五个出图功能 · 端点池"]
    end

    subgraph BE["后端 FastAPI（23 个 router）"]
        A1["/api/agent<br/>SSE 流式对话"]
        A2["/api/ticket<br/>工单 + 审批决策"]
        A3["/api/qc<br/>质检与校准"]
        A4["/api/chats · /api/search · /api/labeling<br/>/api/knowledge · /api/export · /api/training"]
        A5["/api/media · /api/studio · /api/image<br/>素材库 · 两阶段出图 · 图像端点网关"]
        A6["/api/model-settings<br/>板块模型选择（密钥只在 .env）"]
    end

    subgraph ORCH["编排层（可替换）"]
        E1["deepagents（默认）"]
        E2["LangGraph（对照实现）"]
        M1["Middleware<br/>Filesystem · TodoList · HumanInTheLoop"]
        T1["工具层<br/>内置工具 + RAG + skill_* + mcp_*"]
    end

    subgraph DATA["存储"]
        D1[("PostgreSQL 17<br/>+ pgvector")]
        D2[("Checkpoint 表")]
        D3[("本地磁盘 media/<br/>可替换为 OSS")]
    end

    W1 & W2 & W3 & W4 --> A1 & A2 & A3 & A4
    W5 --> A5
    A1 --> E1 & E2
    E1 --> M1 --> T1
    E2 --> T1
    E1 --> D2
    T1 --> D1
    A2 & A3 & A4 --> D1
    A5 --> D1
    A5 --> D3
    A6 --> D1
    A5 -.按能力分派.-> G1["图像端点池<br/>webhook / OpenAI Images / 火山方舟 / mock"]
    T1 -.可选.-> D3
```

**设计原则**：编排层可替换，工具层、工单、质检、数据流水线都不依赖具体引擎。切引擎只改 `AGENT_ENGINE`。AI 创作是独立工作区，与客服数据体系并列；出图不再写死模型，端点池里注册什么就用什么，全链失败才回落到内置占位图。

---

## 技术栈

| 层 | 选型 |
| --- | --- |
| Web 框架 | FastAPI ≥0.109 · uvicorn · pydantic-settings |
| Agent 编排 | deepagents 0.7+ · langchain 1.4+ · langgraph 1.2+ |
| 断点持久化 | langgraph-checkpoint-postgres |
| 数据库 | PostgreSQL 17 + pgvector · SQLAlchemy 2.0 · psycopg2 |
| 模型接入 | 文本：`model_registry` 统一解析（OpenAI 兼容 · DeepSeek / DashScope / 本地 Ollama）；图像：`image_gateway` 端点池（webhook / OpenAI Images / 火山方舟 / mock），密钥不落库 |
| 前端 | React 18 · Vite 5 · TypeScript 5.3 · Tailwind 3.4 · react-router 6 · axios · zustand |
| 素材存储 | 默认本地磁盘 `backend/data/media` + PG 元数据；切 OSS 只替换 `media_store.py`，火山 TOS 为可选预留 |
| 部署 | Docker Compose · nginx |

> 不使用 ORM 迁移工具，启动时 `create_all` + `schema_sync` 兜底补列。取舍是为了"clone 下来就能跑"，代价是改表需手工。

---

## 快速开始

### 前置要求

- Python 3.11+
- Node.js 18+
- Docker（用于起数据库）

### 1. 启动数据库

```bash
docker compose -f docker-compose.db.yml up -d
# PostgreSQL 17 + pgvector，映射到宿主机 :5432
# 数据库名：aiwxchat（见 backend/.env）
```

### 2. 启动后端

```bash
cd backend
cp env.example .env          # 至少填写 DATABASE_URL 和一个 LLM 的 API Key
uv sync                      # 或 python -m venv .venv && .venv/bin/pip install -e .
PYTHONPATH= ./.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8100

# 开发期需要热重载时，必须把监听范围限定在代码目录：
PYTHONPATH= ./.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8100 \
  --reload --reload-dir app
```

> `PYTHONPATH=` 置空是刻意的：避免环境中额外的 `sitecustomize` 抢先加载。
>
> **`--reload-dir app` 不能省**：出图任务跑在进程内的 `BackgroundTasks`，每写一张图到
> `backend/data/media` 都会改动磁盘。若让 reload 监控整个 `backend/`，进程会在出图中途重启、
> 后台任务被直接打死，任务永远卡在 `generating`。直接运行 `python -m app.main` 时
> 代码里已内置同样的排除规则。即便如此，进程被 kill 仍会留下僵尸任务：启动时全量回收、
> 查询时 90 秒超时兜底，都标成 `failed`，在任务工作台点「重跑」即可恢复。

后端启动后：

- 健康检查 / 接口文档：<http://localhost:8100/docs>
- 首次启动会自动建表（空库即可跑通在线链路）

### 3. 启动前端

```bash
cd frontend
npm install
npm run dev                  # http://localhost:3000
```

前端请求走相对路径 `/api`，由 Vite 代理到 `frontend/vite.config.ts` 中的 `server.proxy['/api'].target`，当前值为 `http://localhost:8100`。**后端端口需与之一致**。

### 端口一览

| 服务 | 开发默认 | 说明 |
| --- | --- | --- |
| 后端 | 8100 | 与 Vite 代理一致；生产容器内为 8000 |
| 前端 dev | 3000 | Vite `server.port` |
| 前端容器 | 80 | nginx |
| 数据库（dev） | 5432 | `docker-compose.db.yml` |
| 数据库（prod） | 5433 | `docker-compose.yml` |

### 关于演示数据

仓库**不含**任何真实聊天记录。空库即可跑通在线链路；如需演示数据，将脱敏 `pg_dump` 放到 `docker/initdb/01-data.sql` 后重建数据卷（该文件已在 `.gitignore` 中）。

---

## 配置

配置文件：`backend/.env`（模板见 `backend/env.example`）

| 变量 | 作用 | 默认 |
| --- | --- | --- |
| `DATABASE_URL` | PostgreSQL 连接串 | 见 `env.example` |
| `AGENT_ENGINE` | Agent 引擎：`deepagents` / `langgraph` | `deepagents` |
| `DEEPAGENTS_HITL` | 审批闸门总开关，`0` 关闭 | 开启 |
| `DEEPAGENTS_TODOS` | 规划中间件，`1` / `0` 强制开关 | 按意图自动 |
| `DEEPSEEK_API_KEY` / `DEEPSEEK_BASE_URL` | DeepSeek 连接信息 | — |
| `OPENAI_API_KEY` / `OPENAI_BASE_URL` | OpenAI 兼容端点（可指向本地 Ollama / vLLM） | 官方地址 |
| `ARK_API_KEY` / `ARK_BASE_URL` / `ARK_EMBEDDING_MODEL` | 百炼 DashScope 对话 + Embedding | `text-embedding-v3` |
| `ARK_VISION_*` | 火山方舟图片识别（可选；`ARK_VISION_MODEL` 是账号相关的 `ep-xxxx` 端点 ID，自托管务必换成自己的） | — |
| `WECHAT_DB_PATH` / `VOICE_FILE_PATH` | 微信数据源路径 | `../Msg/Msg` |
| `MEDIA_ROOT` | AI 创作素材库落盘目录（**本地磁盘**，留空 = `backend/data/media`） | 空 |
| `MEDIA_MAX_MB` | 素材单文件上限 | `20` |
| `TOS_*` | 对象存储（可选；素材库暂未使用，换 OSS 时替换 `media_store.py`） | — |
| `JWT_SECRET_KEY` | 令牌签名，**生产必须修改** | 开发占位值 |

### 设置：模型信息（按板块配模型）

左侧全局工具新增「设置」入口，回答的是「模型到底该配在代码里还是设置里」——**分层，不二选一**：

| 内容 | 放哪 | 为什么 |
| --- | --- | --- |
| API Key / base_url / provider 默认端点 | `backend/.env`（代码配置） | 开源自托管：密钥进 DB 会随备份泄露，多实例也难保持一致；设置页不保存、不回显密钥 |
| 各业务板块用哪个 provider / 哪个模型 | 设置页 → `model_settings` 表 | 运营参数，改一次不该重启；不同板块成本 / 质量诉求不同，自托管用户还得能填自己的端点 ID |
| 代码里的默认值 | `services/model_registry.py` 的 `SLOTS` / `PROVIDERS` | 空库、DB 挂掉时全站仍能跑，设置页只是 override |

关键是**统一解析器**：改造前 `deepseek-chat` / `gpt-4o-mini` / `qwen-plus` 硬编码散在十几个 service 里，每个还各写一遍 `if settings.deepseek_api_key else ...`，改设置页不改调用点就只是摆设。现在所有调用点统一走 `model_registry.resolve(slot)` / `openai_client(slot)` / `credentials(slot)`，板块按业务划分、不按文件划分：

- **在线服务**：在线客服对话、Agent 编排、知识库问答
- **数据与评测**：质检与质量评分、知识抽取、知识蒸馏与改写、数据清洗判定、考核出题与评分、训练数据生成
- **专用能力与预留**：文本向量化、图片信息提取、AI 创作 · 出图规划 / 图像生成（规划仍是规则引擎；出图已改由**图像端点池**驱动，见下一节，与这套「板块选文本模型」是两套机制）

`auto` 模式的优先级**刻意沿用改造前每个服务各自的顺序**（多数板块 DeepSeek → OpenAI，知识问答 / 抽取 Ark → DeepSeek → OpenAI），避免「只给 Embedding 配了 `ARK_API_KEY`，质检就莫名切到 qwen-plus」这类串线。用户显式选的 provider 不受优先级限制，可以切到任意能力兼容端点。

保存后清掉 registry 的进程内缓存，下一次业务调用即生效、不用重启；多实例部署下其他实例最多 20 秒后自动跟上。设置页每个板块可先「测试」再保存（用临时配置发一次 `max_tokens=8` 的最小请求，不写库），也可一键「恢复默认」。

```bash
TOKEN=<登录后的 access_token>
BASE=http://localhost:8100
# 设置页数据：分组 / 板块生效配置 / provider 是否已配置（不含密钥）
curl -H "Authorization: Bearer $TOKEN" "$BASE/api/model-settings"
# 只提交要改的板块；provider=auto + model 留空 = 自动挑 + 用 provider 默认模型
curl -X PUT -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"slots":{"qc":{"provider":"openai","model":"gpt-4o-mini"}}}' "$BASE/api/model-settings"
# 连通性自检（可带临时 provider/model，不写库）
curl -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"slot":"qc","provider":"openai","model":"gpt-4o-mini"}' "$BASE/api/model-settings/test"
# 恢复代码默认
curl -X DELETE -H "Authorization: Bearer $TOKEN" "$BASE/api/model-settings/qc"
```

两个约定：Embedding 板块只能选 Embedding provider（反之亦然），否则返回 400；质检配置页里的 `model` 字段留空即跟随设置页，填了则那套质检标准单独覆盖。

### AI 创作：当前实现边界

| 层 | 状态 | 说明 |
| --- | --- | --- |
| 素材库 | 已实现 | 上传 / 去重 / 检索 / 删除 / 静态直出，文件落 `backend/data/media` |
| 两级分类目录 | 已实现 | `media_categories` 表 + `media_assets.category`；目录树 / 新建 / 删除 / 筛选 / 移动；素材只存目录 key，删目录不删图 |
| 一级显示名可编辑 | 已实现 | 五个 key 固定，显示名存 `media_kind_labels`，素材库里双击 / 铅笔改名，可恢复默认；目录树、上传区、选图弹窗、槽位提示、素材卡片全部读同一份 tree |
| 弹窗选图器 | 已实现 | `StudioAssetPickerModal`：两级目录树 + 大图网格 + 搜索 + 多选上限，确认后一次写回；另一 Tab 就地上传并自动进入待选。弹窗自行按目录/关键词查后端，不受「最近 100 张」限制 |
| 槽位回显 | 已实现 | 已选素材按 id 精确回查（`GET /api/media/list?ids=`），旧任务里的老图也能显示缩略图 |
| 任务表与轮询 | 已实现 | `studio_tasks`，`BackgroundTasks` 后台执行，`progress` 轮询 |
| 两阶段闸门 | 已实现 | 同步产出逐图规划并停在 `planned`，人工确认后才触发执行 |
| 功能专属输入 | 已实现 | `studioKinds.ts` 定义每个功能的素材角色与选项；后端 `KIND_CONFIG` 白名单清洗后按 kind 生成不同规划（SKU 按新品逐个、精修按修复项、组图按搭配组合） |
| 规划引擎 | 规则模板 | `studio_task_service.build_plan()`，每张 shot 带 `meta` 专属元信息 + `capability` 能力标签；结构与未来 LLM 输出一致，可直接替换 |
| 图像端点池 | 已实现 | `image_endpoints` 表，端点可任意多个；协议 `webhook` / `openai_images` / `volc_ark` / `mock`；密钥 `none` / `env` / `inline` 三模式，接口只回掩码 |
| 服务绑定与动态分派 | 已实现 | `image_endpoint_bindings` 存有序候选链（可按能力覆盖）；`image_gateway.process_image()` 按「服务 + 能力 + 本次端点」解析链，逐个协议适配器尝试，失败自动 fallback |
| 运行时端点选择 | 已实现 | 任务创建可传 `endpoint_key` / `endpoint_params`，本次覆盖提前但不砍 fallback；规划卡提前标注每张镜头将用哪个端点，确认前可改并重新规划 |
| 单图即席处理 | 已实现 | `POST /api/image/process` 对素材库里一张已有图选动作 + 选端点，走同一网关，结果回写素材库并记 `image_process_jobs` |
| 出图引擎 | 网关 / 占位图兜底 | 有可用真实端点时由端点出图；没配端点或全链失败才回落 `_render_shot()` 的 PIL 占位图，并在 `outputs.routes` 里如实标注 |
| 视觉 / 图像模型 | 需自配端点 | 本仓库不内置第三方模型凭证；在「图像端点」页注册自己的端点即可，无需改代码 |

素材文件与 `media_assets` 表可能因进程中断出现不一致，配套两个运维接口：

```bash
TOKEN=<登录后的 access_token>
BASE=http://localhost:8100
# 只读检查：返回 missing（表有文件没了）/ orphan（磁盘有表里没记录）/ ok
curl -H "Authorization: Bearer $TOKEN" "$BASE/api/media/files-check"
# 清理预览（默认 dry_run，不删任何东西）
curl -X POST -H "Authorization: Bearer $TOKEN" "$BASE/api/media/files-cleanup"
# 确认无误后真删；只删 MEDIA_ROOT 内的无主文件，不碰已登记素材
curl -X POST -H "Authorization: Bearer $TOKEN" "$BASE/api/media/files-cleanup?apply=true"
```

两级分类目录接口：`GET /api/media/categories` 返回带计数的目录树；`POST /api/media/categories` 新建二级目录（`{kind, label}`，同名幂等）；`DELETE /api/media/categories/{id}` 删自定义目录（预置目录返回 409，素材移到未归类）。上传 `POST /api/media/upload` 与列表 `GET /api/media/list` 都吃 `category` 参数，`_uncategorized` 表示未归类；`PATCH /api/media/{id}` 可移动目录。

两个容易踩的约束：二级目录 key 只在一级内唯一（`product.detail` 与 `result.detail` 是两个目录），所以按具体 `category` 查询**必须同时传 `kind`**，否则返回 400；`GET /api/media/list?ids=1&ids=2` 按 id 精确取，用于任务回显已选素材，不受分页与目录筛选影响。

```bash
# 目录树（一级 / 二级 / 各节点素材数 / 未归类数）
curl -H "Authorization: Bearer $TOKEN" "$BASE/api/media/categories"
# 只取「商品图 / 白底图」
curl -H "Authorization: Bearer $TOKEN" "$BASE/api/media/list?kind=product&category=white_bg"
# 只取未归类素材
curl -H "Authorization: Bearer $TOKEN" "$BASE/api/media/list?category=_uncategorized"
# 新建自定义目录；中文目录名不用做 slug，后端生成短 key、显示名单独存 label
curl -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"kind":"product","label":"秋季新款"}' "$BASE/api/media/categories"
# 改一级目录的显示名（key product 不变；1-20 字，未知 key / 空名返回 400）
curl -X PATCH -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"label":"货品图"}' "$BASE/api/media/kind-labels/product"
# 恢复代码默认名
curl -X DELETE -H "Authorization: Bearer $TOKEN" "$BASE/api/media/kind-labels/product"
```

`GET /api/media/categories` 返回的每个一级节点带 `label`（生效名）、`default_label`（代码默认名）、
`custom`（是否被改过）。前端所有显示一级名的地方都从这份目录树读，不再硬编码在组件里。

### AI 创作：图像端点池、服务绑定与运行时选择

「设置 → 模型信息」解决的是**文本模型按板块选哪个**；图像这边是另一套机制，因为出图要按**动作**分派，而且端点数量不受限制：

| 层 | 存在哪 | 职责 |
| --- | --- | --- |
| 端点池 | `image_endpoints` | 任意多个端点。每个声明协议、base_url、模型名、能力标签、密钥模式、默认参数、最大参考图数、超时、优先级 |
| 服务绑定 | `image_endpoint_bindings` | 每个服务一条**有序候选链**（`service + capability` 为键，`capability=""` 是默认链）；顺序就是 fallback 顺序，具体动作链优先于默认链 |
| 运行时选择 | 任务入参 `endpoint_key` | 只把本次指定的端点**提前到链首**，后面的 fallback 一个都不砍；不改绑定数据 |

8 类能力标签：`txt2img` / `img2img` / `inpaint` / `remove_bg` / `upscale` / `outpaint` / `style_transfer` / `tryon`。规划阶段 `infer_capability()` 把镜头标题翻译成能力，`image_gateway.process_image()` 再解析候选链逐个尝试协议适配器；每张结果都记下实际命中的端点、协议、耗时与失败尝试。内置 `_mock` 端点永远在链尾，任何配置下链路都能跑完。

密钥有三种模式：`none`（本地自托管）、`env`（**推荐**，只填环境变量名，密钥留在 `.env`）、`inline`（存 DB）。接口只回 `secret_source` / `secret_masked` / `secret_ready`，不回明文。本机地址（`127.0.0.1` / `localhost`）会自动绕过 `HTTP_PROXY`，否则公司代理会吃掉 ComfyUI 这类自托管端点的请求。

```bash
TOKEN=<登录后的 access_token>
BASE=http://localhost:8100
# 端点页全量数据：能力/协议/服务字典 + 端点池（脱敏）+ 绑定矩阵
curl -H "Authorization: Bearer $TOKEN" "$BASE/api/image/endpoints"
# 注册一个自托管端点（none 模式 + webhook 协议 + 声明能力）
curl -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"key":"comfy-main","name":"本地 ComfyUI","protocol":"webhook",
       "base_url":"http://127.0.0.1:8188/generate","auth_mode":"none",
       "capabilities":["img2img","inpaint","remove_bg"],"max_refs":4,"timeout_s":60}' \
  "$BASE/api/image/endpoints"
# 只测这一个端点（single 模式，不触发 fallback）
curl -X POST -H "Authorization: Bearer $TOKEN" "$BASE/api/image/endpoints/comfy-main/test"
# 给「精修」绑定候选链；顺序 = fallback 顺序
curl -X PUT -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"service":"retouch","capability":"","keys":["comfy-main"]}' "$BASE/api/image/bindings"
# 按动作单独配链（优先于默认链）
curl -X PUT -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"service":"retouch","capability":"remove_bg","keys":["comfy-main"]}' "$BASE/api/image/bindings"
# 素材库单图即席处理；结果写回素材库
curl -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"asset_id":15,"operation":"remove_bg","params":{"prompt":"换成纯白背景"}}' \
  "$BASE/api/image/process"
curl -H "Authorization: Bearer $TOKEN" "$BASE/api/image/jobs?asset_id=15"
```

出图任务侧：`POST /api/studio/tasks` 可带 `endpoint_key` / `endpoint_params`；`GET /api/studio/engine` 会返回 `is_mock` 与 `endpoint_count`，前端据此标注「网关已就位」还是「占位图兜底」。任务 `outputs.routes` 是逐镜头的实际路由记录。

两个实现约束值得留意：

- **生成结果按 sha256 去重**。同内容只存一份（`media_assets.sha256` 有唯一索引），端点反复返回同一张图或重跑任务时复用已有素材并删掉刚落盘的副本；否则唯一键冲突会污染事务，后台任务会永远卡在 `running` / `generating`。出图任务与即席处理都走 `media_assets.create_generated_asset()` 这一个入口。
- **后台任务是进程内的**。`uvicorn --reload`、容器重建、进程被 kill 都会打断执行；出图任务有启动回收 + 90 秒 stale sweep + 前端「重跑」，即席处理任务异常会落 `failed` 并打印堆栈，不会静默卡住。开发时务必用 `--reload-dir app`（只监听代码目录），否则每写出一张图都会触发 reload。

首次启动会 seed 一个 `_mock` 兜底端点与每个服务的默认链。仓库里另外配了三个 `demo-*` 示例端点（缺密钥 / 停用状态），只用于展示端点池与绑定链界面，不会被网关真的调用；把它们改成自己的真实配置即可。

未来切 OSS：只替换 `app/services/media_store.py` 这一层，`media_assets` 表结构、
`/api/media/*` 接口和前端契约都不用动（详见 `docs/plans/picsetai-replication-plan.html`）。

---

## 目录结构

```
backend/app/
├── main.py                  入口：建表、注册 23 个 router、seed 兜底端点与目录、Agent 预热
├── config.py                pydantic-settings 环境变量
├── routers/                 API 模块（media.py 素材库 / studio.py 出图任务 /
│                            image_endpoints.py 端点与即席处理 / model_settings.py 设置页）
├── services/
│   ├── deep_agent.py        deepagents 引擎：中间件栈、子 Agent、HITL、resume
│   ├── langgraph_agent.py   LangGraph 引擎：StateGraph 手写实现
│   ├── dialog_state.py      DST：槽位、阶段、意图延续、共指消解
│   ├── intent_recognition.py 意图识别（词典 + LLM 两级）
│   ├── ticket_service.py    工单全生命周期 + 审批挂起/决策
│   ├── refund_store.py      退款受理仓（RMA 号唯一来源）
│   ├── model_registry.py    文本模型统一解析器：13 板块 / 5 provider / 20s 缓存
│   ├── media_store.py       素材落盘（本地磁盘，换 OSS 只改这一层）
│   ├── media_assets.py      生成图入库统一入口（sha256 去重，规避唯一键冲突）
│   ├── media_categories.py  两级目录 + 一级显示名：seed / 目录树 / 归属校验 / 改名
│   ├── image_endpoints.py   端点注册表、服务绑定与候选链解析
│   ├── image_gateway.py     图像网关：按能力分派 / 协议适配 / fallback / mock 兜底
│   ├── image_process.py     素材库单图即席处理（走同一网关）
│   ├── studio_task_service.py 两阶段任务：按 kind 规划 / 端点标注 / 僵尸任务自愈
│   ├── sft_service.py       SFT 训练样本提取与导出
│   ├── dpo_service.py       DPO 偏好对生成、标注与导出
│   ├── tools/               工具基类、注册表、MCP 客户端
│   └── etl.py · quality_inspection.py · qc_calibration.py  数据与质检流水线
└── models/                  SQLAlchemy 模型（39 张表；数据库共 49 张，另 10 张为框架 / 服务内建表）

frontend/src/
├── App.tsx                  视图路由分发
├── appRoutes.ts             ViewMode 与 URL 映射（含 /settings 与 /studio/*）
├── api.ts                   全部接口的类型与调用
├── navigation.ts            IA 唯一真源（4 个工作区 / 5 个功能组 / 面包屑）
├── studioSpec.ts            AI 创作各功能的输入输出与能力缺口
├── studioKinds.ts           五个出图功能各自的输入契约（素材角色 + 专属选项 + 默认目录）
├── mediaCategories.ts       两级目录展示层公共逻辑（一级显示名统一入口）
└── components/              AgentWorkbench / TicketView / QualityCheckView
                             SettingsView / WorkbenchView / GlobalOverviewView
                             StudioWorkbench / StudioAssets / StudioTaskRunner
                             StudioEndpoints / StudioEndpointChooser
                             StudioImageProcessModal / StudioAssetPickerModal
                             StudioAssetSlotPicker / StudioPaneView
```

---

## 核心设计

### 1. 每轮对话一个 thread

`thread_id` 为 `{session_id}:t{turn_count}`，而非会话 ID。原因：LangGraph 的 `messages` 是追加语义，`invoke` 是合并而非替换，整会话共用一个 thread 会导致历史线性膨胀；每轮独立 thread 则恒定为 2 条。

跨轮记忆交给 `dialog_states` + `agent_messages` 两张表，checkpoint 只负责"这一轮跑到哪"。

> 代价：**resume 必须落在同一 thread**。用新 thread 调 `Command(resume=...)` 不报错，而是另起空图再中断一次——静默失败。因此挂起时把 `thread_id` 显式写入工单的 `pending_action`。

### 2. 审批闸门放在中间件

```python
HumanInTheLoopMiddleware(
    interrupt_on={
        "submit_refund": {
            "allowed_decisions": ["approve", "reject"],
            "when": _refund_needs_approval,   # 条件拦截：真会动钱才停
        }
    },
    interrupt_mode="batched",
)
```

无条件拦截会让每次退款咨询都变工单；改成"订单存在且判定可退"才停，闸门才只拦真正花钱的那一下。

被拦截后 `invoke` 正常返回（带 `__interrupt__`），应用层建工单并生成话术。**话术用确定性模板，不走 LLM**——模型常说"我这就提交"，而工具实际未执行，金额与单号也不能给它编造空间。

### 3. 工具矩阵

| 来源 | 工具 | 说明 |
| --- | --- | --- |
| 内置 | `query_order` `list_recent_orders` `check_logistics` | 订单与物流（本地 Mock） |
| 内置 | `create_ticket` | 建单幂等：同会话同分类复用 |
| 内置 | `submit_refund` | **唯一挂审批闸门的工具** |
| 内置 | `rag_knowledge` | 知识库检索（pgvector） |
| 动态 | `skill_<id>` | Skill 的 SOP 文本包成工具 |
| 动态 | `mcp_<server>` | 挂载外部 MCP 服务 |

工具的上下文（`session_id` / `user_id`）由闭包注入，模型无需传参。

### 4. 离线数据闭环

```
微信 SQLite ──ETL──▶ raw_chats ──预处理──▶ staging_conversations ──人工审核──▶ labeled_conversations
                                                                          │
                     knowledge_articles / knowledge_chunks ◀──知识提炼────┘
                                  │
                                  ├──▶ pgvector 检索（RAG）
                                  ├──▶ quality_inspections（质检）
                                  ├──▶ sft_training_samples（SFT 微调）
                                  └──▶ dpo_preference_pairs（DPO 偏好对齐）
```

- **审核是硬闸门**：AI 只能推进到 staging，进 labeled 必须过人；质检与训练数据只吃 labeled。
- **ETL 有时间下限**（2025-10-01 起），老数据不入库，避免污染知识库。
- **校准单独存放**，不污染线上质检统计。

### 数据模型

数据库共 49 张表，其中 39 张由 `models/` 定义、启动时 `create_all` 建出：

| 分组 | 表 |
| --- | --- |
| 原始数据 | `contacts` `sessions` `raw_chats` |
| 加工数据 | `staging_conversations` `labeled_conversations` `knowledge_articles` `knowledge_chunks` |
| Agent 运行 | `agent_sessions` `agent_messages` `intent_records` `emotion_records` `transfer_decisions` |
| 工单 | `tickets` `ticket_events` |
| 质检 | `quality_inspections` `quality_inspection_configs` `qc_config_versions` `qc_calibration_*` |
| 训练数据 | `sft_training_samples` `dpo_preference_pairs` `training_jobs` |
| 设置 | `model_settings`（各板块模型选择；不存密钥） |
| AI 创作 · 素材 | `media_assets`（文件在本地磁盘） · `media_categories` · `media_kind_labels` |
| AI 创作 · 任务 | `studio_tasks` |
| AI 创作 · 图像端点 | `image_endpoints` · `image_endpoint_bindings` · `image_process_jobs` |

其余 10 张表不在 ORM 内：服务内建表（`dialog_states` / `refund_requests` / `students` 等）、框架表（`checkpoints` 系列）、历史遗留表。

---

## API 概览

| 分组 | 端点 | 说明 |
| --- | --- | --- |
| Agent | `POST /api/agent/message/stream` | 流式对话，SSE 事件 `metadata / token / answer / done` |
| | `GET /api/agent/sessions` · `GET /api/agent/sessions/{id}/messages` | 会话列表与历史 |
| | `GET /api/agent/engine` · `POST /api/agent/intent/detect` | 当前引擎 / 单独试意图 |
| 工单 | `GET /api/ticket/list` | 支持 `status/category/keyword/session_id` 过滤 |
| | `POST /api/ticket/{id}/decision` | **审批**：approve / reject，触发 resume |
| | `GET /api/ticket/history/{session_id}` | 会话全部工单 |
| 质检 | `GET /api/qc/stats/summary` · `POST /api/qc/inspect` · `POST /api/qc/batch` | 评分与批量质检 |
| | `POST /api/qc/calibration/groups/{id}/run` | 用指定配置版本重跑并对比真值 |
| 数据 | `GET /api/chats/sessions` · `GET /api/search` | 会话与全文检索 |
| | `POST /api/labeling/*` · `POST /api/export/*` | 标注与数据集导出 |
| 训练 | `POST /api/training/sft/extract` · `POST /api/training/dpo/generate` | SFT 样本提取 / DPO 偏好对生成 |
| | `POST /api/training/dpo/pairs/{id}/annotate` · `POST /api/training/*/export` | 标注 / 导出 |
| 能力 | `GET /api/skills/list` · `GET /api/mcp/servers` | Skill 与 MCP 管理 |
| 设置 | `GET/PUT /api/model-settings` · `DELETE /api/model-settings/{slot}` · `POST /api/model-settings/test` | 板块模型选择 / 恢复默认 / 连通性自检 |
| AI 创作 · 素材 | `GET/POST/PATCH/DELETE /api/media/*` | 上传 / 目录树 / 列表 / 移动 / 删除 / 一致性检查；文件经 `/api/media/files/*` 静态直出 |
| AI 创作 · 任务 | `POST /api/studio/tasks` · `POST /api/studio/tasks/{id}/confirm` · `GET /api/studio/tasks/{id}` · `GET /api/studio/engine` | 规划 → 人工确认 → 后台执行 → 轮询；创建可带 `endpoint_key` / `endpoint_params` |
| AI 创作 · 图像端点 | `GET/POST/PATCH/DELETE /api/image/endpoints*` · `PUT /api/image/bindings` · `POST /api/image/process` · `GET /api/image/jobs` | 端点池 / 连通测试 / 候选链绑定 / 单图即席处理 |

完整 OpenAPI schema：服务启动后访问 `/docs`。

---

## 生产部署

```bash
docker compose up -d --build
```

三容器：

| 容器 | 端口 | 说明 |
| --- | --- | --- |
| `db` | 5433:5432 | PostgreSQL 17 + pgvector |
| `backend` | 8000 | FastAPI |
| `frontend` | 80 | nginx，反向代理 `/api` 到 backend |

部署前必改：`JWT_SECRET_KEY`、`DATABASE_URL`、模型 API Key。更详细的说明见 [DEPLOY.md](DEPLOY.md)。

---

## 已知限制

以下是明确未实现的功能，不是 bug：

- **无双引擎等价性测试**：两套引擎共享工具与 prompt 契约，但输出未逐字对齐，切换后话术会变。
- **无数据库迁移版本管理**：靠 `create_all` + `schema_sync` 补列，删列/改类型需手工。
- **Mock 业务系统**：订单、物流、退款仓为本地 Mock（`order_store` / `refund_store`），接真实系统需替换工具实现，接口契约可复用。
- **DPO 偏好对为规则生成**：rejected 由错误类型模板合成，非真实模型采样，用于打通流程；生产建议替换为真实采样 + 人工标注。
- **不内置图像模型凭证**：出图规划仍是规则模板（不用 LLM）；真图完全依赖在「端点池」注册自己的端点，没配端点或全链失败会产出带 `MOCK` 标识的占位图，并在 `outputs.routes` 里如实留痕。
- **出图与即席处理是进程内后台任务**：容器重建 / 进程被 kill 会打断执行；出图任务有启动回收 + 90 秒 stale sweep + 前端「重跑」，即席处理异常会落 `failed` 并打印堆栈。生产若需跨进程可靠性，应换成独立任务队列。

---

## 许可证

- 代码：[Apache-2.0](LICENSE)
- 第三方资料边界：[NOTICE](NOTICE)
- 作者：[clearwind](https://github.com/clearwind)
