package com.docqa.service;

import com.docqa.dto.LoginResponse;
import com.docqa.entity.UserEntity;
import com.docqa.repository.UserRepository;
import org.springframework.stereotype.Service;

import java.util.UUID;

/**
 * 用户服务：简化登录（用户名直接发放 token）
 */
@Service
public class UserService {

    private final UserRepository userRepository;

    public UserService(UserRepository userRepository) {
        this.userRepository = userRepository;
    }

    public LoginResponse login(String username) {
        if (username == null || username.isBlank()) {
            throw new IllegalArgumentException("用户名不能为空");
        }
        UserEntity user = userRepository.findByUsername(username.trim()).orElseGet(() -> {
            UserEntity u = new UserEntity();
            u.setUsername(username.trim());
            u.setToken(UUID.randomUUID().toString().replace("-", ""));
            return userRepository.save(u);
        });
        // 若已有用户则刷新 token
        if (user.getToken() == null || user.getToken().isBlank()) {
            user.setToken(UUID.randomUUID().toString().replace("-", ""));
            userRepository.save(user);
        }
        LoginResponse resp = new LoginResponse();
        resp.setUserId(user.getId());
        resp.setUsername(user.getUsername());
        resp.setToken(user.getToken());
        return resp;
    }
}
