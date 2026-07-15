package com.docqa.dto;

import lombok.Data;

@Data
public class DocumentDto {
    private Long id;
    private String fileName;
    private Long fileSize;
    private String fileType;
    private Integer chunkCount;
    private String status;
    private String errorMsg;
    private String createdAt;
    /** 预览文本（截断） */
    private String preview;
}
