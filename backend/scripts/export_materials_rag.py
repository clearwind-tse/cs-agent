# -*- coding: utf-8 -*-
"""
素材库导出为 RAG 知识库条目（标签组合式 question）

将素材库中的喜报（report类）按标签导出为 question/answer CSV，
question 采用标签关键词组合，覆盖更多用户查询方式。
answer 中包含 TOS 公开 URL，客服系统可直接渲染图片。

用法:
    cd backend
    python scripts/export_materials_rag.py -o ../rag_materials_volcano.csv
"""
import csv
import sys
import os
import argparse
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


# ============================================================
# 标签 → 扩展关键词映射
# 每个标签自动展开为一组同义词/关联词，提高检索覆盖面
# ============================================================
TAG_EXPAND_MAP = {
    # ==================== 学历相关 ====================
    "大专": ["大专", "专科", "大专学历", "专科学历"],
    "本科": ["本科", "本科学历", "统招本科"],
    "专升本": ["专升本", "专升本学历"],
    "硕士": ["硕士", "研究生", "硕士学历"],
    "高中": ["高中", "高中学历"],
    "成人大专": ["成人大专", "成人专科", "非统招"],

    # ==================== 转行背景 ====================
    "前端": ["前端", "前端开发", "前端转AI"],
    "java": ["Java", "java", "Java开发", "Java转AI"],
    "Java": ["Java", "java", "Java开发", "Java转AI"],
    "后端": ["后端", "后端开发", "后端转AI"],
    "零基础": ["零基础", "0基础", "没有基础", "没有编程基础", "小白"],
    "0基础": ["零基础", "0基础", "没有基础", "小白"],
    "产品经理": ["产品经理", "产品", "PM转AI"],
    "运营": ["运营", "运营转AI"],
    "销售": ["销售", "销售转AI"],
    "测试": ["测试", "QA", "测试转AI"],
    "运维": ["运维", "运维转AI"],
    "嵌入式": ["嵌入式", "嵌入式转AI"],

    # ==================== 城市/地区 ====================
    "北京": ["北京", "北京市"],
    "上海": ["上海", "上海市"],
    "深圳": ["深圳"],
    "杭州": ["杭州"],
    "成都": ["成都"],
    "广州": ["广州"],
    "武汉": ["武汉"],
    "南京": ["南京"],
    "重庆": ["重庆"],
    "郑州": ["郑州"],
    "长沙": ["长沙"],
    "西安": ["西安"],
    "合肥": ["合肥"],
    "惠州": ["惠州"],
    "苏州": ["苏州"],
    "天津": ["天津"],
    "厦门": ["厦门"],
    "济南": ["济南"],
    "青岛": ["青岛"],
    "佛山": ["佛山"],

    # 地区维度（展开到具体城市）
    "中部": ["中部", "武汉", "郑州", "长沙", "合肥", "南昌"],
    "华东": ["华东", "上海", "杭州", "南京", "苏州", "合肥"],
    "华南": ["华南", "广州", "深圳", "佛山", "惠州", "厦门"],
    "华北": ["华北", "北京", "天津", "济南", "青岛"],
    "西南": ["西南", "成都", "重庆"],
    "川渝": ["川渝", "成都", "重庆", "四川", "重庆市"],
    "广深": ["广深", "广州", "深圳"],

    # ==================== 薪资区间 ====================
    "10k": ["10k", "1万", "10K"],
    "10-15k": ["10-15k", "10k-15k", "1万到1万5"],
    "15k": ["15k", "1万5", "15K"],
    "15-20k": ["15-20k", "15k-20k", "1万5到2万"],
    "20k": ["20k", "2万", "20K"],
    "20-25k": ["20-25k", "20k-25k", "2万到2万5"],
    "25k": ["25k", "2万5", "25K"],
    "30k": ["30k", "3万", "30K", "30k+"],

    # ==================== 年龄/经验 ====================
    "应届": ["应届", "应届生", "应届毕业", "刚毕业"],
    "1-3年": ["1-3年", "1到3年经验"],
    "3-5年": ["3-5年", "3到5年经验"],
    "5年以上": ["5年以上", "资深"],

    # ==================== 时间维度 ====================
    "近3个月": ["近3个月", "最近", "最新"],
    "近1个月": ["近1个月", "这个月", "上个月"],

    # ==================== offer/喜报 ====================
    "offer": ["offer", "拿到offer", "入职", "成功"],
    "喜报": ["喜报", "成功案例", "学员喜报"],
}

# 所有条目共用的基础标签（每条都会附加）
BASE_TAGS = ["学员案例", "成功案例", "喜报", "offer"]


