# -*- coding: utf-8 -*-
"""
生成用于开发/演示的模拟微信 SQLite 数据库。

业务场景：小蚕惠生活（小蚕霸王餐）——帮你点外卖省钱、吃喝玩乐的本地生活平台。
立场：平台客服视角（客服自称「小蚕 / 蚕宝」，专业亲和）。
产出：
  - MicroMsg.db        通讯录（联系人为外卖平台用户）
  - Multi/MSG0.db      聊天消息（约 200 条种子，可用 LLM 扩量脚本补到 300）
  - Multi/MSG1-5.db    空库（保持与真实微信一致的分片结构）
  - FileStorage/Voice/{MsgSvrID}.mp3  语音哑文件（供 ETL 语音补链验证）

用法：
    python scripts/generate_fake_data.py [output_dir] [--total N]
    # 默认输出：./Msg/Msg，默认总量 200
"""
import sqlite3
import os
import sys
import random
import argparse

DEFAULT_OUTPUT_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "Msg", "Msg"
)
DEFAULT_VOICE_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "FileStorage", "Voice"
)

# ============================================================
# 联系人（昵称常见、备注为「昵称-身份」）
# ============================================================
CONTACTS = [
    {"wxid": "wxid_wangxiaoyu01", "alias": "xiaoyu_01", "nickname": "王小雨", "remark": "王小雨-大学生"},
    {"wxid": "wxid_limengqi02", "alias": "mengqi_02", "nickname": "李梦琪", "remark": "李梦琪-外卖重度用户"},
    {"wxid": "wxid_zhanghaoran03", "alias": "haoran_03", "nickname": "张浩然", "remark": "张浩然-上班族"},
    {"wxid": "wxid_chensiyuan04", "alias": "siyuan_04", "nickname": "陈思远", "remark": "陈思远-打工人"},
    {"wxid": "wxid_liuting05", "alias": "liuting_05", "nickname": "刘婷", "remark": "刘婷-宝妈"},
    {"wxid": "wxid_zhaozixuan06", "alias": "zixuan_06", "nickname": "赵子轩", "remark": "赵子轩-学生"},
    {"wxid": "wxid_sunyue07", "alias": "sunyue_07", "nickname": "孙悦", "remark": "孙悦-饭搭子"},
    {"wxid": "wxid_zhouxiaodong08", "alias": "xiaodong_08", "nickname": "周晓东", "remark": "周晓东-程序员"},
    {"wxid": "wxid_wujiayi09", "alias": "jiayi_09", "nickname": "吴佳怡", "remark": "吴佳怡-上班族"},
    {"wxid": "wxid_zhengyiming10", "alias": "yiming_10", "nickname": "郑一鸣", "remark": "郑一鸣-外卖重度用户"},
    {"wxid": "wxid_fengxue11", "alias": "fengxue_11", "nickname": "冯雪", "remark": "冯雪-研究生"},
    {"wxid": "wxid_jiangwenbo12", "alias": "wenbo_12", "nickname": "蒋文博", "remark": "蒋文博-上班族"},
    {"wxid": "wxid_hanxuemei13", "alias": "xuemei_13", "nickname": "韩雪梅", "remark": "韩雪梅-宝妈"},
    {"wxid": "wxid_yangfan14", "alias": "yangfan_14", "nickname": "杨帆", "remark": "杨帆-外卖重度用户"},
    {"wxid": "wxid_hejing15", "alias": "hejing_15", "nickname": "何静", "remark": "何静-大学生"},
    {"wxid": "wxid_luoxin16", "alias": "luoxin_16", "nickname": "罗鑫", "remark": "罗鑫-打工人"},
    {"wxid": "wxid_gaopeng17", "alias": "gaopeng_17", "nickname": "高鹏", "remark": "高鹏-上班族"},
    {"wxid": "wxid_linxiao18", "alias": "linxiao_18", "nickname": "林晓", "remark": "林晓-学生"},
    {"wxid": "wxid_xuzihan19", "alias": "zihan_19", "nickname": "徐子涵", "remark": "徐子涵-外卖重度用户"},
    {"wxid": "wxid_maxiaoli20", "alias": "xiaoli_20", "nickname": "马晓丽", "remark": "马晓丽-宝妈"},
    {"wxid": "wxid_zhujunjie21", "alias": "junjie_21", "nickname": "朱俊杰", "remark": "朱俊杰-程序员"},
    {"wxid": "wxid_huyue22", "alias": "huyue_22", "nickname": "胡月", "remark": "胡月-上班族"},
    {"wxid": "wxid_guojun23", "alias": "guojun_23", "nickname": "郭俊", "remark": "郭俊-外卖重度用户"},
    {"wxid": "wxid_xieting24", "alias": "xieting_24", "nickname": "谢婷", "remark": "谢婷-大学生"},
    {"wxid": "wxid_dengchao25", "alias": "dengchao_25", "nickname": "邓超", "remark": "邓超-打工人"},
    {"wxid": "wxid_qianxin26", "alias": "qianxin_26", "nickname": "钱欣", "remark": "钱欣-饭搭子"},
    {"wxid": "wxid_songjia27", "alias": "songjia_27", "nickname": "宋佳", "remark": "宋佳-上班族"},
    {"wxid": "wxid_pengyu28", "alias": "pengyu_28", "nickname": "彭宇", "remark": "彭宇-外卖重度用户"},
    {"wxid": "wxid_luyao29", "alias": "luyao_29", "nickname": "陆瑶", "remark": "陆瑶-宝妈"},
    {"wxid": "wxid_yaoming30", "alias": "yaoming_30", "nickname": "姚明轩", "remark": "姚明轩-学生"},
]

