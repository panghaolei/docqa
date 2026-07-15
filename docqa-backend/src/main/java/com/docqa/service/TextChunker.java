package com.docqa.service;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.List;

/**
 * 文本切片器：按固定字符长度滑动窗口切片
 */
@Service
public class TextChunker {

    @Value("${docqa.chunk.size:500}")
    private int chunkSize;

    @Value("${docqa.chunk.overlap:80}")
    private int overlap;

    /**
     * 将长文本切片为多个片段
     */
    public List<String> chunk(String text) {
        List<String> chunks = new ArrayList<>();
        if (text == null || text.isBlank()) {
            return chunks;
        }
        // 清理多余空白
        String cleaned = text.replaceAll("\\s+", " ").trim();
        int len = cleaned.length();
        if (len <= chunkSize) {
            chunks.add(cleaned);
            return chunks;
        }
        int step = chunkSize - overlap;
        if (step <= 0) step = chunkSize;
        for (int start = 0; start < len; start += step) {
            int end = Math.min(start + chunkSize, len);
            chunks.add(cleaned.substring(start, end));
            if (end == len) break;
        }
        return chunks;
    }
}
