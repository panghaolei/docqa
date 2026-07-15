package com.docqa.controller;

import com.docqa.dto.ApiResult;
import com.docqa.dto.AskRequest;
import com.docqa.dto.ChatMessageDto;
import com.docqa.entity.ChatSessionEntity;
import com.docqa.service.ChatSessionService;
import com.docqa.service.QaService;
import com.docqa.vector.SearchResult;
import jakarta.validation.Valid;
import org.springframework.http.MediaType;
import org.springframework.http.codec.ServerSentEvent;
import org.springframework.web.bind.annotation.*;
import reactor.core.publisher.Flux;

import java.time.Duration;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.atomic.AtomicReference;
import java.util.stream.Collectors;

@RestController
@RequestMapping("/chat")
public class ChatController {

    private final QaService qaService;
    private final ChatSessionService sessionService;

    public ChatController(QaService qaService, ChatSessionService sessionService) {
        this.qaService = qaService;
        this.sessionService = sessionService;
    }

    /**
     * 流式问答 SSE 接口
     * 事件类型：
     *  - session: 会话 ID
     *  - meta:    引用来源文档名（逗号分隔），可空
     *  - token:   回答内容分片
     *  - done:    结束标记
     */
    @PostMapping(value = "/ask/stream", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    public Flux<ServerSentEvent<String>> askStream(@Valid @RequestBody AskRequest req) {
        // 若无 sessionId 则新建
        Long sessionId = req.getSessionId();
        if (sessionId == null) {
            String title = req.getQuestion().length() > 20
                    ? req.getQuestion().substring(0, 20) + "..." : req.getQuestion();
            ChatSessionEntity s = sessionService.createSession(title);
            sessionId = s.getId();
        } else {
            sessionService.getSession(sessionId);
        }

        final Long sid = sessionId;
        AtomicReference<String> fullAnswer = new AtomicReference<>("");

        QaService.AnswerResult result = qaService.streamAnswer(sid, req.getQuestion());

        // 引用来源：去重后的文档名
        Set<String> refDocNames = new LinkedHashSet<>();
        if (result.sources() != null) {
            for (SearchResult sr : result.sources()) {
                refDocNames.add(sr.docName());
            }
        }
        String refs = refDocNames.isEmpty() ? "" : String.join(",", refDocNames);

        // 先发 session 与 meta 事件
        Flux<ServerSentEvent<String>> header = Flux.just(
                ServerSentEvent.<String>builder()
                        .event("session")
                        .data(String.valueOf(sid))
                        .build(),
                ServerSentEvent.<String>builder()
                        .event("meta")
                        .data(refs)
                        .build()
        );

        Flux<ServerSentEvent<String>> body = result.tokens().map(t -> {
            fullAnswer.accumulateAndGet(t, (old, n) -> old + n);
            return ServerSentEvent.<String>builder()
                    .event("token")
                    .data(t)
                    .build();
        });

        Flux<ServerSentEvent<String>> done = Flux.defer(() -> Flux.just(
                ServerSentEvent.<String>builder()
                        .event("done")
                        .data("[DONE]")
                        .build()
        ));

        return Flux.concat(header, body, done)
                // 保持连接，防止代理超时断开
                .mergeWith(Flux.interval(Duration.ofSeconds(15))
                        .map(i -> ServerSentEvent.<String>builder().comment("keep-alive").build()))
                .takeUntil(e -> e.event() != null && "done".equals(e.event()));
    }

    /**
     * 创建会话
     */
    @PostMapping("/session")
    public ApiResult<Map<String, Object>> createSession(@RequestBody(required = false) Map<String, String> body) {
        String title = body == null ? null : body.get("title");
        ChatSessionEntity s = sessionService.createSession(title);
        return ApiResult.success(Map.of("sessionId", s.getId(), "title", s.getTitle()));
    }

    @GetMapping("/sessions")
    public ApiResult<List<ChatSessionEntity>> sessions() {
        return ApiResult.success(sessionService.listSessions());
    }

    @GetMapping("/messages/{sessionId}")
    public ApiResult<List<ChatMessageDto>> messages(@PathVariable Long sessionId) {
        return ApiResult.success(sessionService.messages(sessionId));
    }

    @DeleteMapping("/session/{id}")
    public ApiResult<Void> deleteSession(@PathVariable Long id) {
        sessionService.deleteSession(id);
        return ApiResult.success();
    }
}
