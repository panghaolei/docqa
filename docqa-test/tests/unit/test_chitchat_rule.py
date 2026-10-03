"""闲聊短路规则规格测试（纯单元测试）。

被测对象：``com.docqa.service.QaService`` 中的 CHITCHAT_PATTERN 与 isChitchat()。
业务价值：命中闲聊规则时系统不调用大模型，直接本地回复。
    这条规则既能降低 API 成本，也是"响应时延"体验的关键，属于核心回归点。

测试策略：等价类划分 + 边界值（30 字长度阈值）+ 已知风险记录。
"""

from __future__ import annotations

import re

import pytest

CHITCHAT_MAX_LEN = 30

# 与后端 CHITCHAT_PATTERN 等价的正则
CHITCHAT_PATTERN = re.compile(
    r"^(你好|您好|hi|hello|hey|嗨|在吗|谢谢|感谢|thx|thanks|好的|ok|再见|拜拜|bye"
    r"|你是谁|你叫什么|介绍一下你自己|你能做什么|帮助|help).*$",
    re.IGNORECASE,
)

# 与后端 localChitchatReply 等价的回复映射
REPLY_RULES = [
    (r"(?i).*(谢谢|感谢|thx|thanks).*", "不客气"),
    (r"(?i).*(你好|您好|hi|hello|hey|嗨|在吗).*", "你好！我是智能文档问答助手"),
    (r"(?i).*(再见|拜拜|bye).*", "再见"),
    (r"(?i).*(你是谁|你叫什么|介绍一下你自己|你能做什么|帮助|help).*", "我是「智能文档问答助手」"),
    (r"(?i).*(好的|ok).*", "好的"),
]


def is_chitchat(question: str | None) -> bool:
    """复刻 QaService#isChitchat：先 trim，长度 >30 直接判定为非闲聊。"""
    if question is None:
        return False
    trimmed = question.strip()
    if len(trimmed) > CHITCHAT_MAX_LEN:
        return False
    return CHITCHAT_PATTERN.match(trimmed) is not None


def local_reply(question: str) -> str:
    for pattern, reply in REPLY_RULES:
        if re.match(pattern, question.strip()):
            # 返回规则标识，便于断言"命中了哪一类"
            return reply
    return "默认引导回复"


# --------------------------------------------------------------------- #
# 等价类划分
# --------------------------------------------------------------------- #
@pytest.mark.unit
@pytest.mark.parametrize("question", [
    "你好", "您好", "hi", "Hello", "HEY", "嗨", "在吗",
    "谢谢", "感谢", "thx", "Thanks",
    "好的", "ok", "OK",
    "再见", "拜拜", "bye",
    "你是谁", "你叫什么", "介绍一下你自己", "你能做什么", "帮助", "help",
    "你好呀", "hi~", "谢谢啦", "OK 好的",     # 前缀命中 + 后缀任意
])
def test_greeting_equivalence_class_is_chitchat(question: str):
    """闲聊等价类：所有问候/致谢/告别/自我介绍类短句都应本地短路。"""
    assert is_chitchat(question) is True, f"'{question}' 应被判定为闲聊"


@pytest.mark.unit
@pytest.mark.parametrize("question", [
    "年假有多少天？",
    "差旅费几个工作日内提交报销单？",
    "请根据文档总结一下报销流程和审批权限的要求，越详细越好，谢谢。",  # 超过 30 字
    "What is the annual leave policy?",
    "   ",                     # 纯空白
])
def test_document_question_is_not_chitchat(question: str):
    """非闲聊等价类：真实业务提问必须走 RAG 链路，不能被误短路。"""
    assert is_chitchat(question) is False, f"'{question}' 不应被判定为闲聊"


@pytest.mark.unit
def test_length_boundary_30_chars():
    """边界值：长度阈值 30 —— 30 字仍判闲聊，31 字不再判闲聊。"""
    assert is_chitchat("你好" + "啊" * 28) is True        # 恰好 30 字
    assert is_chitchat("你好" + "啊" * 29) is False       # 31 字，超过阈值


@pytest.mark.unit
def test_none_and_whitespace_are_safe():
    """健壮性：None / 纯空白不得抛异常。"""
    assert is_chitchat(None) is False
    assert is_chitchat("   你好   ") is True      # trim 后命中


@pytest.mark.unit
def test_reply_mapping_covers_each_branch():
    """回复映射：每类闲聊都要落到对应分支，且文案可区分（便于接口层断言）。"""
    assert "不客气" in local_reply("谢谢")
    assert "文档问答助手" in local_reply("你好")
    assert "再见" in local_reply("拜拜")
    assert "智能文档问答助手" in local_reply("你能做什么")
    assert "好的" in local_reply("OK")


@pytest.mark.unit
def test_documented_risk_greedy_prefix_match():
    """【已知风险-记录型用例】规则使用前缀贪婪匹配。

    "你好，请帮我总结文档内容" 虽然是业务提问，但因为以"你好"开头且长度 ≤30，
    会被判定为闲聊并被短路，用户拿不到文档答案。
    该用例固化当前行为：一旦产品修复（改为"完全不包含业务关键词才判闲聊"），
    这里会失败并提醒同步更新规则与文档。
    """
    risky = "你好，请帮我总结文档内容"
    assert len(risky) <= CHITCHAT_MAX_LEN
    assert is_chitchat(risky) is True, "当前实现会误判，属于已知风险"
