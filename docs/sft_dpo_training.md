# SFT → DPO 两阶段训练路径实现文档

## 概述

本文档描述如何实现 **SFT（监督微调）→ DPO（直接偏好优化）** 两阶段训练路径，用于提升小蚕惠生活客服 Agent 的回答质量。

### 训练目标
1. **SFT 阶段**：解决客服语气模仿，让模型学会专业亲和的客服话术风格
2. **DPO 阶段**：对同一业务问题采样多条回复，由业务主管标注 chosen/rejected 偏好对，训练模型区分优劣

### 优势
- DPO overhead 较低（不需要额外的 reward model）
- 性能更稳定（直接优化偏好，避免 RLHF 的训练不稳定性）
- 充分利用现有聊天记录数据

---

## 系统架构

### 数据流

```
微信聊天记录 → 清洗/切分 → SFT训练样本 → 导出ShareGPT格式
                                        ↓
                              多Agent生成候选回复
                                        ↓
                              DPO偏好对（chosen/rejected）
                                        ↓
                              业务主管标注 → 导出DPO格式
                                        ↓
                              Stage1: SFT微调
                                        ↓
                              Stage2: DPO对齐
                                        ↓
                              最终客服模型
```

### 核心组件

| 组件 | 文件 | 职责 |
|------|------|------|
| 数据模型 | `app/models/dpo.py` | SFT样本、DPO偏好对、训练任务表 |
| SFT服务 | `app/services/sft_service.py` | 从聊天记录提取SFT训练样本 |
| DPO服务 | `app/services/dpo_service.py` | 生成、标注、管理DPO偏好对 |
| API路由 | `app/routers/training.py` | 训练数据管理REST接口 |
| 前端页面 | `frontend/src/components/TrainingView.tsx` | 训练数据管理界面 |

---

## 数据库表结构

### 1. dpo_preference_pairs (DPO偏好对表)

