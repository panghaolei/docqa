package com.docqa.config;

import org.springframework.ai.chat.client.ChatClient;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * Spring AI ChatClient 配置。
 * SiliconFlow 兼容 OpenAI 协议，starter 已自动装配 OpenAiChatModel，
 * 这里通过 Builder 注入默认系统提示等。
 */
@Configuration
public class AiConfig {

    @Bean
    public ChatClient chatClient(ChatClient.Builder builder) {
        return builder.build();
    }
}
