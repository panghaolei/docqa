package com.docqa.repository;

import com.docqa.entity.ChatSessionEntity;
import org.springframework.data.jpa.repository.JpaRepository;
import java.util.List;

public interface ChatSessionRepository extends JpaRepository<ChatSessionEntity, Long> {
    List<ChatSessionEntity> findByUserIdOrderByUpdatedAtDesc(Long userId);
}
