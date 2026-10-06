-- 创建子Agent配置表
CREATE TABLE IF NOT EXISTS agent_configs (
    id SERIAL PRIMARY KEY,
    agent_id VARCHAR(100) UNIQUE NOT NULL,
    name VARCHAR(200) NOT NULL,
    description TEXT,
    agent_type VARCHAR(50) NOT NULL,
    status VARCHAR(20) DEFAULT 'inactive',
    priority INTEGER DEFAULT 50,

    -- 路由配置
    supported_intents JSONB,
    supported_emotions JSONB,
    supported_phases JSONB,

    -- Agent逻辑配置
    config_json TEXT,
    prompt_template TEXT,

    -- 元数据
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(100)
);

-- 创建索引
CREATE INDEX IF NOT EXISTS idx_agent_configs_agent_id ON agent_configs(agent_id);
CREATE INDEX IF NOT EXISTS idx_agent_configs_status ON agent_configs(status);
CREATE INDEX IF NOT EXISTS idx_agent_configs_type ON agent_configs(agent_type);

-- 插入默认子Agent配置
INSERT INTO agent_configs (agent_id, name, description, agent_type, status, priority, supported_intents, supported_emotions)
VALUES
('faq_agent', 'FAQ回答Agent', '基于RAG知识库回答常见问题', 'faq', 'active', 10,
 '["order_status", "logistics", "product_inquiry", "general_faq"]',
 'null'),

('dialogue_agent', '多轮对话Agent', '管理退货退款等复杂场景的多轮对话', 'dialogue', 'active', 20,
 '["refund_return"]',
 'null'),

('complaint_agent', '投诉处理Agent', '处理客户投诉和负面情绪', 'complaint', 'active', 5,
 '["complaint"]',
 '["anger", "anxiety", "disappointment"]')
ON CONFLICT (agent_id) DO NOTHING;

-- 创建意图识别记录表
CREATE TABLE IF NOT EXISTS intent_records (
    id SERIAL PRIMARY KEY,
    session_id VARCHAR(100) NOT NULL,
    turn_number INTEGER NOT NULL,
    user_message TEXT NOT NULL,
    intent VARCHAR(50) NOT NULL,
    sub_intent VARCHAR(100),
    confidence INTEGER NOT NULL,
    emotion_type VARCHAR(50),
    emotion_intensity INTEGER,
    frustration_signals JSONB,
    routed_to_agent VARCHAR(100),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_intent_records_session ON intent_records(session_id);
CREATE INDEX IF NOT EXISTS idx_intent_records_intent ON intent_records(intent);
CREATE INDEX IF NOT EXISTS idx_intent_records_created ON intent_records(created_at);

-- 创建情绪检测记录表
CREATE TABLE IF NOT EXISTS emotion_records (
    id SERIAL PRIMARY KEY,
    session_id VARCHAR(100) NOT NULL,
    turn_number INTEGER NOT NULL,
    user_message TEXT NOT NULL,
    emotion_type VARCHAR(50) NOT NULL,
    intensity INTEGER NOT NULL,
    frustration_signals JSONB,
    emotion_trend VARCHAR(20),
    risk_score INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_emotion_records_session ON emotion_records(session_id);
CREATE INDEX IF NOT EXISTS idx_emotion_records_emotion ON emotion_records(emotion_type);

-- 创建转人工决策记录表
CREATE TABLE IF NOT EXISTS transfer_decisions (
    id SERIAL PRIMARY KEY,
    session_id VARCHAR(100) NOT NULL,
    decision_action VARCHAR(20) NOT NULL,
    decision_reason VARCHAR(50),
    risk_score INTEGER,
    triggered_signals JSONB,
    handoff_notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_transfer_decisions_session ON transfer_decisions(session_id);
CREATE INDEX IF NOT EXISTS idx_transfer_decisions_action ON transfer_decisions(decision_action);