# ============================================================
# 对话模板：按 10 类客服场景组织
#   (is_sender, content, msg_type)   is_sender=True 表示「小蚕客服」发出
#   msg_type: 1=文本 3=图片 34=语音 49=链接/文件
# ============================================================
CONVERSATIONS = {
    # ---- 玩法说明 / 怎么领券 ----
    "savings_explain": [
        [
            (False, "小蚕惠生活怎么用啊 同事说点外卖能便宜不少", 1),
            (True, "您好~ 小蚕也叫小蚕霸王餐，是帮你点外卖省钱、吃喝玩乐薅羊毛的本地生活平台。用法很简单：点外卖前先在小蚕领券，再去美团/饿了么/京东外卖/淘宝闪购下单，就能省一笔，部分订单还有返利，单笔最低15元起🦊", 1),
            (False, "每天都能领吗"),
            (True, "每天都能领的~ 午餐、晚餐、下午茶的红包都有，像20-18、15-13这种力度，比直接在外卖平台下单划算多了", 1),
            (False, "那一个月大概能省多少"),
            (True, "正常用的话一个月省500到1000是有的，具体看你的点单频率哈", 1),
        ],
        [
            (False, "我朋友说领了券下单更便宜，是真的吗"),
            (True, "是真的~ 举个例子，同一单外卖，直接下单可能30块，先在小蚕领张20-18的红包，实际就花12块左右，差额就是省下的", 1),
            (True, "而且小蚕覆盖了300多个城市，主流的外卖渠道基本都有券", 1),
            (False, "那返利是啥意思"),
            (True, "返利就是下单之后额外返给你的钱~ 单笔最低15元起，攒在App里能直接提现", 1),
        ],
    ],
    # ---- 返利查询 / 提现 ----
    "rebate_query": [
        [
            (False, "我上周五点的外卖，返利怎么还没到账啊"),
            (True, "您好~ 返利一般在订单确认收货后1-3个工作日到账。方便把订单号发我下吗，小蚕帮你查一下", 1),
            (False, "订单号是 XCH-20251018093", 1),
            (True, "收到啦，帮你查到这笔返利15.6元已经到账咯🦊 在App首页-我的-返利余额里就能看到", 1),
            (False, "那这个钱怎么提出来"),
            (True, "返利余额满1元就能提现，微信、支付宝都支持，一般秒到账哈", 1),
            (False, "好的谢谢，我试一下"),
            (True, "不客气~ 有问题随时找小蚕", 1),
        ],
        [
            (False, "我这个返利金额好像不对，少了"),
            (True, "别急，小蚕帮你看下~ 你把这个订单的截图发我，我核对一下返利比例", 1),
            (False, "/storage/emulated/0/Pictures/Screenshots/Screenshot_20251020_120134.jpg", 3),
            (True, "收到截图了，这单是拼好饭渠道，返利比例是按实付金额算的，不是按原价，所以显示的金额会少一点，这个是正常的哈", 1),
            (False, "原来是这样，那我懂了"),
        ],
    ],
    # ---- 红包/券问题 ----
    "coupon_issue": [
        [
            (False, "为啥我领的红包用不了啊，下单没减钱"),
            (True, "您好~ 红包用不了一般有这几种情况：1）没在有效期内 2）订单金额没达到券的使用门槛 3）跳转的渠道不对。你把订单和领的券截图发小蚕看看", 1),
            (False, "我领的是15-13的，点了个12块的单"),
            (True, "那就对啦~ 15-13的意思是满15元才能减，你12块没到门槛，所以用不了。下次凑到15以上就能抵扣了", 1),
            (False, "哦哦 明白了 谢谢"),
        ],
        [
            (False, "我的券怎么过期了都没提醒啊"),
            (True, "抱歉带来困扰~ 券面上都有有效期，可以在App-我的-我的红包里看剩余时间，小蚕后面也会尽量提前提醒你哈", 1),
            (False, "那过期的还能补吗"),
            (True, "过期的券系统没法补哦，不过每天都有新的红包可以领，你明天登录再领一张就行🦊", 1),
        ],
    ],
    # ---- 订单异常（没返上 / 取消） ----
    "order_problem": [
        [
            (False, "我昨天点的这单好像没返上，是不是漏了"),
            (True, "您好，方便把订单号发小蚕核对下吗", 1),
            (False, "订单号 2025102100344212", 1),
            (True, "好的，小蚕查到你这单是从小蚕跳转过去下单的吗？如果是直接从外卖App下的，是不计入返利的哦", 1),
            (False, "啊 我当时没从小蚕跳"),
            (True, "那就没法补录啦~ 记得下次一定要从小蚕App里点进对应渠道下单，才能领券和拿返利哈", 1),
        ],
        [
            (False, "订单取消了，返利还算吗"),
            (True, "订单取消或者退款的话，对应的返利会一起扣回的~ 建议确认收货后再操作哈", 1),
            (False, "好的知道了"),
        ],
    ],
    # ---- 投诉 / 差评 ----
    "complaint": [
        [
            (False, "我要投诉，上次霸王餐说好的是双人套餐，到店给我换了单人份"),
            (True, "非常抱歉给你带来不好的体验！你说的这个情况小蚕会帮你反馈给商家核实。方便发下门店名称和用餐时间吗", 1),
            (False, "茶百道杭州西湖店，上周六中午"),
            (True, "收到，已经登记反馈了，核实后会有专员联系你处理，一般1-2个工作日给答复。给你添麻烦了🙏", 1),
            (False, "行吧 希望处理快点"),
        ],
        [
            (False, "你们这个返利提现怎么要审核这么久，是不是骗人的"),
            (True, "理解你的担心~ 提现正常是秒到的，如果超过24小时还在审核，可能是账号触发了风控校验。把提现记录截图发小蚕，我帮你加急看看", 1),
            (False, "好吧"),
        ],
    ],
    # ---- 到店霸王餐 / 门店 ----
    "merchant": [
        [
            (False, "到店霸王餐怎么参加啊，需要发什么"),
            (True, "您好~ 到店霸王餐是分享真实用餐感受就有机会低至0元吃品牌套餐的活动，主要覆盖城市里的热门店铺。你在小蚕App-到店霸王餐里报名，中签后到店用餐、发真实感受就行", 1),
            (False, "报名要收费吗"),
            (True, "报名是免费的~ 中签了才需要到店消费，用完发真实感受就完成啦", 1),
            (False, "中签概率大吗"),
            (True, "看门店和时段哦，热门店铺竞争会大一些，多报几家机会更大🦊", 1),
        ],
        [
            (False, "我们餐厅想入驻小蚕可以吗"),
            (True, "当然可以~ 商家合作可以联系我们商务同学，你把门店名称、城市和联系方式发小蚕，我帮你对接哈", 1),
            (False, "好的，我整理下发你"),
        ],
    ],
    # ---- 大牌特惠推广 ----
    "brand_promo": [
        [
            (False, "茶百道在小蚕有优惠吗"),
            (True, "有的~ 茶百道、沪上阿姨、霸王茶姬、奈雪的茶、茶颜悦色、夸父炸串这些大牌都入驻小蚕了，全天都有专属优惠，你在App里搜品牌名就能领", 1),
            (False, "那我要喝奈雪，能便宜多少"),
            (True, "具体优惠在券面上会写哈，一般比门店价和外卖平台价都划算，你搜「奈雪的茶」看看当天的券就知道啦", 1),
        ],
        [
            (False, "霸王茶姬有券吗，想下午点一杯"),
            (True, "有~ 下午茶时段还有额外的红包可以叠加，你领完券再下单更划算🦊", 1),
            (False, "好嘞 谢谢小蚕"),
        ],
    ],
    # ---- 积分 / 盲盒 ----
    "points_box": [
        [
            (False, "积分是怎么攒的，能干嘛用啊"),
            (True, "您好~ 每下一单都能攒积分，积分可以换券，还能抽五折盲盒、品牌代金券这些福利，攒起来挺快的哈", 1),
            (False, "五折盲盒是啥"),
            (True, "就是一个抽奖玩法，花很少的积分就有机会抽到五折券或者品牌券，图个乐子~", 1),
            (False, "听着挺有意思，我去试试"),
        ],
        [
            (False, "我的积分怎么突然少了一部分"),
            (True, "小蚕帮你查下~ 积分如果有兑换券或者抽过盲盒，是会扣掉对应积分的，你可以在积分明细里看每一笔记录哈", 1),
            (False, "哦 我抽过盲盒 那没事了"),
        ],
    ],
    # ---- 新人引导 ----
    "onboarding": [
        [
            (False, "新人第一次用，有啥优惠吗"),
            (True, "欢迎加入小蚕🦊 新人注册就有专属红包，绑定手机号还能再领一张神券。你先下载小蚕App，注册后在小蚕那里领券下单就行~", 1),
            (False, "安卓能下吗"),
            (True, "可以的，iPhone和安卓版都有，App Store美食佳饮榜排到过第14名，评分4.6分呢", 1),
            (False, "好，我这就去下"),
            (True, "下载完有不懂的随时问小蚕~", 1),
        ],
        [
            (False, "我怎么注册啊，找不到入口"),
            (True, "打开App首页就有「注册/登录」，用手机号一键登录就行，注册时填小蚕给你的邀请码还能多拿一张券", 1),
            (False, "邀请码在哪看"),
            (True, "你把手机号发小蚕，我帮你关联一下~", 1),
            (False, "我手机号是 13800001234，你帮我关联下", 1),
            (True, "收到，已经帮你关联好啦，去App里看看新人红包到账没🦊", 1),
        ],
    ],
    # ---- 闲聊 / 品牌咨询 ----
    "chitchat": [
        [
            (False, "小蚕你们总部在哪啊"),
            (True, "小蚕总部在杭州~ 是杭州柏鹿信息技术有限公司开发的，目前已经覆盖300多个城市啦", 1),
            (False, "那你们靠谱吗"),
            (True, "放心的，App Store评分4.6分、6.4万条评分呢，安卓下载量也不小🦊", 1),
        ],
        [
            (False, "想吃夸父炸串，小蚕有券不"),
            (True, "有~ 夸父炸串也入驻了，你在App搜「夸父炸串」领券再下单就行", 1),
            (False, "好，今天晚饭就它了"),
            (True, "哈哈那必须省一笔，点完记得看看返利到没到账🦊", 1),
        ],
    ],
}

