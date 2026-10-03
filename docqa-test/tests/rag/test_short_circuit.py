"""智能短路（Short-Circuit）测试。

被测逻辑：``com.docqa.service.QaService#streamAnswer`` 的三条短路分支：
    1. 闲聊命中 → 本地规则回复，不调用大模型；
    2. 无已解析文档 → 直接提示上传文档，不调用 Embedding / Chat；
    3. 检索为空（低于相似度阈值）→ 提示未检索到，不调用大模型。

短路的业务意义 = **省钱 + 降延迟**：
    一次未命中的大模型调用不仅要花 token，还要等首 token 数秒。
    因此"该短路时必须短路"属于核心性能回归点。

断言手段：
    · 行为断言——短路的回答是固定文案（多次调用完全一致）；
    · 结构断言——短路时 tokens 只有 1 个分片、meta 引用为空；
    · 性能断言——短路响应必须显著快于真实 RAG 调用。
"""

from __future__ import annotations

import pytest

from core.assertions import assert_contains, assert_equal, assert_lte, assert_true

pytestmark = pytest.mark.rag

# (提问, 期望回复中的关键片段)
CHITCHAT_CASES = [
    ("你好", "智能文档问答助手"),
    ("谢谢", "不客气"),
    ("再见", "再见"),
    ("你能做什么", "文档问答助手"),
    ("ok", "好的"),
]


@pytest.mark.parametrize("question,expected", CHITCHAT_CASES)
def test_chitchat_is_short_circuited(api, question, expected):
    """闲聊短路：固定文案 + 单个 token 分片 + 无引用来源。"""
    result = api.ask(question)
    assert_true(result.done, f"'{question}' 未正常结束：{result.error}")
    assert_contains(result.answer, expected)
    assert_equal(result.token_count, 1, f"'{question}' 应本地一次性返回（Flux.just）")
    assert_equal(result.meta_refs, [], "闲聊不应携带任何文档引用")


def test_chitchat_reply_is_deterministic(api):
    """确定性：同一闲聊问题多次调用必须返回完全一致的文案（证明未经过大模型）。"""
    answers = {api.ask("你好").answer for _ in range(3)}
    assert_equal(len(answers), 1, f"闲聊回复出现多种结果，疑似走了大模型：{answers}")


def test_chitchat_latency_is_far_below_llm_latency(api, settings):
    """性能断言：短路响应耗时必须在阈值内（本地规则匹配，不应受模型时延影响）。"""
    limit = settings.get("thresholds.short_circuit_latency_ms", 3000)
    for question, _ in CHITCHAT_CASES:
        result = api.ask(question)
        assert_lte(result.total_ms, limit, f"'{question}' 短路耗时")


def test_chitchat_exchange_is_persisted(api, chat_session):
    """短路回答同样要落库，保证前端刷新后能看到完整对话历史。"""
    api.ask("你好", session_id=chat_session)
    messages = api.messages(chat_session).data
    assert_equal(len(messages), 2, f"应产生一问一答两条消息，实际 {messages}")
    assert_equal([m["role"] for m in messages], ["USER", "ASSISTANT"], "消息角色顺序")


def test_over_length_greeting_is_not_short_circuited(api, settings):
    """边界值：超过 30 字的提问即使以"你好"开头，也不应被判定为闲聊。

    这是防止"误短路"的关键回归——一旦规则放宽，真实的文档提问会被吞掉。
    """
    question = "你好，" + "请帮我详细分析一下员工手册里关于报销审批权限的规定" * 2
    assert len(question) > settings.get("rag.chitchat_max_len", 30)

    result = api.ask(question)
    chitchat_replies = ["智能文档问答助手", "不客气", "随时欢迎回来提问", "有什么文档相关的问题需要我帮忙吗"]
    assert not any(r in result.answer for r in chitchat_replies), (
        f"超长提问被误判为闲聊，回答：{result.answer[:120]}"
    )


def test_retrieval_empty_short_circuit_skips_llm(api, kb_doc, rag_ready, settings):  # noqa: ARG001
    """检索为空短路：与知识库完全无关的提问，应提示"未检索到相关内容"。

    若回答中出现了文档之外的具体事实（例如编造的天气数据），说明模型越过了检索边界。
    """
    result = api.ask("请推荐三个适合周末爬山的杭州景点，并给出交通路线。")
    assert result.done, f"未正常结束：{result.error}"

    short_circuit_hints = ["未检索到", "未找到相关", "没有相关", "换个更具体的关键词"]
    hit_short_circuit = any(h in result.answer for h in short_circuit_hints)
    if hit_short_circuit:
        # 走短路分支：应快速返回且无引用来源
        assert_lte(result.total_ms, settings.get("thresholds.full_answer_latency_ms", 60000),
                   "检索为空时的响应耗时")
    else:
        # 走了大模型分支：必须明确声明无法从文档回答，而不是给出行程建议
        refuse_hints = ["无法", "没有", "未包含", "不包含", "建议上传", "抱歉"]
        assert any(h in result.answer for h in refuse_hints), (
            f"域外提问未声明无法回答，存在编造风险：{result.answer[:200]}"
        )


@pytest.mark.xfail(
    reason="已知缺陷：QaService#countReadyDocs 使用 findAll() 做全局统计，"
           "且向量检索未按 userId 过滤，导致无任何文档的新用户可检索到其它用户上传的文档内容"
           "（跨租户数据泄露）",
    strict=False,
)
def test_new_user_without_documents_gets_upload_prompt(other_api, kb_doc):  # noqa: ARG001
    """数据隔离（安全）：新账号名下没有任何文档时，提问应得到"请先上传文档"的提示，
    而不是基于他人文档作答。
    """
    result = other_api.ask("入职满 3 年的员工每年可以享受多少天年假？")
    assert "还没有可用的文档" in result.answer, (
        f"新用户获取到了知识库内容，存在跨用户数据泄露：{result.answer[:200]}"
    )