def build_tag_question(tags: list[str]) -> str:
    """
    将素材标签列表转换为标签组合式 question

    策略：
    1. 每个标签通过 TAG_EXPAND_MAP 展开为同义词
    2. 拼接基础标签
    3. 去重后用空格连接
    """
    keywords = set()

    for tag in tags:
        tag = str(tag).strip()
        if not tag:
            continue
        # 展开标签
        expanded = TAG_EXPAND_MAP.get(tag, [tag])
        keywords.update(expanded)
        # 原始标签也加上（兜底）
        keywords.add(tag)

    # 加入基础标签
    keywords.update(BASE_TAGS)

    # 排序：先按长度短的排（核心关键词优先）
    sorted_kw = sorted(keywords, key=lambda x: (len(x), x))
    return " ".join(sorted_kw)


def build_public_url(oss_key: str, bucket: str, endpoint: str) -> str:
    """
    构建 TOS 公开访问 URL
    格式: https://{bucket}.{endpoint_host}/{oss_key}
    """
    # endpoint 格式: https://tos-cn-beijing.volces.com
    host = endpoint.replace("https://", "").replace("http://", "")
    return f"https://{bucket}.{host}/{oss_key}"


def main():
    parser = argparse.ArgumentParser(description='素材库导出为RAG知识库（标签组合式）')
    parser.add_argument('-o', '--output', default='../rag_materials_volcano.csv')
    parser.add_argument('--category', default='report', help='素材分类（默认report=喜报）')
    args = parser.parse_args()

    from app.models.database import get_session_local
    from app.models.chat import Material
    from app.config import get_settings

    settings = get_settings()
    bucket = settings.tos_bucket
    endpoint = settings.tos_endpoint

    SessionLocal = get_session_local()
    db = SessionLocal()

    # 查询所有喜报素材（图片类型，有标签）
    materials = db.query(Material).filter(
        Material.category == args.category,
        Material.file_type.like("image/%"),
        Material.oss_key.isnot(None),
    ).all()

    print(f"查询到 {len(materials)} 个 {args.category} 类图片素材")

    # ========== 按标签组合分组 ==========
    # 每个素材可能有多个标签，按标签集合（frozenset）分组
    tag_group_materials: dict[frozenset, list] = defaultdict(list)
    single_tag_materials: dict[str, list] = defaultdict(list)
    no_tag = 0

    for m in materials:
        tags = m.tags or []
        if not tags:
            no_tag += 1
            continue
        tag_strs = [str(t).strip() for t in tags if str(t).strip()]
        if not tag_strs:
            no_tag += 1
            continue

        # 单标签维度分组（用于按维度检索）
        for tag in tag_strs:
            single_tag_materials[tag].append(m)

    print(f"有标签的素材覆盖 {len(single_tag_materials)} 个标签，无标签 {no_tag} 个")
    print()

    # ========== 生成 Q&A 条目 ==========
    rows = []

    for tag, mats in single_tag_materials.items():
        # 构建标签组合式 question
        question = build_tag_question([tag])

        # 构建 answer：文字描述 + 图片URL列表
        image_urls = []
        for m in mats[:5]:  # 每个标签最多5张图
            url = build_public_url(m.oss_key, bucket, endpoint)
            title = m.title or m.filename
            image_urls.append(f"- {title}: {url}")

        answer_text = f"有的，以下是{tag}相关的学员成功案例：\n" + "\n".join(image_urls)

        rows.append({
            "question": question,
            "answer": answer_text,
        })

    # ========== 通用问题（不按标签） ==========
    if materials:
        # 最新5个喜报
        recent = sorted(materials, key=lambda m: m.created_at or '', reverse=True)[:5]
        recent_urls = []
        for m in recent:
            url = build_public_url(m.oss_key, bucket, endpoint)
            title = m.title or m.filename
            recent_urls.append(f"- {title}: {url}")

        general_answer = "最近的学员成功案例：\n" + "\n".join(recent_urls)
        # 通用问题也用标签式
        rows.append({
            "question": "最新 最近 成功案例 学员案例 喜报 offer",
            "answer": general_answer,
        })

    # ========== 写出 CSV ==========
    with open(args.output, 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['question', 'answer'])
        writer.writeheader()
        writer.writerows(rows)

    db.close()

    print(f"导出: {len(rows)} 条 → {args.output}")
    print()

    # 统计
    print("标签 → 标签组合式 question 预览:")
    print("-" * 60)
    for tag in sorted(single_tag_materials.keys()):
        cnt = len(single_tag_materials[tag])
        q = build_tag_question([tag])
        # 截断显示
        q_display = q[:60] + "..." if len(q) > 60 else q
        print(f"  [{tag}] ({cnt}张) → {q_display}")


if __name__ == '__main__':
    main()
