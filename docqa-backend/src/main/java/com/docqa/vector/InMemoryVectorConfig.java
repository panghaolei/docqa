package com.docqa.vector;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.ai.document.Document;
import org.springframework.ai.embedding.EmbeddingModel;
import org.springframework.ai.vectorstore.SearchRequest;
import org.springframework.ai.vectorstore.VectorStore;
import org.springframework.boot.autoconfigure.condition.ConditionalOnMissingBean;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.CopyOnWriteArrayList;

/**
 * 本地降级配置：当 Redis VectorStore（RediSearch）不可用时，
 * 提供一个基于内存的 VectorStore 实现，使用 EmbeddingModel + 余弦相似度检索。
 */
@Configuration
public class InMemoryVectorConfig {

    private static final Logger log = LoggerFactory.getLogger(InMemoryVectorConfig.class);

    @Bean
    @ConditionalOnMissingBean(VectorStore.class)
    public VectorStore inMemoryVectorStore(EmbeddingModel embeddingModel) {
        log.info("启用内存版 VectorStore（降级模式，无 RediSearch 依赖）");
        return new InMemoryVectorStore(embeddingModel);
    }

    /**
     * 内存向量存储：保存 Document 及其 embedding，检索时计算余弦相似度。
     */
    static class InMemoryVectorStore implements VectorStore {

        private static final Logger log = LoggerFactory.getLogger(InMemoryVectorStore.class);

        private final EmbeddingModel embeddingModel;
        private final List<DocVector> store = new CopyOnWriteArrayList<>();

        InMemoryVectorStore(EmbeddingModel embeddingModel) {
            this.embeddingModel = embeddingModel;
        }

        /** 当前向量条数 */
        public int size() {
            return store.size();
        }

        @Override
        public void add(List<Document> documents) {
            if (documents == null || documents.isEmpty()) return;
            for (Document d : documents) {
                float[] vec = embeddingModel.embed(d.getContent());
                d.setEmbedding(vec);
                store.add(new DocVector(d, vec));
            }
            log.info("内存向量库新增 {} 条，当前共 {} 条", documents.size(), store.size());
        }

        @Override
        public Optional<Boolean> delete(List<String> idList) {
            if (idList == null) return Optional.of(false);
            store.removeIf(dv -> idList.contains(dv.doc.getId()));
            return Optional.of(true);
        }

        public void deleteByDocId(Long docId) {
            store.removeIf(dv -> {
                Map<String, Object> meta = dv.doc.getMetadata();
                return meta != null && docId.equals(meta.get("docId"));
            });
            log.info("按 docId={} 删除后剩余 {} 条", docId, store.size());
        }

        @Override
        public List<Document> similaritySearch(SearchRequest request) {
            if (store.isEmpty() || request.getQuery() == null) return List.of();
            float[] qvec = embeddingModel.embed(request.getQuery());
            int topK = request.getTopK() > 0 ? request.getTopK() : 4;
            double threshold = request.getSimilarityThreshold();
            return store.stream()
                    .map(dv -> Map.entry(dv, cosine(qvec, dv.vector)))
                    .filter(e -> threshold <= 0 || e.getValue() >= threshold)
                    .sorted(Comparator.<Map.Entry<DocVector, Double>>comparingDouble(Map.Entry::getValue).reversed())
                    .limit(topK)
                    .map(Map.Entry::getKey)
                    .map(dv -> dv.doc)
                    .toList();
        }

        /** 按用户隔离检索：先按 metadata.userId 过滤，再计算相似度取 topK，保证召回结果只属于当前用户。 */
        public List<Document> similaritySearch(String query, int topK, double threshold, Long userId) {
            if (store.isEmpty() || query == null) return List.of();
            float[] qvec = embeddingModel.embed(query);
            int k = topK > 0 ? topK : 4;
            return store.stream()
                    .filter(dv -> userId == null || userId.equals(userIdOf(dv.doc)))
                    .map(dv -> Map.entry(dv, cosine(qvec, dv.vector)))
                    .filter(e -> threshold <= 0 || e.getValue() >= threshold)
                    .sorted(Comparator.<Map.Entry<DocVector, Double>>comparingDouble(Map.Entry::getValue).reversed())
                    .limit(k)
                    .map(Map.Entry::getKey)
                    .map(dv -> dv.doc)
                    .toList();
        }

        private static Long userIdOf(Document d) {
            Map<String, Object> meta = d.getMetadata();
            if (meta == null) return null;
            Object u = meta.get("userId");
            return u instanceof Number n ? n.longValue() : null;
        }

        /** 余弦相似度 */
        private static double cosine(float[] a, float[] b) {
            if (a.length != b.length) return 0;
            double dot = 0, na = 0, nb = 0;
            for (int i = 0; i < a.length; i++) {
                dot += a[i] * b[i];
                na += a[i] * a[i];
                nb += b[i] * b[i];
            }
            if (na == 0 || nb == 0) return 0;
            return dot / (Math.sqrt(na) * Math.sqrt(nb));
        }

        private record DocVector(Document doc, float[] vector) {}
    }
}
