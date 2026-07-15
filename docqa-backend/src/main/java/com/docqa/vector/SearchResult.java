package com.docqa.vector;

/**
 * 带元数据的向量检索结果：包含命中的文本片段、来源文档名、相似度分数。
 */
public record SearchResult(String content, String docName, double score) {
}
