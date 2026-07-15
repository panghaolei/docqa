package com.docqa.vector;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.ai.document.Document;
import org.springframework.ai.vectorstore.SearchRequest;
import org.springframework.ai.vectorstore.VectorStore;
import org.springframework.stereotype.Service;

import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

/**
 * 向量服务：封装对 Spring AI VectorStore（Redis）的写入与 KNN 检索。
 * 每个 chunk 以 Document 形式存储，metadata 携带 docId / docName / chunkIndex。
 */
@Service
public class VectorService {

    private static final Logger log = LoggerFactory.getLogger(VectorService.class);

    private final VectorStore vectorStore;

    public VectorService(VectorStore vectorStore) {
        this.vectorStore = vectorStore;
    }

    /**
     * 将文档切片批量写入向量库
     *
     * @param docId   文档 ID
     * @param docName 文档名（用于回答时标注来源）
     * @param chunks  切片列表
     */
    public void storeChunks(Long docId, String docName, List<String> chunks) {
        List<Document> docs = chunks.stream().map(text -> {
            Map<String, Object> meta = new HashMap<>();
            meta.put("docId", docId);
            meta.put("docName", docName == null ? "未知文档" : docName);
            return new Document(text, meta);
        }).collect(Collectors.toList());
        vectorStore.add(docs);
        log.info("文档 docId={}({}) 共写入 {} 个向量", docId, docName, docs.size());
    }

    /**
     * 相似度检索（带元数据与相似度阈值过滤）
     *
     * @param query     用户问题
     * @param topK      返回条数
     * @param threshold 相似度阈值（0~1），低于该值的结果被过滤
     * @return 命中的检索结果（含文档名与分数）
     */
    public List<SearchResult> searchWithMeta(String query, int topK, double threshold) {
        SearchRequest req = SearchRequest.query(query)
                .withTopK(topK)
                .withSimilarityThreshold(threshold);
        List<Document> hits = vectorStore.similaritySearch(req);
        if (hits == null || hits.isEmpty()) return List.of();
        return hits.stream().map(d -> {
            Map<String, Object> meta = d.getMetadata();
            String name = meta != null && meta.get("docName") != null
                    ? String.valueOf(meta.get("docName")) : "未知文档";
            // Spring AI Document 的 metadata 中可能携带 score（部分实现），否则无法获取精确分数
            double score = meta != null && meta.get("score") instanceof Number n
                    ? n.doubleValue() : 0.0;
            return new SearchResult(d.getContent(), name, score);
        }).collect(Collectors.toList());
    }

    /**
     * 向量库中是否存在任何向量
     */
    public boolean hasAnyVector() {
        // InMemoryVectorStore 实现了该接口判断；Redis 场景退化为一次空查询判断
        if (vectorStore instanceof InMemoryVectorConfig.InMemoryVectorStore im) {
            return im.size() > 0;
        }
        // 其它实现：用一个极简查询探测；查询为空则认为无向量
        try {
            List<Document> hits = vectorStore.similaritySearch(
                    SearchRequest.query("probe").withTopK(1));
            return hits != null && !hits.isEmpty();
        } catch (Exception e) {
            log.warn("探测向量库失败: {}", e.getMessage());
            return false;
        }
    }

    /**
     * 删除指定文档对应的所有向量。
     * 内存实现支持按 docId 精确删除；Redis 实现降级为日志提示。
     */
    public void deleteByDocId(Long docId) {
        try {
            if (vectorStore instanceof InMemoryVectorConfig.InMemoryVectorStore im) {
                im.deleteByDocId(docId);
                log.info("已从内存向量库删除 docId={} 的向量", docId);
            } else {
                log.warn("删除 docId={} 向量：当前 VectorStore 实现未直接支持按 metadata 删除，可手动清理", docId);
            }
        } catch (Exception e) {
            log.error("删除向量失败 docId={}", docId, e);
        }
    }
}
