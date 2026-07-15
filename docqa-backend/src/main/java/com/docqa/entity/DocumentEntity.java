package com.docqa.entity;

import jakarta.persistence.*;
import lombok.Data;
import java.time.LocalDateTime;

/**
 * 文档元数据实体
 */
@Data
@Entity
@Table(name = "doc_info")
public class DocumentEntity {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    /** 原始文件名 */
    @Column(nullable = false, length = 255)
    private String fileName;

    /** 存储路径 */
    @Column(name = "file_path", length = 512)
    private String filePath;

    /** 文件大小（字节） */
    private Long fileSize;

    /** 文件类型后缀 */
    @Column(length = 32)
    private String fileType;

    /** 解析后的纯文本内容（仅用于预览/调试，可裁剪） */
    @Column(columnDefinition = "MEDIUMTEXT")
    private String content;

    /** 切片数量 */
    private Integer chunkCount;

    /** 处理状态：PENDING / PROCESSING / DONE / FAILED */
    @Column(length = 32)
    private String status = "PENDING";

    /** 处理失败时的错误信息 */
    @Column(length = 1024)
    private String errorMsg;

    @Column(name = "user_id")
    private Long userId;

    @Column(name = "created_at")
    private LocalDateTime createdAt = LocalDateTime.now();

    @Column(name = "updated_at")
    private LocalDateTime updatedAt = LocalDateTime.now();
}
