package com.docqa.service;

import com.docqa.entity.DocumentEntity;
import com.docqa.repository.DocumentRepository;
import com.docqa.vector.VectorService;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

import java.io.FileInputStream;
import java.nio.file.Paths;
import java.time.LocalDateTime;
import java.util.List;

/**
 * 文档解析工作单元：Tika 解析 -> 切片 -> 向量化。
 * 被 DocumentService 同步调用（local 模式）或 ParseConsumer 异步调用（full 模式）。
 */
@Component
public class DocumentParseWorker {

    private static final Logger log = LoggerFactory.getLogger(DocumentParseWorker.class);

    private final DocumentRepository documentRepository;
    private final DocumentParser parser;
    private final TextChunker chunker;
    private final VectorService vectorService;

    public DocumentParseWorker(DocumentRepository documentRepository,
                               DocumentParser parser,
                               TextChunker chunker,
                               VectorService vectorService) {
        this.documentRepository = documentRepository;
        this.parser = parser;
        this.chunker = chunker;
        this.vectorService = vectorService;
    }

    public void process(Long docId) {
        log.info("开始解析文档 docId={}", docId);
        DocumentEntity doc = documentRepository.findById(docId).orElse(null);
        if (doc == null) {
            log.warn("文档不存在 docId={}", docId);
            return;
        }
        try {
            doc.setStatus("PROCESSING");
            doc.setUpdatedAt(LocalDateTime.now());
            documentRepository.save(doc);

            // 1. Tika 解析
            String text;
            try (FileInputStream fis = new FileInputStream(Paths.get(doc.getFilePath()).toFile())) {
                text = parser.parse(fis);
            }
            log.info("文档 docId={} 解析得到 {} 字符，前200字符预览: {}",
                    docId, text.length(),
                    text.length() > 200 ? text.substring(0, 200).replaceAll("\\s+", " ") : text.replaceAll("\\s+", " "));

            String stored = text.length() > 5000 ? text.substring(0, 5000) : text;
            doc.setContent(stored);

            // 2. 文本切片
            List<String> chunks = chunker.chunk(text);
            doc.setChunkCount(chunks.size());

            // 3. 向量化（单独捕获异常，失败不影响文档状态）
            String vectorWarn = null;
            try {
                vectorService.storeChunks(docId, doc.getFileName(), chunks);
            } catch (Exception ve) {
                vectorWarn = "文档解析成功，但向量化失败（可能未配置有效的 Embedding API Key）: "
                        + (ve.getMessage() == null ? ve.getClass().getSimpleName() : ve.getMessage());
                log.warn("向量化失败 docId={}，文档仍标记为完成: {}", docId, ve.getMessage());
            }

            // 解析+切片成功即标记 DONE
            doc.setStatus("DONE");
            doc.setErrorMsg(vectorWarn);
            doc.setUpdatedAt(LocalDateTime.now());
            documentRepository.save(doc);
            log.info("文档解析完成 docId={} chunks={} vectorWarn={}", docId, chunks.size(), vectorWarn != null);
        } catch (Exception e) {
            log.error("文档解析失败 docId={}", docId, e);
            doc.setStatus("FAILED");
            String m = e.getMessage();
            doc.setErrorMsg(m == null ? e.getClass().getSimpleName() :
                    (m.length() > 900 ? m.substring(0, 900) : m));
            doc.setUpdatedAt(LocalDateTime.now());
            documentRepository.save(doc);
        }
    }
}
