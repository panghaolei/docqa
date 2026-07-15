package com.docqa.config;

import org.springframework.amqp.core.*;
import org.springframework.boot.autoconfigure.condition.ConditionalOnClass;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * RabbitMQ 配置：文档解析与向量化异步处理（仅 full 模式生效）
 */
@Configuration
@ConditionalOnClass(name = "org.springframework.amqp.core.Queue")
@ConditionalOnProperty(name = "docqa.mode", havingValue = "full")
public class RabbitMqConfig {

    public static final String EXCHANGE = "docqa.exchange";
    public static final String QUEUE_PARSE = "docqa.queue.parse";
    public static final String ROUTING_KEY_PARSE = "docqa.parse";

    @Bean
    public DirectExchange docqaExchange() {
        return new DirectExchange(EXCHANGE, true, false);
    }

    @Bean
    public Queue parseQueue() {
        return QueueBuilder.durable(QUEUE_PARSE).build();
    }

    @Bean
    public Binding parseBinding(Queue parseQueue, DirectExchange docqaExchange) {
        return BindingBuilder.bind(parseQueue).to(docqaExchange).with(ROUTING_KEY_PARSE);
    }
}
