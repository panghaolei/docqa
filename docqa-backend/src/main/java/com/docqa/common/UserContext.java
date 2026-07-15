package com.docqa.common;

import jakarta.servlet.http.HttpServletRequest;
import org.springframework.web.context.request.RequestContextHolder;
import org.springframework.web.context.request.ServletRequestAttributes;

/**
 * 从当前请求上下文中获取用户 ID
 */
public class UserContext {

    public static Long currentUserId() {
        ServletRequestAttributes attr =
                (ServletRequestAttributes) RequestContextHolder.getRequestAttributes();
        if (attr == null) return null;
        HttpServletRequest request = attr.getRequest();
        Object uid = request.getAttribute("userId");
        return uid == null ? null : (Long) uid;
    }
}
