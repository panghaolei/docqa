package com.docqa.entity;

import jakarta.persistence.*;
import lombok.Data;
import java.time.LocalDateTime;

/**
 * 用户实体
 * 为简化演示：使用单一 token 作为会话凭证，无密码登录。
 */
@Data
@Entity
@Table(name = "sys_user")
public class UserEntity {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    /** 用户名 */
    @Column(nullable = false, unique = true, length = 64)
    private String username;

    /** 访问令牌（前端请求头携带） */
    @Column(unique = true, length = 128)
    private String token;

    @Column(name = "created_at")
    private LocalDateTime createdAt = LocalDateTime.now();
}