```sql
CREATE TABLE dpo_preference_pairs (
    id VARCHAR(16) PRIMARY KEY,
    prompt TEXT NOT NULL,                    -- 用户原始问题
    business_category VARCHAR(50),           -- 业务分类
    scenario_description TEXT,               -- 场景描述
    
    candidate_replies JSONB,                 -- 候选回复列表
    -- [{"index": 0, "reply": "...", "source": "agent/complaint_agent"}, ...]
    
    chosen_index INTEGER NOT NULL,           -- 选中的回复索引
    rejected_indices JSONB,                  -- 被拒绝的索引列表
    preference_type VARCHAR(50),             -- compliance/tone/efficiency/empathy
    
    annotation_status VARCHAR(20),           -- pending/annotated/reviewed/rejected
    annotated_by VARCHAR(100),               -- 标注人
    annotated_at TIMESTAMP,
    annotation_notes TEXT,                   -- 标注备注
    
    quality_score FLOAT,                     -- 整体质量分 0-10
    difficulty_level VARCHAR(20),            -- easy/medium/hard
    
    source_session_id VARCHAR(100),          -- 来源会话ID
    source_message_ids JSONB,                -- 原始消息ID列表
    
    version INTEGER DEFAULT 1,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

### 2. sft_training_samples (SFT训练样本表)

```sql
CREATE TABLE sft_training_samples (
    id VARCHAR(16) PRIMARY KEY,
    instruction TEXT NOT NULL,               -- 用户问题/指令
    input_context TEXT,                      -- 上下文输入
    output TEXT NOT NULL,                    -- 期望回复
    
    system_prompt TEXT,                      -- 系统提示词
    
    category VARCHAR(50),                    -- 业务分类
    quality_score FLOAT,                     -- 质量分 0-10
    difficulty_level VARCHAR(20),            -- 难度
    
    source_type VARCHAR(20),                 -- chat/labeled/custom/generated
    source_id VARCHAR(100),
    source_session_id VARCHAR(100),
    
    is_approved BOOLEAN DEFAULT TRUE,
    reviewed_by VARCHAR(100),
    reviewed_at TIMESTAMP,
    
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

### 3. training_jobs (训练任务表)

```sql
CREATE TABLE training_jobs (
    id SERIAL PRIMARY KEY,
    job_type VARCHAR(20) NOT NULL,           -- sft/dpo
    job_name VARCHAR(200) NOT NULL,
    base_model VARCHAR(200),
    dataset_id VARCHAR(100),
    
    config_json JSONB,                       -- 训练参数配置
    
    status VARCHAR(20) DEFAULT 'pending',    -- pending/running/success/failed/cancelled
    progress FLOAT DEFAULT 0.0,              -- 进度 0-100
    logs TEXT,                               -- 训练日志
    
    model_path VARCHAR(500),                 -- 输出模型路径
    metrics_json JSONB,                      -- 评估指标
    
    created_by VARCHAR(100),
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW()
);
```

---

## API 接口清单

### SFT 训练数据接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/training/sft/samples` | 获取SFT样本列表 |
| POST | `/api/training/sft/extract` | 从聊天记录提取SFT样本 |
| POST | `/api/training/sft/export` | 导出SFT训练数据 |

### DPO 偏好对接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/training/dpo/pairs` | 获取DPO偏好对列表 |
| GET | `/api/training/dpo/pairs/{id}` | 获取偏好对详情 |
| POST | `/api/training/dpo/generate` | 自动生成DPO偏好对 |
| POST | `/api/training/dpo/pairs/{id}/annotate` | 标注偏好对 |
| POST | `/api/training/dpo/export` | 导出DPO训练数据 |
| GET | `/api/training/dpo/statistics` | 获取DPO统计信息 |

### 训练任务接口

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/training/jobs` | 创建训练任务 |
| GET | `/api/training/jobs` | 获取训练任务列表 |
| GET | `/api/training/jobs/{id}` | 获取训练任务详情 |
| PUT | `/api/training/jobs/{id}/status` | 更新任务状态 |
| PUT | `/api/training/jobs/{id}/complete` | 标记任务完成 |

### 统计接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/training/statistics` | 获取训练数据统计概览 |

---

## 使用流程

### 第一阶段：准备 SFT 数据

1. **提取训练样本**
   ```bash
   curl -X POST "http://127.0.0.1:8100/api/training/sft/extract?min_quality=medium&max_samples=500"
   ```

2. **查看和审核样本**
   - 在前端「训练数据」页面查看 SFT 样本列表
   - 对低质量样本进行筛选或修改

3. **导出 SFT 数据**
   ```bash
   curl -X POST "http://127.0.0.1:8100/api/training/sft/export" \
     -H "Content-Type: application/json" \
     -d '{"format": "sharegpt", "categories": ["complaint", "order_problem"]}'
   ```

### 第二阶段：准备 DPO 数据

1. **生成偏好对**
   ```bash
   curl -X POST "http://127.0.0.1:8100/api/training/dpo/generate" \
     -H "Content-Type: application/json" \
     -d '{"min_quality": "medium", "max_pairs": 200}
   ```

2. **业务主管标注**
   - 在前端查看生成的偏好对
   - 对每个问题的多条回复进行标注：
     - 选择最优回复（chosen）
     - 标注拒绝原因（算错运费、态度生硬等）

3. **导出 DPO 数据**
   ```bash
   curl -X POST "http://127.0.0.1:8100/api/training/dpo/export" \
     -H "Content-Type: application/json" \
     -d '{"format": "dpo"}'
   ```

### 第三阶段：执行训练

#### SFT 训练命令示例

```bash
# 使用 LLaMA-Factory 进行 SFT
python src/train.py \
    --model_name_or_path Qwen/Qwen2.5-7B-Instruct \
    --dataset sft_data.json \
    --dataset_format sharegpt \
    --output_dir ./output/sft_model \
    --num_train_epochs 3 \
    --per_device_train_batch_size 16 \
    --learning_rate 2e-5 \
    --cutoff_len 512 \
    --logging_steps 10 \
    --save_steps 100 \
    --evaluation_steps 100
```

#### DPO 训练命令示例

```bash
# 使用 TRL 库进行 DPO
python src/train_dpo.py \
    --model_name_or_path ./output/sft_model \
    --dataset dpo_data.json \
    --dataset_format dpo \
    --output_dir ./output/dpo_model \
    --num_train_epochs 1 \
    --per_device_train_batch_size 4 \
    --learning_rate 5e-6 \
    --beta 0.1 \
    --logging_steps 10 \
    --save_steps 50
```

---

## 标注规范

### chosen（选中回复）标准

1. **合规性**：符合平台规则和业务政策
2. **准确性**：金额计算正确，信息准确无误
3. **专业性**：语气专业，表达清晰有条理
4. **亲和力**：态度友好，适当使用「您」「请」等敬语

### rejected（拒绝回复）常见原因

1. **算错运费/金额**： rebate 计算错误
2. **态度生硬**：语气冷淡、推诿责任
3. **违反合规**：诱导差评、承诺无法兑现
4. **信息错误**：给出过期的规则或政策

---

## 数据质量要求

### SFT 样本质量等级

| 等级 | 分数 | 标准 |
|------|------|------|
| HIGH | ≥ 7.0 | 完整问答、高价值关键词、专业回复 |
| MEDIUM | ≥ 4.0 | 有价值但可能不完整 |
| LOW | ≥ 2.0 | 碎片化内容 |
| REJECTED | < 2.0 | 无意义、敏感、重复 |

### DPO 偏好对要求

- 每个问题至少 2 条候选回复
- chosen 和 rejected 要有明显差异
- 覆盖主要业务场景（投诉、订单、返利、优惠券等）
- 标注需由业务主管完成

---

## 扩展建议

### 未来可以添加的功能

1. **自动标注助手**
   - 使用 LLM 辅助生成初始标注建议
   - 人工只需审核和微调

2. **主动学习**
   - 识别模型不确定的样本优先标注
   - 提高标注效率

3. **训练效果评估**
   - 对比训练前后模型的回复质量
   - 自动化测试集评估

4. **在线学习**
   - 新对话自动加入训练数据
   - 定期增量训练

---

## 相关文件

- 数据库模型：`backend/app/models/dpo.py`
- SFT 服务：`backend/app/services/sft_service.py`
- DPO 服务：`backend/app/services/dpo_service.py`
- API 路由：`backend/app/routers/training.py`
- 前端页面：`frontend/src/components/TrainingView.tsx`
- API 定义：`frontend/src/api.ts`（新增训练相关接口）

