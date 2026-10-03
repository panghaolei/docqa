package com.docqa.service;

import com.docqa.common.UserContext;
import com.docqa.dto.DocumentDto;
import com.docqa.entity.DocumentEntity;
import com.docqa.mq.ParseMessage;
import com.docqa.repository.DocumentRepository;
import com.docqa.vector.VectorService;
import jakarta.annotation.PostConstruct;
import jakarta.annotation.PreDestroy;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.stereotype.Service;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;
import java.nio.file.*;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.stream.Collectors;

import static com.docqa.config.RabbitMqConfig.EXCHANGE;
import static com.docqa.config.RabbitMqConfig.ROUTING_KEY_PARSE;

@Service
public class DocumentService {

    private static final Logger log = LoggerFactory.getLogger(DocumentService.class);
    private static final DateTimeFormatter FMT = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss");

    private final DocumentRepository documentRepository;
    /** RabbitTemplate 可选注入：local 模式下不存在 */
    private final ObjectProvider<RabbitTemplate> rabbitTemplateProvider;
    private final DocumentParseWorker parseWorker;
    private final VectorService vectorService;
    /** 本地解析线程池：local 模式下异步解析，避免大文件同步 embedding 阻塞上传请求 */
    private final ExecutorService parseExecutor = Executors.newFixedThreadPool(2);

    @Value("${docqa.upload.dir:./uploads}")
    private String uploadDir;

    @Value("${docqa.mode:local}")
    private String mode;

    public DocumentService(DocumentRepository documentRepository,
                           ObjectProvider<RabbitTemplate> rabbitTemplateProvider,
                           DocumentParseWorker parseWorker,
                           VectorService vectorService) {
        this.documentRepository = documentRepository;
        this.rabbitTemplateProvider = rabbitTemplateProvider;
        this.parseWorker = parseWorker;
        this.vectorService = vectorService;
    }

    @PostConstruct
    public void init() throws IOException {
        Files.createDirectories(Paths.get(uploadDir).toAbsolutePath());
        log.info("DocQA 运行模式: {}", mode);
    }

    @PreDestroy
    public void shutdown() {
        parseExecutor.shutdown();
    }

    /**
     * 上传文档：落盘 -> 保存元数据 -> 解析（local 同步 / full 异步 MQ）
     */
    public DocumentDto upload(MultipartFile file) throws IOException {
        Long userId = UserContext.currentUserId();
        String original = file.getOriginalFilename();
        String ext = original != null && original.contains(".")
                ? original.substring(original.lastIndexOf('.') + 1) : "txt";
        String storedName = UUID.randomUUID() + "." + ext;
        Path dest = Paths.get(uploadDir, storedName).toAbsolutePath();
        Files.copy(file.getInputStream(), dest, StandardCopyOption.REPLACE_EXISTING);

        DocumentEntity doc = new DocumentEntity();
        doc.setFileName(original);
        doc.setFilePath(dest.toString());
        doc.setFileSize(file.getSize());
        doc.setFileType(ext);
        doc.setStatus("PENDING");
        doc.setUserId(userId);
        doc = documentRepository.save(doc);

        final Long docId = doc.getId();
        if ("full".equalsIgnoreCase(mode)) {
            // 异步解析
            RabbitTemplate rt = rabbitTemplateProvider.getIfAvailable();
            if (rt != null) {
                rt.convertAndSend(EXCHANGE, ROUTING_KEY_PARSE, new ParseMessage(docId));
                log.info("文档已上传并发送 MQ 解析任务 docId={}", docId);
            } else {
                // 兜底：MQ 不可用则同步解析
                parseWorker.process(docId);
            }
        } else {
            // local 模式：线程池异步解析（大文件不再阻塞上传请求）
            log.info("文档已上传，提交异步解析任务 docId={}", docId);
            parseExecutor.submit(() -> parseWorker.process(docId));
        }

        // 重新查询最新状态返回
        doc = documentRepository.findById(docId).orElse(doc);
        return toDto(doc, null);
    }

    public List<DocumentDto> listMine() {
        Long userId = UserContext.currentUserId();
        return documentRepository.findByUserIdOrderByCreatedAtDesc(userId).stream()
                .map(d -> toDto(d, null))
                .collect(Collectors.toList());
    }

    public DocumentEntity get(Long id) {
        return documentRepository.findById(id).orElseThrow(() -> new RuntimeException("文档不存在"));
    }

    public void delete(Long id) throws IOException {
        DocumentEntity doc = get(id);
        // 先删除向量库中对应的向量
        try {
            vectorService.deleteByDocId(id);
        } catch (Exception e) {
            log.warn("删除文档 {} 向量失败，继续删除文件与记录: {}", id, e.getMessage());
        }
        if (doc.getFilePath() != null) {
            Files.deleteIfExists(Paths.get(doc.getFilePath()));
        }
        documentRepository.delete(doc);
    }

    public DocumentDto toDto(DocumentEntity d, String preview) {
        DocumentDto dto = new DocumentDto();
        dto.setId(d.getId());
        dto.setFileName(d.getFileName());
        dto.setFileSize(d.getFileSize());
        dto.setFileType(d.getFileType());
        dto.setChunkCount(d.getChunkCount());
        dto.setStatus(d.getStatus());
        dto.setErrorMsg(d.getErrorMsg());
        dto.setCreatedAt(d.getCreatedAt() == null ? null : d.getCreatedAt().format(FMT));
        dto.setPreview(preview);
        return dto;
    }
}
