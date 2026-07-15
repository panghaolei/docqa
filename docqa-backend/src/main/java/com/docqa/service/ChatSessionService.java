package com.docqa.service;

import com.docqa.common.UserContext;
import com.docqa.dto.ChatMessageDto;
import com.docqa.entity.ChatMessageEntity;
import com.docqa.entity.ChatSessionEntity;
import com.docqa.repository.ChatMessageRepository;
import com.docqa.repository.ChatSessionRepository;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.data.redis.core.RedisTemplate;
import org.springframework.stereotype.Service;

import java.time.format.DateTimeFormatter;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.TimeUnit;
import java.util.stream.Collectors;

/**
 * 会话与消息服务：
 *  - MySQL 持久化会话与消息
 *  - Redis 缓存最近 N 轮对话历史（用于 LLM 上下文）
 *  - Redis 不可用时自动降级为内存缓存
 */
@Service
public class ChatSessionService {

    private static final Logger log = LoggerFactory.getLogger(ChatSessionService.class);
    private static final DateTimeFormatter FMT = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss");
    private static final String HISTORY_KEY = "docqa:history:";

    private final ChatSessionRepository sessionRepository;
    private final ChatMessageRepository messageRepository;
    private final RedisTemplate<String, Object> redisTemplate;

    /** 内存降级缓存：Redis 不可用时使用 */
    private final Map<Long, List<HistoryItem>> memoryHistory = new ConcurrentHashMap<>();

    public ChatSessionService(ChatSessionRepository sessionRepository,
                              ChatMessageRepository messageRepository,
                              RedisTemplate<String, Object> redisTemplate) {
        this.sessionRepository = sessionRepository;
        this.messageRepository = messageRepository;
        this.redisTemplate = redisTemplate;
    }

    public ChatSessionEntity createSession(String title) {
        Long userId = UserContext.currentUserId();
        ChatSessionEntity s = new ChatSessionEntity();
        s.setTitle(title == null || title.isBlank() ? "新对话" : title);
        s.setUserId(userId);
        return sessionRepository.save(s);
    }

    public List<ChatSessionEntity> listSessions() {
        Long userId = UserContext.currentUserId();
        return sessionRepository.findByUserIdOrderByUpdatedAtDesc(userId);
    }

    public ChatSessionEntity getSession(Long id) {
        return sessionRepository.findById(id)
                .orElseThrow(() -> new RuntimeException("会话不存在"));
    }

    public List<ChatMessageDto> messages(Long sessionId) {
        return messageRepository.findBySessionIdOrderByCreatedAtAsc(sessionId).stream()
                .map(this::toDto)
                .collect(Collectors.toList());
    }

    public ChatMessageEntity saveMessage(Long sessionId, String role, String content, String references) {
        ChatMessageEntity m = new ChatMessageEntity();
        m.setSessionId(sessionId);
        m.setRole(role);
        m.setContent(content);
        m.setReferences(references);
        return messageRepository.save(m);
    }

    /**
     * 从 Redis 读取最近对话历史（用于 LLM 上下文），Redis 异常时降级内存
     */
    @SuppressWarnings("unchecked")
    public List<HistoryItem> recentHistory(Long sessionId, int maxRounds) {
        // 先尝试 Redis
        try {
            Object obj = redisTemplate.opsForValue().get(HISTORY_KEY + sessionId);
            if (obj instanceof List) {
                List<HistoryItem> all = (List<HistoryItem>) obj;
                int from = Math.max(0, all.size() - maxRounds * 2);
                return all.subList(from, all.size());
            }
            return List.of();
        } catch (Exception e) {
            log.warn("Redis 读取历史失败，降级内存: {}", e.getMessage());
            List<HistoryItem> all = memoryHistory.get(sessionId);
            if (all == null) return List.of();
            int from = Math.max(0, all.size() - maxRounds * 2);
            return all.subList(from, all.size());
        }
    }

    public void appendHistory(Long sessionId, String role, String content) {
        // 内存缓存（始终写入，作为 Redis 降级兜底）
        memoryHistory.computeIfAbsent(sessionId, k -> new CopyOnWriteArrayList<>()).add(new HistoryItem(role, content));

        // 尝试写入 Redis（失败不影响流程）
        try {
            String key = HISTORY_KEY + sessionId;
            List<HistoryItem> list;
            Object obj = redisTemplate.opsForValue().get(key);
            if (obj instanceof List) {
                list = (List<HistoryItem>) obj;
            } else {
                list = new java.util.ArrayList<>();
            }
            list.add(new HistoryItem(role, content));
            redisTemplate.opsForValue().set(key, list, 2, TimeUnit.HOURS);
        } catch (Exception e) {
            log.warn("Redis 写入历史失败，使用内存降级: {}", e.getMessage());
        }
    }

    public void deleteSession(Long id) {
        messageRepository.findBySessionIdOrderByCreatedAtAsc(id)
                .forEach(m -> messageRepository.delete(m));
        sessionRepository.deleteById(id);
        memoryHistory.remove(id);
        try {
            redisTemplate.delete(HISTORY_KEY + id);
        } catch (Exception e) {
            log.warn("Redis 删除历史失败，忽略: {}", e.getMessage());
        }
    }

    private ChatMessageDto toDto(ChatMessageEntity m) {
        ChatMessageDto dto = new ChatMessageDto();
        dto.setId(m.getId());
        dto.setRole(m.getRole());
        dto.setContent(m.getContent());
        dto.setReferences(m.getReferences());
        dto.setCreatedAt(m.getCreatedAt() == null ? null : m.getCreatedAt().format(FMT));
        return dto;
    }

    /** Redis 中缓存的对话历史条目 */
    public record HistoryItem(String role, String content) {}
}
