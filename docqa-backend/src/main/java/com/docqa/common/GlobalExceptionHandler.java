package com.docqa.common;

import com.docqa.dto.ApiResult;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.multipart.MultipartException;
import org.springframework.web.multipart.support.MissingServletRequestPartException;

@RestControllerAdvice
public class GlobalExceptionHandler {

    private static final Logger log = LoggerFactory.getLogger(GlobalExceptionHandler.class);

    @ExceptionHandler(IllegalArgumentException.class)
    public ApiResult<?> illegal(IllegalArgumentException e) {
        return ApiResult.error(400, e.getMessage());
    }

    /** 文件上传参数错误：非 multipart 请求 / 缺少 file 字段，属于客户端参数错误，映射为 400 */
    @ExceptionHandler({MultipartException.class, MissingServletRequestPartException.class})
    public ApiResult<?> multipart(Exception e) {
        return ApiResult.error(400, "请求不是有效的文件上传，或缺少 file 字段");
    }

    /** 数据库约束冲突（如 title 超出列长度）：映射为 400 参数错误，而非 500 */
    @ExceptionHandler(DataIntegrityViolationException.class)
    public ApiResult<?> dataIntegrity(DataIntegrityViolationException e) {
        log.warn("数据约束冲突: {}", e.getMessage());
        return ApiResult.error(400, "数据不符合约束，请检查输入内容（如标题过长）");
    }

    @ExceptionHandler(Exception.class)
    public ApiResult<?> other(Exception e) {
        log.error("未处理异常", e);
        return ApiResult.error(500, e.getMessage() == null ? "服务器内部错误" : e.getMessage());
    }
}
