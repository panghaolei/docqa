package com.docqa.dto;

import lombok.Data;

@Data
public class ChatMessageDto {
    private Long id;
    private String role;
    private String content;
    private String references;
    private String createdAt;
}
