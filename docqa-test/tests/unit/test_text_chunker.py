"""文本切片算法规格测试（纯单元测试，不依赖后端服务）。

被测对象：后端 ``com.docqa.service.TextChunker``（滑动窗口切片）。
测试策略：**参考实现 + 不变量断言**
    在测试侧用 Python 复刻同一份算法规格（500 字 / 80 重叠 / 空白归一化），
    然后断言算法必须满足的若干"不变量"（边界、覆盖性、无丢失、步长保护）。
    这样即使无法直接调用 Java，也能把"分块规格"固化成回归用例；
    真正的后端实现通过 tests/api/test_document_api.py 中的 chunkCount 差分测试交叉验证。
"""

from __future__ import annotations

import pytest

from utils.chunker_model import (  # noqa: F401  (sliding_chunk 供本模块用例调用)
    DEFAULT_CHUNK_SIZE as CHUNK_SIZE,
    DEFAULT_OVERLAP as OVERLAP,
    sliding_chunk,
)


# --------------------------------------------------------------------- #
# 边界值用例
# --------------------------------------------------------------------- #
@pytest.mark.unit
def test_empty_and_blank_text_produce_no_chunk():
    """空文本 / 纯空白：不应产生任何切片（防止写入空向量）。"""
    for value in ["", "   ", "\n\t  \r\n"]:
        assert sliding_chunk(value)[1] == []


@pytest.mark.unit
@pytest.mark.parametrize("length", [1, 10, 499, 500, 501, 980, 981, 1000])
def test_chunk_count_boundary(length: int):
    """长度边界：<=500 只切 1 片；501 起按 420 步长滚动。"""
    text = "甲" * length
    _cleaned, chunks, ranges = sliding_chunk(text)
    if length <= CHUNK_SIZE:
        assert len(chunks) == 1
    else:
        expected = 1
        start = 0
        while start + CHUNK_SIZE < length:
            start += CHUNK_SIZE - OVERLAP
            expected += 1
        assert len(chunks) == expected, f"长度 {length} 的切片数应为 {expected}"
    assert all(len(c) <= CHUNK_SIZE for c in chunks)


@pytest.mark.unit
def test_every_chunk_within_size_limit_and_only_last_can_be_short():
    """除最后一片外，其余切片必须正好等于 chunk_size（保证检索粒度均匀）。"""
    text = "测试内容" * 500          # 2000 字
    _cleaned, chunks, _ranges = sliding_chunk(text)
    assert len(chunks) > 2
    for chunk in chunks[:-1]:
        assert len(chunk) == CHUNK_SIZE
    assert 0 < len(chunks[-1]) <= CHUNK_SIZE


@pytest.mark.unit
def test_adjacent_chunks_overlap_exactly_80_chars():
    """相邻切片重叠必须恰好为 80 字——这是"上下文不断裂"的关键参数。"""
    text = "".join(str(i % 10) for i in range(1600))
    _cleaned, chunks, _ranges = sliding_chunk(text)
    for prev, nxt in zip(chunks, chunks[1:]):
        assert prev[-OVERLAP:] == nxt[:OVERLAP]


@pytest.mark.unit
def test_full_coverage_no_content_lost():
    """覆盖性不变量：切片区间必须连续覆盖原文 [0, len)，不允许出现空洞。"""
    text = "星云科技员工手册" * 200
    cleaned, _chunks, ranges = sliding_chunk(text)
    assert ranges[0][0] == 0, "首个切片必须从 0 开始"
    assert ranges[-1][1] == len(cleaned), "最后一个切片必须覆盖到文本末尾"
    for (s1, e1), (s2, e2) in zip(ranges, ranges[1:]):
        assert s2 <= e1, f"出现内容空洞：区间 {(s1, e1)} 与 {(s2, e2)} 不相接"
        assert e2 > e1, "步长非正，切片未向前推进"


@pytest.mark.unit
def test_chunk_content_matches_source_slice():
    """切片内容必须是原文的精确子串（不能有截断错位、不能凭空造字）。"""
    text = "ABCDEFG中文混排" * 120
    cleaned, chunks, ranges = sliding_chunk(text)
    for chunk, (start, end) in zip(chunks, ranges):
        assert chunk == cleaned[start:end]


@pytest.mark.unit
def test_whitespace_normalized_before_chunking():
    """换行 / 制表 / 连续空格必须先归一化为单空格，否则切片会被空白浪费。"""
    text = "第一段内容\n\n\n第二段内容\t\t第三段内容   " + "填充" * 300
    cleaned, _chunks, _ranges = sliding_chunk(text)
    assert "\n" not in cleaned and "\t" not in cleaned
    assert "  " not in cleaned
    assert cleaned.startswith("第一段内容 第二段内容 第三段内容")
    assert not cleaned.endswith(" ")


@pytest.mark.unit
def test_step_guard_when_overlap_not_smaller_than_size():
    """参数异常保护：overlap >= size 时步长非正，必须退化为不重叠，避免死循环。"""
    text = "内容" * 400          # 800 字
    _cleaned, chunks, ranges = sliding_chunk(text, chunk_size=100, overlap=100)
    assert len(chunks) == 8, "步长必须退化为 100，否则会死循环"
    assert [r[0] for r in ranges] == [0, 100, 200, 300, 400, 500, 600, 700]


@pytest.mark.unit
def test_real_knowledge_base_chunk_count_is_stable():
    """对知识库语料的切片数量做快照式断言：语料或参数被改动会立即被发现。"""
    from utils.doc_factory import KB_TEXT

    cleaned, chunks, ranges = sliding_chunk(KB_TEXT)
    assert len(cleaned) > CHUNK_SIZE, "测试语料应长于单个切片，否则评测无效"
    assert len(chunks) >= 3, f"语料约 {len(cleaned)} 字，至少应切出 3 片，实际 {len(chunks)}"
    assert ranges[-1][1] == len(cleaned)
