package com.docqa.service;

import org.apache.tika.config.TikaConfig;
import org.apache.tika.exception.TikaException;
import org.apache.tika.metadata.Metadata;
import org.apache.tika.parser.AutoDetectParser;
import org.apache.tika.parser.ParseContext;
import org.apache.tika.parser.Parser;
import org.apache.tika.parser.pdf.PDFParserConfig;
import org.apache.tika.sax.BodyContentHandler;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import org.xml.sax.ContentHandler;

import java.io.InputStream;

/**
 * 基于 Apache Tika 的统一文档解析器
 * 支持 PDF / Word / TXT / HTML / Markdown 等格式
 *
 * 针对增强 PDF 解析：
 *  - 使用 AutoDetectParser 自动识别格式
 *  - PDFParserConfig 开启 OCR 降级、提取内嵌内容、sort-by-position
 *  - BodyContentHandler 设置巨大 writeLimit 避免截断
 */
@Service
public class DocumentParser {

    private static final Logger log = LoggerFactory.getLogger(DocumentParser.class);

    /**
     * 解析输入流为纯文本
     */
    public String parse(InputStream stream) throws Exception {
        // 1. 配置 ContentHandler，设置足够大的 writeLimit（-1 为无限制）
        BodyContentHandler handler = new BodyContentHandler(-1);

        // 2. 配置 PDF 解析参数
        PDFParserConfig pdfConfig = new PDFParserConfig();
        pdfConfig.setExtractInlineImages(true);        // 提取内嵌图片
        pdfConfig.setExtractUniqueInlineImagesOnly(false);
        pdfConfig.setSortByPosition(true);             // 按位置排序，改善排版提取
        pdfConfig.setSuppressDuplicateOverlappingText(true); // 去重复重叠文本
        // 如果 PDF 是扫描件，尝试 OCR（需要 Tesseract，没装则自动跳过）
        pdfConfig.setOcrStrategy(PDFParserConfig.OCR_STRATEGY.AUTO);

        // 3. 构建 ParseContext
        ParseContext context = new ParseContext();
        context.set(PDFParserConfig.class, pdfConfig);

        // 4. 使用 AutoDetectParser 自动识别文件类型
        Parser parser = new AutoDetectParser();

        Metadata metadata = new Metadata();

        log.info("开始解析文档...");
        try {
            parser.parse(stream, handler, metadata, context);
        } catch (TikaException e) {
            log.warn("Tika 解析异常（可能部分内容丢失）: {}", e.getMessage());
            // 不中断，返回已解析的部分
        }

        String text = handler.toString();
        String contentType = metadata.get("Content-Type");
        log.info("解析完成 contentType={} 文本长度={} 字符", contentType, text.length());

        if (text == null || text.isBlank()) {
            log.warn("解析结果为空！contentType={} metadata keys: {}", contentType, metadata.names());
            throw new RuntimeException("文档解析结果为空，可能为扫描件/图片型 PDF 或文件损坏");
        }

        return text;
    }
}
