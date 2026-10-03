package com.docqa.service;

import com.docqa.common.UserContext;
import com.docqa.entity.DocumentEntity;
import com.docqa.repository.DocumentRepository;
import com.docqa.vector.SearchResult;
import com.docqa.vector.VectorService;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.chat.messages.*;
import org.springframework.ai.chat.prompt.Prompt;
import org.springframework.ai.chat.prompt.PromptTemplate;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import reactor.core.publisher.Flux;

import java.util.*;
import java.util.regex.Pattern;
import java.util.stream.Collectors;

/**
 * 问答服务：RAG 检索 + Spring AI ChatClient 流式生成。
 *
 * 优化点：
 *  1. 闲聊/问候本地规则匹配，不调用大模型；
 *  2. 无已解析文档时直接提示，跳过 Embedding + Chat；
 *  3. 向量检索结果按相似度阈值过滤，低于阈值不调用大模型；
 *  4. 去掉「检索为空时塞全部文档原文」的兜底逻辑（避免无谓 token 消耗）；
 *  5. 上下文按文档名分组并标注来源。
 */
@Service
public class QaService {

    private static final Logger log = LoggerFactory.getLogger(QaService.class);

    /** 闲聊/问候关键词：命中则本地直接回复，不消耗 API */
    private static final Pattern CHITCHAT_PATTERN = Pattern.compile(
            "^(你好|您好|hi|hello|hey|嗨|在吗|谢谢|感谢|thx|thanks|好的|ok|再见|拜拜|bye" +
            "|你是谁|你叫什么|介绍一下你自己|你能做什么|帮助|help).*$",
            Pattern.CASE_INSENSITIVE);

    private final ChatClient chatClient;
    private final VectorService vectorService;
    private final ChatSessionService sessionService;
    private final DocumentRepository documentRepository;

    @Value("${docqa.rag.top-k:4}")
    private int topK;

    @Value("${docqa.rag.similarity-threshold:0.35}")
    private double similarityThreshold;

    @Value("${docqa.rag.system-prompt}")
    private String systemPrompt;

    @Value("${docqa.rag.prompt-template}")
    private String promptTemplate;

    @Value("${docqa.history.max-rounds:6}")
    private int maxRounds;

    public QaService(ChatClient chatClient,
                     VectorService vectorService,
                     ChatSessionService sessionService,
                     DocumentRepository documentRepository) {
        this.chatClient = chatClient;
        this.vectorService = vectorService;
        this.sessionService = sessionService;
        this.documentRepository = documentRepository;
    }

    /**
     * 流式问答：返回 token 流与引用来源。
     * 短路场景下 tokens 为单元素 Flux，sources 为空。
     */
    public AnswerResult streamAnswer(Long sessionId, String question) {
        // 0. 闲聊短路
        if (isChitchat(question)) {
            log.info("会话 {} 命中闲聊规则，本地回复（不调用大模型）", sessionId);
            String reply = localChitchatReply(question);
            persistExchange(sessionId, question, reply, List.of());
            return new AnswerResult(Flux.just(reply), List.of());
        }

        // 1. 无已解析文档短路：不调 Embedding / Chat
        long doneCount = countReadyDocs();
        if (doneCount == 0) {
            log.info("会话 {} 无已解析文档，直接提示（不调用大模型）", sessionId);
            String reply = "当前还没有可用的文档。请先在左侧上传文档（支持 PDF / Word / TXT / Markdown / HTML），"
                    + "文档解析完成后即可基于内容进行问答。";
            persistExchange(sessionId, question, reply, List.of());
            return new AnswerResult(Flux.just(reply), List.of());
        }

        // 2. 向量检索（带相似度阈值过滤）
        List<SearchResult> hits;
        try {
            hits = vectorService.searchWithMeta(question, topK, similarityThreshold, UserContext.currentUserId());
        } catch (Exception e) {
            log.warn("会话 {} 向量检索异常，提示用户: {}", sessionId, e.getMessage());
            String reply = "抱歉，检索服务暂时不可用，请稍后再试或检查 Embedding 配置。";
            persistExchange(sessionId, question, reply, List.of());
            return new AnswerResult(Flux.just(reply), List.of());
        }
        log.info("会话 {} 向量检索到 {} 条相关片段（阈值 {}）", sessionId, hits.size(), similarityThreshold);

        // 3. 检索为空：不调大模型，直接提示
        if (hits.isEmpty()) {
            log.info("会话 {} 未检索到相关内容，不调用大模型", sessionId);
            String reply = "根据当前已上传的文档，未检索到与该问题相关的内容。\n\n"
                    + "你可以：\n"
                    + "- 换个更具体的关键词重新提问；\n"
                    + "- 上传更多相关文档扩充知识库；\n"
                    + "- 确认文档是否已解析完成（左侧文档状态为「已完成」）。";
            persistExchange(sessionId, question, reply, List.of());
            return new AnswerResult(Flux.just(reply), List.of());
        }

        // 4. 组装上下文：按文档名分组，标注来源
        String context = buildContext(hits);

        // 5. 构造 RAG Prompt
        PromptTemplate pt = new PromptTemplate(promptTemplate);
        String userContent = pt.render(Map.of("context", context, "question", question));

        // 6. 组装消息序列：system + history + user
        List<Message> messages = new ArrayList<>();
        messages.add(new SystemMessage(systemPrompt));
        List<ChatSessionService.HistoryItem> history =
                sessionService.recentHistory(sessionId, maxRounds);
        for (ChatSessionService.HistoryItem h : history) {
            if ("USER".equalsIgnoreCase(h.role())) {
                messages.add(new UserMessage(h.content()));
            } else {
                messages.add(new AssistantMessage(h.content()));
            }
        }
        messages.add(new UserMessage(userContent));

        // 7. 记录用户问题到历史
        sessionService.appendHistory(sessionId, "USER", question);

        // 8. 流式调用
        Prompt prompt = new Prompt(messages);
        String referencesLine = hits.stream()
                .map(SearchResult::docName)
                .distinct()
                .collect(Collectors.joining("、"));

        Flux<String> tokenFlux = chatClient.prompt(prompt)
                .stream()
                .content()
                .doOnComplete(() -> log.info("会话 {} 流式回答完成", sessionId))
                .doOnError(e -> log.error("会话 {} 流式回答异常", sessionId, e));

        // 9. 缓冲完整回答并写回历史 + 消息表
        StringBuilder full = new StringBuilder();
        Flux<String> wrapped = tokenFlux
                .doOnNext(full::append)
                .doOnComplete(() -> {
                    String answer = full.toString();
                    String refs = referencesLine.isEmpty() ? null : referencesLine;
                    String ctxRefs = hits.stream().map(SearchResult::content)
                            .collect(Collectors.joining("\n---\n"));
                    sessionService.appendHistory(sessionId, "ASSISTANT", answer);
                    sessionService.saveMessage(sessionId, "USER", question, null);
                    sessionService.saveMessage(sessionId, "ASSISTANT", answer, refs == null ? ctxRefs : refs);
                });

        return new AnswerResult(wrapped, hits);
    }

