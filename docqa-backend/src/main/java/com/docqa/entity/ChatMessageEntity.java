package com.docqa.entity;

import jakarta.persistence.*;
import lombok.Data;
import java.time.LocalDateTime;

/**
 * 聊天消息实体（持久化对话历史，同时缓存到 Redis）
 */
@Data
@Entity
@Table(name = "chat_message")
public class ChatMessageEntity {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "session_id", nullable = false)
    private Long sessionId;

    /** USER / ASSISTANT */
    @Column(length = 16, nullable = false)
    private String role;

    @Column(columnDefinition = "MEDIUMTEXT", nullable = false)
    private String content;

    /** 本次回答引用的文档片段（JSON 字符串，可空） */
    @Column(name = "ref_content", columnDefinition = "TEXT")
    private String references;

    @Column(name = "created_at")
    private LocalDateTime createdAt = LocalDateTime.now();
}