# ============================================================
# 单轮速答（保持问答形态的样本）
# ============================================================
SINGLE_QA = [
    ("券能送给朋友用吗", "红包一般是绑定账号的，不能直接转赠哦，不过你可以让朋友自己下载领~"),
    ("返利多久结算一次", "按订单来的，确认收货后1-3个工作日结算，余额满1元就能提现"),
    ("小蚕收费吗", "小蚕对用户是免费的，领券、返利、霸王餐都不收费哈"),
    ("一天能领几张券", "每天午餐、晚餐、下午茶的券都能领，具体张数以App显示为准~"),
    ("外卖和到店都能省吗", "都可以~ 外卖领券拿返利，到店有霸王餐和大牌特惠"),
    ("提现要手续费吗", "提现不收手续费，微信支付宝都支持🦊"),
    ("券的有效期多久", "不同券有效期不一样，券面上会写明，领了尽量早点用哈"),
    ("为什么我的返利比别人的少", "返利按实付金额和渠道比例算的，不同订单会有差异~"),
    ("小蚕支持哪些外卖平台", "美团、饿了么、京东外卖、淘宝闪购这些主流的都有"),
    ("霸王餐要发几张图", "按活动要求发真实用餐感受就行，具体张数活动页会写哈"),
]

# ============================================================
# 非文本消息块（图片 / 语音 / 链接），用于验证 ETL 多类型导入
# ============================================================
NON_TEXT_BLOCKS = [
    [
        (False, "小蚕你看下这单，是这样操作的", 1),
        (False, "/storage/emulated/0/tencent/MicroMsg/WeiXin/mmexport1760500001.jpg", 3),
        (True, "收到，小蚕看下截图~", 1),
        (True, "没问题哦，这样从小蚕跳转下单是对的，券和返利都能领到🦊", 1),
    ],
    [
        (False, "我把订单信息发你", 1),
        (False, "/storage/emulated/0/Pictures/WeiXin/order_20251021.png", 3),
        (True, "好的，小蚕核对一下，稍等~", 1),
        (True, "查到了，这单返利已经在结算中啦", 1),
    ],
    [
        (False, "我语音跟你说下情况", 1),
        (False, "", 34),  # 语音（内容为空，ETL 通过 MsgSvrID 关联 Voice/{id}.mp3）
        (True, "收到你的语音啦，小蚕听完了，你说的提现没到账我帮你查下~", 1),
        (False, "", 34),
        (True, "放心，显示已经到账了，你刷新下App首页看看🦊", 1),
    ],
    [
        (False, "帮你分享个活动链接", 1),
        (False, '<?xml version="1.0"?><msg><appmsg><title>小蚕霸王餐｜今日到店霸王餐开抢</title>'
                '<des>分享真实感受，低至0元吃品牌套餐</des><type>5</type>'
                '<url>https://xiaocan.example.com/activity/20251021</url></appmsg></msg>', 49),
        (True, "收到，这个是到店霸王餐的活动页~ 你在小蚕App里报名就能参加啦", 1),
    ],
]

