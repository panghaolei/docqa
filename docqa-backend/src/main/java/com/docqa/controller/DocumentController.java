package com.docqa.controller;

import com.docqa.dto.ApiResult;
import com.docqa.dto.DocumentDto;
import com.docqa.service.DocumentService;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;
import java.util.List;

@RestController
@RequestMapping("/document")
public class DocumentController {

    private final DocumentService documentService;

    public DocumentController(DocumentService documentService) {
        this.documentService = documentService;
    }

    @PostMapping("/upload")
    public ApiResult<DocumentDto> upload(@RequestParam("file") MultipartFile file) throws IOException {
        if (file == null || file.isEmpty()) {
            return ApiResult.error(400, "文件不能为空");
        }
        return ApiResult.success(documentService.upload(file));
    }

    @GetMapping("/list")
    public ApiResult<List<DocumentDto>> list() {
        return ApiResult.success(documentService.listMine());
    }

    @DeleteMapping("/{id}")
    public ApiResult<Void> delete(@PathVariable Long id) throws IOException {
        documentService.delete(id);
        return ApiResult.success();
    }
}
