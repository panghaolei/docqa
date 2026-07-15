package com.docqa.mq;

import com.docqa.service.DocumentParseWorker;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.amqp.rabbit.annotation.RabbitListener;
import org.springframework.boot.autoconfigure.condition.ConditionalOnClass;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Component;

import static com.docqa.config.RabbitMqConfig.QUEUE_PARSE;

/**
 * 文档解析消费者（仅 full 模式启用）。
 * 解析逻辑委托给 DocumentParseWorker，与同步模式共用。
 */
@Component
@ConditionalOnClass(name = "org.springframework.amqp.rabbit.annotation.RabbitListener")
@ConditionalOnProperty(name = "docqa.mode", havingValue = "full")
public class ParseConsumer {

    private static final Logger log = LoggerFactory.getLogger(ParseConsumer.class);

    private final DocumentParseWorker parseWorker;

    public ParseConsumer(DocumentParseWorker parseWorker) {
        this.parseWorker = parseWorker;
    }

    @RabbitListener(queues = QUEUE_PARSE)
    public void onMessage(ParseMessage msg) {
        Long docId = msg.getDocumentId();
        log.info("收到 MQ 文档解析任务 docId={}", docId);
        parseWorker.process(docId);
    }
}
