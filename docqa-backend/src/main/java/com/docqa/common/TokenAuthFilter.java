package com.docqa.common;

import com.docqa.entity.UserEntity;
import com.docqa.repository.UserRepository;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.core.annotation.Order;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;

/**
 * 基于 Servlet Filter 的 Token 鉴权。
 *
 * 为什么用 Filter 而非 HandlerInterceptor：
 * HttpMediaTypeNotAcceptableException 等异常在 DispatcherServlet 的 HandlerMapping 阶段抛出，
 * 早于拦截器 preHandle，导致流式接口（produces=text/event-stream）在未携带 token 时也能返回 200。
 * Filter 运行在 DispatcherServlet 之前，能确保所有请求先过鉴权，返回 401。
 */
@Component
@Order(1)
public class TokenAuthFilter extends OncePerRequestFilter {

    private final UserRepository userRepository;

    public TokenAuthFilter(UserRepository userRepository) {
        this.userRepository = userRepository;
    }

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response, FilterChain chain)
            throws ServletException, IOException {
        // CORS 预检放行
        if ("OPTIONS".equalsIgnoreCase(request.getMethod())) {
            chain.doFilter(request, response);
            return;
        }

        // 白名单放行（去掉 context-path 后比较）
        String contextPath = request.getContextPath();
        String uri = request.getRequestURI();
        String path = (contextPath != null && !contextPath.isEmpty() && uri.startsWith(contextPath))
                ? uri.substring(contextPath.length()) : uri;
        if ("/user/login".equals(path) || "/error".equals(path) || "/favicon.ico".equals(path)) {
            chain.doFilter(request, response);
            return;
        }

        String auth = request.getHeader("Authorization");
        if (auth == null || auth.isBlank()) {
            write401(response, "未登录");
            return;
        }
        String token = auth.startsWith("Bearer ") ? auth.substring(7) : auth;

        UserEntity user = userRepository.findByToken(token).orElse(null);
        if (user == null) {
            write401(response, "Token 无效");
            return;
        }
        request.setAttribute("userId", user.getId());
        request.setAttribute("username", user.getUsername());
        chain.doFilter(request, response);
    }

    private void write401(HttpServletResponse response, String message) throws IOException {
        response.setStatus(401);
        response.setContentType("application/json;charset=UTF-8");
        response.getWriter().write("{\"code\":401,\"message\":\"" + message + "\"}");
    }
}
