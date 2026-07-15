-- 智能文档问答系统 MySQL 初始化脚本
-- 由 Docker MySQL 容器在首次启动时自动执行（已挂载至 /docker-entrypoint-initdb.d）

CREATE DATABASE IF NOT EXISTS docqa DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE docqa;

-- 用户表
CREATE TABLE IF NOT EXISTS sys_user (
    id          BIGINT AUTO_INCREMENT PRIMARY KEY,
    username    VARCHAR(64)  NOT NULL UNIQUE COMMENT '用户名',
    token       VARCHAR(128) UNIQUE COMMENT '访问令牌',
    created_at  DATETIME     DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='用户表';

-- 文档表
CREATE TABLE IF NOT EXISTS doc_info (
    id           BIGINT AUTO_INCREMENT PRIMARY KEY,
    file_name    VARCHAR(255) NOT NULL COMMENT '原始文件名',
    file_path    VARCHAR(512) COMMENT '存储路径',
    file_size    BIGINT COMMENT '文件大小(字节)',
    file_type    VARCHAR(32) COMMENT '文件类型',
    content      MEDIUMTEXT COMMENT '解析后的纯文本(截断)',
    chunk_count  INT COMMENT '切片数量',
    status       VARCHAR(32) DEFAULT 'PENDING' COMMENT '处理状态',
    error_msg    VARCHAR(1024) COMMENT '错误信息',
    user_id      BIGINT COMMENT '所属用户',
    created_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at   DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='文档元数据表';

-- 会话表
CREATE TABLE IF NOT EXISTS chat_session (
    id          BIGINT AUTO_INCREMENT PRIMARY KEY,
    title       VARCHAR(200) COMMENT '会话标题',
    user_id     BIGINT NOT NULL,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at  DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='对话会话表';

-- 消息表
CREATE TABLE IF NOT EXISTS chat_message (
    id          BIGINT AUTO_INCREMENT PRIMARY KEY,
    session_id  BIGINT NOT NULL,
    role        VARCHAR(16) NOT NULL COMMENT 'USER / ASSISTANT',
    content     MEDIUMTEXT NOT NULL,
    references  TEXT COMMENT '引用片段',
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='对话消息表';

-- 建议索引
CREATE INDEX idx_doc_user       ON doc_info(user_id);
CREATE INDEX idx_session_user   ON chat_session(user_id);
CREATE INDEX idx_msg_session    ON chat_message(session_id);