# ============================================================
# 兜底填充消息
# ============================================================
FILLER_MESSAGES = [
    (False, "好的，谢谢小蚕"),
    (True, "不客气~ 有问题随时找小蚕🦊"),
    (False, "那我先去下单了"),
    (True, "好嘞，记得从小蚕跳转下单哈"),
    (False, "收到"),
    (True, "嗯嗯，祝用餐愉快~"),
    (False, "还有其他优惠吗"),
    (True, "每天登录都能领新券，大牌特惠全天都有~"),
]


def create_micromsg_db(output_dir: str):
    """创建 MicroMsg.db（通讯录）。"""
    db_path = os.path.join(output_dir, "MicroMsg.db")
    os.makedirs(output_dir, exist_ok=True)
    if os.path.exists(db_path):
        os.remove(db_path)

    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE Contact (
            UserName TEXT,
            Alias TEXT,
            NickName TEXT,
            Remark TEXT,
            SmallHeadImgUrl TEXT
        )
    """)
    for c in CONTACTS:
        conn.execute(
            "INSERT INTO Contact (UserName, Alias, NickName, Remark, SmallHeadImgUrl) VALUES (?, ?, ?, ?, ?)",
            (c["wxid"], c["alias"], c["nickname"], c["remark"], None),
        )
    conn.commit()
    conn.close()
    print(f"[OK] Created {db_path} with {len(CONTACTS)} contacts")


def create_msg_db(output_dir: str, voice_dir: str, total_messages: int = 200):
    """创建 Multi/MSG0.db（聊天消息）并生成语音哑文件。"""
    multi_dir = os.path.join(output_dir, "Multi")
    os.makedirs(multi_dir, exist_ok=True)
    os.makedirs(voice_dir, exist_ok=True)
    db_path = os.path.join(multi_dir, "MSG0.db")
    if os.path.exists(db_path):
        os.remove(db_path)

    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE MSG (
            localId INTEGER PRIMARY KEY,
            StrTalker TEXT,
            StrContent TEXT,
            CreateTime INTEGER,
            Type INTEGER,
            SubType INTEGER,
            IsSender INTEGER,
            DisplayContent TEXT,
            BytesExtra BLOB,
            MsgSvrID INTEGER
        )
    """)

    base_ts = 1760490000  # 2025-10-15 09:00:00 CST，晚于 ETL 的 MIN_TIMESTAMP
    state = {"msg_id": 1, "svr_id": 9000000000000000000, "count": 0, "voice_ids": []}

    def emit(session_id: str, is_sender: bool, content: str, msg_type: int, day_offset: int, seq: int):
        if state["count"] >= total_messages:
            return False
        ts = base_ts + day_offset + seq * random.randint(30, 180)
        svr_id = state["svr_id"]
        conn.execute(
            "INSERT INTO MSG (localId, StrTalker, StrContent, CreateTime, Type, SubType, IsSender, DisplayContent, BytesExtra, MsgSvrID) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (state["msg_id"], session_id, content, ts, msg_type, 0, int(is_sender), None, None, svr_id),
        )
        if msg_type == 34:
            state["voice_ids"].append(svr_id)
        state["msg_id"] += 1
        state["svr_id"] += 1
        state["count"] += 1
        return True

    all_conv = [c for convs in CONVERSATIONS.values() for c in convs] + NON_TEXT_BLOCKS

    # 第一轮：保证每个联系人都至少有一段对话
    for contact in CONTACTS:
        if state["count"] >= total_messages:
            break
        conv = random.choice(all_conv)
        day_offset = random.randint(0, 60) * 86400
        for seq, (is_sender, content, *rest) in enumerate(conv):
            msg_type = rest[0] if rest else 1
            if not emit(contact["wxid"], is_sender, content, msg_type, day_offset, seq):
                break

    # 第二轮：随机对话填满
    while state["count"] < total_messages:
        contact = random.choice(CONTACTS)
        conv = random.choice(all_conv)
        day_offset = random.randint(0, 60) * 86400
        for seq, (is_sender, content, *rest) in enumerate(conv):
            msg_type = rest[0] if rest else 1
            if not emit(contact["wxid"], is_sender, content, msg_type, day_offset, seq):
                break

    # 第三轮：单轮问答 + 兜底填充
    while state["count"] < total_messages:
        contact = random.choice(CONTACTS)
        day_offset = random.randint(0, 60) * 86400
        if random.random() < 0.5:
            q, a = random.choice(SINGLE_QA)
            emit(contact["wxid"], False, q, 1, day_offset, 0)
            emit(contact["wxid"], True, a, 1, day_offset, 1)
        else:
            is_sender, content = random.choice(FILLER_MESSAGES)
            emit(contact["wxid"], is_sender, content, 1, day_offset, 0)

    conn.commit()
    conn.close()

    # 生成语音哑文件（供 ETL 语音补链）
    voice_created = 0
    for svr_id in state["voice_ids"]:
        path = os.path.join(voice_dir, f"{svr_id}.mp3")
        if not os.path.exists(path):
            with open(path, "wb") as f:
                f.write(b"\x00")  # 哑数据，仅用于路径匹配
            voice_created += 1

    print(f"[OK] Created {db_path} with {state['count']} messages ({len(state['voice_ids'])} voice, {voice_created} mp3 files)")


