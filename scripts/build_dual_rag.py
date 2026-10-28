# -*- coding: utf-8 -*-
"""
方案 C：两库分离脚本

从 rag_cleaned.csv 生成：
1. rag_knowledge_base.csv  - 标准知识库（结构化 Q&A，50-80条）
2. rag_script_library.csv  - 话术参考库（保留口语风格，~350条）

用法:
    python scripts/build_dual_rag.py rag_cleaned.csv
"""
import csv
import re
import json
import sys
from collections import defaultdict
from typing import List, Dict, Tuple


# ==================== 知识库：核心问题 + 标准答案 ====================

# 按 intent 定义核心问题和标准答案
# 每个核心问题包含：canonical_question, variants, standard_answer, intent, tags
KNOWLEDGE_BASE = [
    # ==================== 课程内容咨询 ====================
    {
        "question": "AI应用开发课程包含哪些内容？",
        "variants": ["ai课程都有什么内容", "课程大纲是什么", "学什么内容", "课程介绍一下", "想了解下课程"],
        "answer": """课程主要围绕AI应用开发，核心内容包括：
1. Python基础（从零开始讲，语言上手很快）
2. AI框架：LangChain、LangGraph、RAG检索增强生成
3. AI Agent智能体开发
4. 大模型API对接（OpenAI、DeepSeek、Gemini、Claude等）
5. 实战项目：AI客服系统、知识库问答、智能体应用等

课程持续更新，紧跟AI行业最新技术栈""",
        "intent": "课程内容咨询",
        "tags": ["ai课程", "课程大纲", "langchain", "rag", "agent", "python"],
        "source": "课程大纲文档",
    },
    {
        "question": "课程的技术栈有哪些？",
        "variants": ["用什么技术", "学哪些框架", "需要学java吗", "用python还是java"],
        "answer": """课程以Python为主要语言，核心技术栈：
- 语言：Python（不需要Java八股文，AI开发只用Python就行）
- 框架：LangChain、LangGraph
- 核心技术：RAG、Agent、Prompt Engineering
- 大模型：OpenAI/GPT、DeepSeek、Gemini、Claude
- 工具：向量数据库、Embedding模型
- 前端可选：Next.js、React（有前端基础更好，但不是必须）

搞AI只用学个Python就行 语言而已上手很快""",
        "intent": "技术栈咨询",
        "tags": ["python", "langchain", "技术栈", "rag", "agent"],
        "source": "课程技术栈说明",
    },

    # ==================== 学习方式咨询 ====================
    {
        "question": "课程的学习方式是什么？线上还是线下？",
        "variants": ["是网课吗", "线上还是线下", "怎么上课", "视频课还是直播", "学习形式是什么"],
        "answer": """线上学习，三合一模式：
1. 加密视频课程 — 按规划顺序学，有播放器账号
2. 直播答疑 — 每周至少1场，包含面试辅导和简历辅导，有回放
3. 班级群答疑 — 随时问，同学之间也互相帮助

录播为主，不懂的群里问，学差不多了约模拟面试""",
        "intent": "学习方式咨询",
        "tags": ["学习方式", "线上", "视频课", "直播答疑", "班级群"],
        "source": "课程学习方式说明",
    },
    {
        "question": "直播回放在哪里看？",
        "variants": ["录屏有吗", "直播在哪看", "回放怎么看", "腾讯直播录屏"],
        "answer": """直播在微信直播平台进行，有回放可以看
班级群公告里有回放链接""",
        "intent": "学习方式咨询",
        "tags": ["直播", "回放", "微信直播"],
        "source": "课程学习方式说明",
    },

    # ==================== 学习周期咨询 ====================
    {
        "question": "课程要学多久？",
        "variants": ["学习周期多长", "多长时间能学完", "培训时间是多久", "几个月能学会"],
        "answer": """正常学习周期2-3个月
有编程基础的更快，很多同学学了一大半就出来试试水了
课程有效期较长，不用担心时间不够
在职的话每天下班学2-3小时，周末多学点，3个月差不多""",
        "intent": "学习周期咨询",
        "tags": ["学习周期", "时间", "2-3个月"],
        "source": "学习周期说明",
    },

    # ==================== 价格咨询 ====================
    {
        "question": "课程多少钱？怎么收费？",
        "variants": ["什么价格", "费用是多少", "怎么收费", "多少人民币", "课程价格"],
        "answer": """课程统一定价，经常有活动优惠
具体价格和最新优惠可以私聊教务老师获取
老学员有9折优惠""",
        "intent": "价格咨询",
        "tags": ["价格", "收费", "优惠"],
        "source": "价格与优惠政策",
    },
    {
        "question": "有优惠活动吗？老学员有折扣吗？",
        "variants": ["能便宜点吗", "有活动吗", "老学员优惠", "能打折吗"],
        "answer": """经常有活动优惠，可以关注最新动态
老学员统一9折，没有额外还价空间
支持15天无理由退款，可以先体验""",
        "intent": "优惠活动咨询",
        "tags": ["优惠", "折扣", "老学员", "活动"],
        "source": "价格与优惠政策",
    },

    # ==================== 就业前景咨询 ====================
    {
        "question": "AI应用开发的就业前景怎么样？",
        "variants": ["就业行情如何", "好找工作吗", "薪资水平怎样", "ai岗位多吗"],
        "answer": """目前AI应用开发岗位需求很大，行情非常好
薪资水平参考：
- 专科转AI：一线城市14-18k，二线10-15k
- 本科转AI：一线城市18-26k，看经验和能力
- 有开发经验转AI：涨幅明显，选择面很广

50%的企业在招做AI客服系统、知识库的岗位
AI的市场空间是万亿美元级别的，现在才刚刚开始""",
        "intent": "就业前景咨询",
        "tags": ["就业", "薪资", "行情", "岗位"],
        "source": "就业行情分析",
    },
    {
        "question": "学完课程能找到什么样的工作？",
        "variants": ["能做什么岗位", "就业方向", "找什么工作", "就业辅导"],
        "answer": """AI应用开发工程师方向，主要岗位：
1. AI应用开发工程师 — 开发AI驱动的应用系统
2. AI Agent开发 — 智能体和自动化系统
3. RAG工程师 — 知识库和检索增强系统
4. AI产品经理 — 懂技术又懂业务，无敌组合

学完课程会提供模拟面试辅导、简历包装指导
有产品经理/前端/后端背景的转AI就业面更广""",
        "intent": "就业前景咨询",
        "tags": ["岗位", "就业方向", "agent", "rag", "面试"],
        "source": "求职辅导手册",
    },

    # ==================== 转行可行性咨询 ====================
    {
        "question": "前端/后端开发转AI可行吗？",
        "variants": ["前端转ai", "java转ai", "后端转ai", "开发转ai"],
        "answer": """有开发经验转AI是最合适的，编程思维是相通的
前端/后端/Java/Python都可以转，Python上手很快
转AI之后就业面更广，不仅能面AI应用开发工程师，还能面AI产品经理
选择大于努力，AI的行情比传统前端/Java好太多了

很多学员就是Java/前端转的，薪资普遍有提升""",
        "intent": "转行可行性咨询",
        "tags": ["转行", "前端", "java", "python"],
        "source": "转行可行性分析",
    },
    {
        "question": "非技术背景可以转AI吗？产品经理/运营/设计",
        "variants": ["产品经理转ai", "运营转ai", "非技术", "没有编程基础转ai"],
        "answer": """非技术背景也可以学AI应用开发
课程从Python零基础开始讲，不需要提前有编程基础
产品经理转AI有独特优势：又懂业务又懂技术
运营/设计背景也可以，AI时代有AI辅助学习，没什么技能学不会

关键是要有学习的决心和时间投入""",
        "intent": "转行可行性咨询",
        "tags": ["转行", "非技术", "产品经理", "零基础"],
        "source": "转行可行性分析",
    },

    # ==================== 零基础可行性 ====================
    {
        "question": "零基础/代码基础差可以学吗？",
        "variants": ["零基础能学吗", "没有编程基础", "代码基础差", "完全不懂代码"],
        "answer": """可以学，课程从Python零基础开始讲
搞AI只需要学Python一门语言，上手很快
现在有AI辅助学习（Cursor、Claude等工具），学习效率比以前高很多
软件技术毕业的哪怕专业没怎么学也有基础在，问题不大

建议先看Python基础部分，跟着敲代码，很快就能上手""",
        "intent": "零基础可行性",
        "tags": ["零基础", "python", "入门"],
        "source": "课程大纲文档",
    },

    # ==================== 学历要求咨询 ====================
    {
        "question": "大专学历可以搞AI吗？学历有要求吗？",
        "variants": ["大专能搞ai吗", "学历要求", "专科可以吗", "二本/三本行不行"],
        "answer": """大专可以搞AI，学历不是绝对门槛
实际情况：
- 大专转AI：薪资比统招会少一些，但AI方向比传统开发强
- 本科/专升本：就业面更广，薪资上限更高
- 硕士：不是必须的，AI应用开发看能力不看论文

能力到了学历只是一个门槛，AI岗位更看重实际项目经验""",
        "intent": "学历要求咨询",
        "tags": ["学历", "大专", "本科", "门槛"],
        "source": "就业行情分析",
    },

    # ==================== 年龄顾虑 ====================
    {
        "question": "年龄大了还能学AI吗？29/34岁来得及吗？",
        "variants": ["年龄大了", "30岁还能学吗", "35岁", "年龄限制"],
        "answer": """AI应用开发不像传统开发那么卷年龄
目前AI行业人才缺口大，30+有工作经验反而是优势
有行业经验+AI技术能力 = 复合型人才，很抢手
关键是现在就开始，AI的红利期不会等人

比年龄更重要的是学习能力和执行力""",
        "intent": "年龄顾虑",
        "tags": ["年龄", "30岁", "35岁", "转行"],
        "source": "转行可行性分析",
    },

    # ==================== 报名流程 ====================
    {
        "question": "怎么报名？报名流程是什么？",
        "variants": ["如何报名", "怎么买课", "报名了", "付款方式"],
        "answer": """报名流程：
1. 先了解课程大纲，确认适合自己
2. 联系教务老师确认价格和优惠
3. 完成付款后拉你进班级群
4. 开通加密播放器账号，开始学习
5. 班级群里有课件、学习资料等所有需要的资源""",
        "intent": "报名流程",
        "tags": ["报名", "付款", "流程"],
        "source": "报名流程指南",
    },

    # ==================== 退款政策 ====================
    {
        "question": "可以退款吗？退款政策是什么？",
        "variants": ["能退课吗", "退款流程", "不想学了能退吗", "看不懂想退款"],
        "answer": """支持15天无理由退款
- 15天内：全额退款，无条件
- 超过15天：按实际情况协商
- 退款处理时间：一般1-3个工作日

可以先体验，不满意随时退""",
        "intent": "退款政策",
        "tags": ["退款", "15天", "无理由"],
        "source": "售后政策手册",
    },

    # ==================== 售后服务 ====================
    {
        "question": "播放器设备怎么解绑/换绑？",
        "variants": ["设备解绑", "换电脑怎么办", "播放器登录不了", "能开多台设备吗"],
        "answer": """播放器设备绑定相关：
- 换手机/电脑：可以联系解绑重新绑定
- 一般支持同时绑定2-3台设备（手机+电脑）
- 需要增加设备数量可以联系处理
- 登录问题可以先尝试重新登录，不行联系技术支持""",
        "intent": "售后服务",
        "tags": ["播放器", "设备", "解绑", "登录"],
        "source": "售后政策手册",
    },
    {
        "question": "学习过程中遇到技术问题怎么办？",
        "variants": ["代码报错", "环境配置问题", "安装慢", "跑不通"],
        "answer": """技术问题解决途径：
1. 班级群里提问 — 老师和同学都会帮忙
2. 直播答疑时提问 — 每周都有
3. 用AI工具辅助排查 — Cursor、Claude等
4. 飞书文档里有常见问题汇总

建议先把具体报错信息截图发群里，一般很快就能解决""",
        "intent": "售后服务",
        "tags": ["技术支持", "报错", "群答疑"],
        "source": "售后政策手册",
    },

    # ==================== 学员案例 ====================
    {
        "question": "有学员成功转行的案例吗？",
        "variants": ["就业案例", "offer情况", "有人找到工作吗", "成功案例"],
        "answer": """已有多位学员成功转行拿到offer：
- 0基础销售转AI应用开发：郑州14k
- 前端转AI应用开发：上海26k（17k涨到26k）
- Java转AI：深圳20k+
- 专科转AI：成都14-15k

很多学员学了一大半就开始面试拿offer了
班级群里经常有同学分享面试经验和offer喜报""",
        "intent": "学员案例",
        "tags": ["案例", "offer", "薪资", "转行成功"],
        "source": "学员就业案例库",
    },

    # ==================== 时间安排 ====================
    {
        "question": "在职/上班族怎么安排学习时间？",
        "variants": ["上班怎么学", "没时间学", "在职学习", "下班学"],
        "answer": """在职学习完全可以：
- 每天下班后学2-3小时
- 周末集中学习
- 视频课随时看，不限时间和次数
- 大部分学员都是在职学的，骑驴找马最稳

3个月坚持下来，基本能达到面试水平""",
        "intent": "学习方式咨询",
        "tags": ["在职", "时间安排", "学习计划"],
        "source": "学习周期说明",
    },

    # ==================== AI工具相关 ====================
    {
        "question": "Gemini/Claude的账号怎么搞？",
        "variants": ["gemini怎么注册", "claude账号", "账号注册不了", "去哪买号"],
        "answer": """AI工具账号获取方式：
- Gemini：可以在咸鱼搜"gemini成品号"，几十块就能买到
- Claude：类似方式获取
- 学习阶段用免费版就够了，不需要Pro
- 班级群里可以问同学分享购买链接

学习用免费的够了，学个思路就行""",
        "intent": "技术栈咨询",
        "tags": ["gemini", "claude", "账号", "工具"],
        "source": "课程技术栈说明",
    },
    {
        "question": "Coze和AI Agent有什么区别？该学哪个？",
        "variants": ["coze怎么样", "低代码和编程", "coze还是编程"],
        "answer": """Coze适合不懂代码的人用，做简单的自动化
AI Agent是用编程（Python）开发，能力上限更高：
- Coze：低代码平台，简单好上手，但灵活度有限
- AI Agent编程：基于LLM编程，未来AI应用的主流方向

想做副业可以先用Coze，想做职业发展建议学Agent编程
AI应用的市场空间万亿美元级别，现在才刚开始""",
        "intent": "技术栈咨询",
        "tags": ["coze", "agent", "低代码", "编程"],
        "source": "课程技术栈说明",
    },

    # ==================== 行业趋势 ====================
    {
        "question": "AI行业的发展趋势怎么样？值得转吗？",
        "variants": ["ai有前景吗", "ai行业趋势", "值得学吗", "ai会不会过时"],
        "answer": """AI应用开发是目前最确定性的技术方向：
- 市场空间：万亿美元级别，刚起步
- 人才缺口：远大于供给，企业招人难
- 薪资水平：普遍高于传统开发岗位
- 技术迭代快：先入场的人有先发优势

50%的企业在招AI客服系统、知识库方向的人才
风口已经确认了，就看你上不上车""",
        "intent": "就业前景咨询",
        "tags": ["行业趋势", "市场前景", "风口"],
        "source": "行业趋势分析",
    },

    # ==================== 技术学习难度 ====================
    {
        "question": "LangChain难学吗？",
        "variants": ["langchain难不难", "langchain好学吗", "langchain学起来复杂吗", "langchain上手快吗"],
        "answer": """LangChain不难，本质就是把大模型API调用封装成链式调用
有Python基础的话1-2周就能上手核心概念
课程里从最简单的Chain讲起，逐步到RAG、Agent
跟着项目写 比看文档快10倍

难的不是框架本身 是理解什么场景该用什么组件""",
        "intent": "学习难度咨询",
        "tags": ["langchain", "学习难度", "框架", "上手"],
        "source": "课程大纲文档",
    },
    {
        "question": "RAG好理解吗？学RAG难不难？",
        "variants": ["rag难吗", "rag好学吗", "rag复杂吗", "rag学起来难不难"],
        "answer": """RAG（检索增强生成）原理很简单：
1. 用户提问 → 2. 从知识库检索相关文档 → 3. 把文档喂给大模型 → 4. 大模型基于文档回答

核心就是"先搜后答"，技术上就是向量数据库+Embedding+LLM调用
课程里有完整的RAG项目实战 从零搭建一个知识库问答系统
搞懂原理之后 你会发现50%的AI岗位都在做RAG相关的事""",
        "intent": "学习难度咨询",
        "tags": ["rag", "学习难度", "检索增强", "知识库"],
        "source": "课程大纲文档",
    },
    {
        "question": "Python难学吗？没学过编程能学会吗？",
        "variants": ["python难不难", "python好学吗", "python学不下去", "python觉得很难"],
        "answer": """Python是最容易入门的编程语言 没有之一
语法接近自然语言 不像Java那么啰嗦
零基础1-2周就能写出能跑的代码

学不下去的话建议：
1. 别光看视频 一定要跟着敲代码
2. 今天学不进去不代表明天学不进去 状态不好就休息
3. 用AI工具（Cursor/Claude）辅助理解 遇到不懂的直接问AI
4. 群里问同学 大家都是这么过来的

Python只是工具 学个够用就行 不需要精通""",
        "intent": "学习难度咨询",
        "tags": ["python", "学习难度", "零基础", "入门"],
        "source": "课程大纲文档",
    },

    # ==================== 学习方法类 ====================
    {
        "question": "怎么学效果好？有什么学习建议？",
        "variants": ["怎么学效果最好", "学习方法", "怎么学效率高", "有什么学习建议"],
        "answer": """学习建议：
1. 按课程规划的顺序学 别跳着看
2. 一定要跟着写代码 光看视频没用
3. 不懂的先问AI（Cursor/Claude） 再问群里
4. 每个项目都自己从零写一遍 不要复制粘贴
5. 学完一个阶段就试着去面试 实战出真知

最重要的是保持每天学习的节奏 哪怕每天只学1小时""",
        "intent": "学习方式咨询",
        "tags": ["学习方法", "学习建议", "效率"],
        "source": "课程学习方式说明",
    },
    {
        "question": "看几节课能学会？多久能入门？",
        "variants": ["几节课能入门", "多久能上手", "多久能学会", "几天能入门"],
        "answer": """入门节奏参考：
- Python基础：3-5天（有基础更快）
- 第一个AI项目跑通：1-2周
- 理解RAG+Agent核心概念：2-3周
- 能独立做项目：1-2个月
- 面试水平：2-3个月

关键不是看多少节课 而是自己动手写了多少代码
很多同学学了一大半就出去面试拿offer了""",
        "intent": "学习周期咨询",
        "tags": ["入门", "学习节奏", "进度"],
        "source": "学习周期说明",
    },

    # ==================== 技术概念类 ====================
    {
        "question": "什么是AI Agent？Agent是做什么的？",
        "variants": ["agent是什么", "什么是智能体", "agent能做什么", "ai agent是什么意思"],
        "answer": """AI Agent（智能体）就是能自主决策和执行任务的AI程序
简单说：普通AI是你问一句它答一句 Agent是你给个目标它自己想办法完成

比如：
- 你说"帮我分析这个数据" → Agent自己决定用什么工具 怎么分析 输出报告
- 你说"帮我写个爬虫" → Agent自己规划步骤 写代码 调试 交付

Agent = LLM大脑 + 工具调用 + 自主规划
这是目前AI应用开发最核心最值钱的方向""",
        "intent": "技术栈咨询",
        "tags": ["agent", "智能体", "概念", "核心技术"],
        "source": "课程技术栈说明",
    },
    {
        "question": "什么是RAG？RAG技术是做什么的？",
        "variants": ["rag是什么", "rag是什么意思", "rag有什么用", "检索增强生成是什么"],
        "answer": """RAG = Retrieval Augmented Generation（检索增强生成）

大模型有个问题：它只知道训练时学到的东西 不知道你公司的内部数据
RAG就是解决这个问题的：
1. 把你的文档/数据切成小块 存到向量数据库
2. 用户提问时 先从数据库里检索出相关内容
3. 把检索到的内容+用户问题一起丢给大模型
4. 大模型基于你的数据回答 不会瞎编

现在企业招AI岗位 50%都在做RAG相关的系统（AI客服、知识库问答等）""",
        "intent": "技术栈咨询",
        "tags": ["rag", "检索增强", "概念", "向量数据库"],
        "source": "课程技术栈说明",
    },
    {
        "question": "什么是MCP？MCP协议是做什么的？",
        "variants": ["mcp是什么", "mcp协议", "mcp有什么用", "什么是model context protocol"],
        "answer": """MCP = Model Context Protocol（模型上下文协议）

简单理解：它是AI大模型连接外部工具和数据的标准接口
就像USB接口统一了设备连接 MCP统一了AI调用工具的方式

没有MCP：每个工具都要单独写对接代码 很麻烦
有了MCP：统一协议 AI可以即插即用地调用各种工具

这是2025年最火的AI基础设施之一
课程里会讲怎么用MCP让你的Agent连接各种外部工具""",
        "intent": "技术栈咨询",
        "tags": ["mcp", "协议", "概念", "工具调用"],
        "source": "课程技术栈说明",
    },

    # ==================== 学员常见困惑 ====================
    {
        "question": "学不进去怎么办？觉得课程太难了",
        "variants": ["学不下去", "看不懂怎么办", "觉得太难了", "一点都学不进去", "完全看不懂"],
        "answer": """学不进去很正常 每个人都有这个阶段
建议：
1. 今天学不进去就休息 明天状态可能就好了
2. 不要死磕 看不懂的先跳过 往后学了回头就懂了
3. 群里问同学 大家都是这么过来的 你不是一个人
4. 用AI工具辅助理解 把不懂的代码丢给Claude解释
5. 如果实在不适合 15天内支持全额退款

别给自己太大压力 学编程本来就有个适应期""",
        "intent": "售后服务",
        "tags": ["学不进去", "困惑", "学习困难", "心态"],
        "source": "售后政策手册",
    },
    {
        "question": "学了一段时间感觉啥也不会怎么办？",
        "variants": ["感觉啥也不会", "学了但不会用", "不知道怎么做项目", "学完不知道干嘛"],
        "answer": """这是正常的学习曲线 信息输入和能力输出之间有个滞后期
解决办法：
1. 别光看 自己从零写一遍项目 写的过程中就通了
2. 约一次模拟面试 面试官的问题会帮你梳理知识框架
3. 把学过的技术用到一个自己感兴趣的小项目上
4. 群里找同学一起讨论 教别人也是学习

能提出这个问题说明你在思考 这比埋头看视频强多了""",
        "intent": "售后服务",
        "tags": ["困惑", "不会用", "项目实战", "心态"],
        "source": "求职辅导手册",
    },
]


