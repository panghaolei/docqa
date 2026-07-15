package com.docqa.common;

import com.docqa.dto.ApiResult;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

@RestControllerAdvice
public class GlobalExceptionHandler {

    private static final Logger log = LoggerFactory.getLogger(GlobalExceptionHandler.class);

    @ExceptionHandler(IllegalArgumentException.class)
    public ApiResult<?> illegal(IllegalArgumentException e) {
        return ApiResult.error(400, e.getMessage());
    }

    @ExceptionHandler(Exception.class)
    public ApiResult<?> other(Exception e) {
        log.error("未处理异常", e);
        return ApiResult.error(500, e.getMessage() == null ? "服务器内部错误" : e.getMessage());
    }
}
