package com.docqa.common;

import com.docqa.entity.UserEntity;
import com.docqa.repository.UserRepository;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.stereotype.Component;
import org.springframework.web.servlet.HandlerInterceptor;

/**
 * 简易 Token 拦截器：从请求头 Authorization 解析 token，校验后将 userId 放入 request attribute。
 */
@Component
public class TokenInterceptor implements HandlerInterceptor {

    private final UserRepository userRepository;

    public TokenInterceptor(UserRepository userRepository) {
        this.userRepository = userRepository;
    }

    @Override
    public boolean preHandle(HttpServletRequest request, HttpServletResponse response, Object handler) throws Exception {
        // 放行 OPTIONS 预检
        if ("OPTIONS".equalsIgnoreCase(request.getMethod())) {
            return true;
        }
        String auth = request.getHeader("Authorization");
        if (auth == null || auth.isBlank()) {
            response.setStatus(401);
            response.setContentType("application/json;charset=UTF-8");
            response.getWriter().write("{\"code\":401,\"message\":\"未登录\"}");
            return false;
        }
        String token = auth.startsWith("Bearer ") ? auth.substring(7) : auth;
        return userRepository.findByToken(token).map(user -> {
            request.setAttribute("userId", user.getId());
            request.setAttribute("username", user.getUsername());
            return true;
        }).orElseGet(() -> {
            try {
                response.setStatus(401);
                response.setContentType("application/json;charset=UTF-8");
                response.getWriter().write("{\"code\":401,\"message\":\"Token 无效\"}");
            } catch (Exception ignored) {
            }
            return false;
        });
    }
}
