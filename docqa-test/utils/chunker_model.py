"""切片算法参考实现（Differential Testing Oracle）。

这是后端 ``com.docqa.service.TextChunker`` 的独立复刻，用途有两个：
1. 单元测试用它验证"分块规格的不变量"（边界、覆盖性、重叠量）；
2. 集成测试用它**预测**后端返回的 ``chunkCount``，与真实返回值做差分比对——
   一旦后端改了切片参数（size / overlap / 归一化规则）而没同步改文档与测试，
   差分测试会立即失败，从而拦住"参数漂移导致检索质量下降"这类隐性回归。

与 Java 实现的对应关系：
    text.replaceAll("\\s+", " ").trim()   →  re.sub(r"\\s+", " ", text).strip()
    step = chunkSize - overlap (<=0 时退化为 chunkSize)
    循环 end = min(start + chunkSize, len)，end == len 时收尾
"""

from __future__ import annotations

import re
from typing import List, Tuple

DEFAULT_CHUNK_SIZE = 500
DEFAULT_OVERLAP = 80


def normalize(text: str) -> str:
    """与 Java 一致：连续空白（含换行、制表）折叠为单空格，并去掉首尾空白。"""
    return re.sub(r"\s+", " ", text or "").strip()


def sliding_chunk(
    text: str,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_OVERLAP,
) -> Tuple[str, List[str], List[Tuple[int, int]]]:
    """滑动窗口切片。

    返回 (归一化文本, 切片列表, 每个切片在归一化文本中的 [start, end) 区间)。
    """
    if text is None or not text.strip():
        return "", [], []

    cleaned = normalize(text)
    length = len(cleaned)
    if length <= chunk_size:
        return cleaned, [cleaned], [(0, length)]

    step = chunk_size - overlap
    if step <= 0:
        step = chunk_size

    chunks: List[str] = []
    ranges: List[Tuple[int, int]] = []
    start = 0
    while start < length:
        end = min(start + chunk_size, length)
        chunks.append(cleaned[start:end])
        ranges.append((start, end))
        if end == length:
            break
        start += step
    return cleaned, chunks, ranges


def predict_chunk_count(text: str, chunk_size: int = DEFAULT_CHUNK_SIZE,
                        overlap: int = DEFAULT_OVERLAP) -> int:
    """预测切片数量（差分测试的期望值）。"""
    return len(sliding_chunk(text, chunk_size, overlap)[1])