def build_knowledge_csv(output_path: str):
    """
    生成知识库 CSV（方案 C 格式：一条知识一行 + 结构化元数据列）

    列：question, answer, intent, tags, source, variants
    - question: 标准问题
    - answer: 自然语言回答（RAG 向量检索友好）
    - intent: 意图分类（用于下游精确过滤）
    - tags: 关键词标签，逗号分隔（用于元数据过滤）
    - source: 数据来源
    - variants: 问题变体，竖线分隔（提升搜索召回率）
    """
    fieldnames = ['question', 'answer', 'intent', 'tags', 'source', 'variants']
    with open(output_path, 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
        writer.writeheader()
        for item in KNOWLEDGE_BASE:
            writer.writerow({
                'question': item['question'],
                'answer': item['answer'].strip(),
                'intent': item['intent'],
                'tags': ','.join(item['tags']),
                'source': item['source'],
                'variants': '|'.join(item.get('variants', [])),
            })
    print(f"知识库（方案C）: {len(KNOWLEDGE_BASE)} 条 → {output_path}")


def build_knowledge_volcano_csv(output_path: str):
    """
    生成火山引擎兼容格式：展开 variants 为多行 question,answer

    每个 variant 独立一行，answer 重复。
    适用于火山引擎知识库等只支持 question,answer 两列的平台。
    """
    rows_written = 0
    with open(output_path, 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['question', 'answer'])
        writer.writeheader()
        for item in KNOWLEDGE_BASE:
            answer = item['answer'].strip()
            # 主问题
            writer.writerow({'question': item['question'], 'answer': answer})
            rows_written += 1
            # 变体展开
            for v in item.get('variants', []):
                writer.writerow({'question': v, 'answer': answer})
                rows_written += 1
    print(f"知识库（火山兼容）: {rows_written} 行（{len(KNOWLEDGE_BASE)} 条展开） → {output_path}")


def build_script_library(input_path: str, output_path: str):
    """从清洗后数据生成话术参考库"""
    with open(input_path, 'r', encoding='utf-8-sig') as f:
        rows = list(csv.DictReader(f))

    print(f"话术库输入: {len(rows)} 条")

    # 过滤条件
    COURSE_INTRO_SHORT = "加密视频+直播答疑+班级群"
    filtered = []
    removed = {'short': 0, 'dup_intro': 0, 'low_info': 0}

    for row in rows:
        answer = row.get('answer', '')

        # 1. 删除精简版课程介绍（67条重复垃圾）
        if answer.strip() == f"{COURSE_INTRO_SHORT}\n按我规划的顺序学 不懂群里问\n学差不多了约我模拟面试":
            removed['dup_intro'] += 1
            continue

        # 2. 删除 answer < 50 字（信息量太低）
        if len(answer.strip()) < 50:
            removed['short'] += 1
            continue

        # 3. 删除纯追问/反问式answer
        q_marks = answer.count('?') + answer.count('？')
        if q_marks >= 3 and len(answer) < 80:
            removed['low_info'] += 1
            continue

        filtered.append(row)

    print(f"  删除精简版重复: {removed['dup_intro']}")
    print(f"  删除过短(<50字): {removed['short']}")
    print(f"  删除低信息量: {removed['low_info']}")
    print(f"话术库输出: {len(filtered)} 条 → {output_path}")

    # 写出
    fieldnames = ['question', 'answer', 'category', 'intent', 'tags', 'source', 'confidence', 'content_type']
    with open(output_path, 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(filtered)


def main():
    import argparse
    import os
    parser = argparse.ArgumentParser(description='方案C：两库分离（含火山引擎兼容格式）')
    parser.add_argument('input', help='清洗后 CSV 文件路径')
    parser.add_argument('--knowledge', default='rag_knowledge_base.csv', help='知识库输出路径')
    parser.add_argument('--scripts', default='rag_script_library.csv', help='话术库输出路径')
    parser.add_argument('--volcano', action='store_true', help='同时生成火山引擎兼容的展开格式')
    args = parser.parse_args()

    print("=" * 50)
    print("方案 C：两库分离")
    print("=" * 50)
    print()

    # 1. 生成知识库（方案 C 紧凑格式）
    build_knowledge_csv(args.knowledge)

    # 1.5 可选：同时生成火山引擎兼容格式
    if args.volcano:
        base, ext = os.path.splitext(args.knowledge)
        volcano_path = f"{base}_volcano{ext}"
        build_knowledge_volcano_csv(volcano_path)
    print()

    # 2. 生成话术库
    build_script_library(args.input, args.scripts)
    print()

    print("=" * 50)
    print("完成")
    print(f"  知识库:   {args.knowledge} ({len(KNOWLEDGE_BASE)} 条，方案C 元数据格式)")
    if args.volcano:
        print(f"  火山兼容: {volcano_path} (展开 variants 的扁平格式)")
    print(f"  话术库:   {args.scripts}")
    print("=" * 50)


if __name__ == '__main__':
    main()

