package com.docqa.dto;

import jakarta.validation.constraints.NotBlank;
import lombok.Data;

@Data
public class AskRequest {
    /** 会话 ID，若为空则新建会话 */
    private Long sessionId;

    @NotBlank(message = "问题不能为空")
    private String question;

    /** 是否仅在指定文档范围内检索，可空 */
    private Long documentId;
}
