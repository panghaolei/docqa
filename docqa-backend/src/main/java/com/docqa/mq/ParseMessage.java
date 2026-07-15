package com.docqa.mq;

import lombok.Data;
import lombok.NoArgsConstructor;

import java.io.Serializable;

/**
 * 文档解析 MQ 消息体
 */
@Data
@NoArgsConstructor
public class ParseMessage implements Serializable {
    private Long documentId;

    public ParseMessage(Long documentId) {
        this.documentId = documentId;
    }
}