def create_empty_msg_shards(output_dir: str):
    """创建空的 MSG1-5.db，保持与真实微信一致的分片结构。"""
    multi_dir = os.path.join(output_dir, "Multi")
    os.makedirs(multi_dir, exist_ok=True)
    for i in range(1, 6):
        db_path = os.path.join(multi_dir, f"MSG{i}.db")
        if not os.path.exists(db_path):
            conn = sqlite3.connect(db_path)
            conn.execute("""
                CREATE TABLE MSG (
                    localId INTEGER PRIMARY KEY,
                    StrTalker TEXT,
                    StrContent TEXT,
                    CreateTime INTEGER,
                    Type INTEGER,
                    SubType INTEGER,
                    IsSender INTEGER,
                    DisplayContent TEXT,
                    BytesExtra BLOB,
                    MsgSvrID INTEGER
                )
            """)
            conn.commit()
            conn.close()


def main():
    parser = argparse.ArgumentParser(description="生成小蚕惠生活模拟微信数据")
    parser.add_argument("output_dir", nargs="?", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--total", type=int, default=200, help="目标消息总数（默认 200）")
    parser.add_argument("--voice-dir", default=DEFAULT_VOICE_DIR)
    args = parser.parse_args()

    output_dir = os.path.abspath(args.output_dir)
    voice_dir = os.path.abspath(args.voice_dir)
    print(f"Generating 小蚕惠生活 fake WeChat data in: {output_dir}")
    print("=" * 50)

    create_micromsg_db(output_dir)
    create_msg_db(output_dir, voice_dir, total_messages=args.total)
    create_empty_msg_shards(output_dir)

    print("=" * 50)
    print("[DONE] 种子数据就绪。下一步：")
    print("  cd backend && uv run python scripts/run_etl.py --clear-existing")
    print("  # 可选：LLM 扩量到 300 条")
    print("  cd backend && uv run python scripts/expand_wechat_data.py --target 300")


if __name__ == "__main__":
    main()