    /** 计算已解析完成（DONE）的文档数量 */
    private long countReadyDocs() {
        try {
            Long userId = UserContext.currentUserId();
            return documentRepository.findByUserIdOrderByCreatedAtDesc(userId).stream()
                    .filter(d -> "DONE".equals(d.getStatus()))
                    .count();
        } catch (Exception e) {
            log.warn("查询已解析文档数失败: {}", e.getMessage());
            return 0;
        }
    }

    /** 按文档名分组组装上下文，每段标注来源 */
    private String buildContext(List<SearchResult> hits) {
        Map<String, List<String>> grouped = new LinkedHashMap<>();
        for (SearchResult h : hits) {
            grouped.computeIfAbsent(h.docName(), k -> new ArrayList<>()).add(h.content());
        }
        StringBuilder sb = new StringBuilder();
        int idx = 1;
        for (Map.Entry<String, List<String>> e : grouped.entrySet()) {
            sb.append("【来源文档：").append(e.getKey()).append("】\n");
            for (String c : e.getValue()) {
                sb.append(idx++).append(". ").append(c).append("\n");
            }
            sb.append("\n");
        }
        return sb.toString().trim();
    }

    /** 闲聊判定 */
    private boolean isChitchat(String q) {
        if (q == null) return false;
        String trimmed = q.trim();
        if (trimmed.length() > 30) return false;
        return CHITCHAT_PATTERN.matcher(trimmed).matches();
    }

    /** 本地闲聊回复 */
    private String localChitchatReply(String q) {
        String s = q.trim();
        if (s.matches("(?i).*(谢谢|感谢|thx|thanks).*")) {
            return "不客气！如果还有文档相关的问题，随时问我。";
        }
        if (s.matches("(?i).*(你好|您好|hi|hello|hey|嗨|在吗).*")) {
            return "你好！我是智能文档问答助手。请先在左侧上传文档，之后我就能基于文档内容回答你的问题啦。";
        }
        if (s.matches("(?i).*(再见|拜拜|bye).*")) {
            return "再见！随时欢迎回来提问。";
        }
        if (s.matches("(?i).*(你是谁|你叫什么|介绍一下你自己|你能做什么|帮助|help).*")) {
            return "我是「智能文档问答助手」，专门基于你上传的文档内容回答问题。\n\n"
                    + "我可以：\n"
                    + "- 帮你快速定位文档中的关键信息；\n"
                    + "- 总结、解释文档内容；\n"
                    + "- 基于文档回答具体问题，并标注来源。\n\n"
                    + "请先在左侧上传文档，然后向我提问吧。";
        }
        if (s.matches("(?i).*(好的|ok).*")) {
            return "好的，有什么文档相关的问题需要我帮忙吗？";
        }
        return "我主要负责基于已上传文档进行问答。请先上传文档，然后提出你的问题。";
    }

    /** 持久化一轮对话（用户问题 + AI 回答 + 用户消息记录） */
    private void persistExchange(Long sessionId, String question, String answer, List<String> ctxSnippets) {
        try {
            sessionService.appendHistory(sessionId, "USER", question);
            sessionService.appendHistory(sessionId, "ASSISTANT", answer);
            sessionService.saveMessage(sessionId, "USER", question, null);
            String refs = ctxSnippets == null || ctxSnippets.isEmpty()
                    ? null : String.join("\n---\n", ctxSnippets);
            sessionService.saveMessage(sessionId, "ASSISTANT", answer, refs);
        } catch (Exception e) {
            log.warn("持久化对话失败（不影响响应）: {}", e.getMessage());
        }
    }

    /** 流式回答结果：token 流 + 引用来源列表 */
    public record AnswerResult(Flux<String> tokens, List<SearchResult> sources) {}
}
