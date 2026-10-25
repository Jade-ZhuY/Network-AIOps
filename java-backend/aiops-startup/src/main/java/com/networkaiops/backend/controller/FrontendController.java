package com.networkaiops.backend.controller;

import com.networkaiops.backend.common.exception.BusinessException;
import java.nio.file.Files;
import java.nio.file.Path;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.io.FileSystemResource;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Controller;
import org.springframework.web.bind.annotation.GetMapping;

@Controller
public class FrontendController {
  private final Path entry;

  public FrontendController(@Value("${workspace.frontend-path}") String path) {
    entry = Path.of(path).toAbsolutePath().normalize().resolve("index.html");
  }

  @GetMapping("/")
  ResponseEntity<FileSystemResource> index() {
    if (!Files.isRegularFile(entry))
      throw new BusinessException(
          503, "frontend_build_required", "请先在 frontend 目录执行 npm ci 和 npm run build。");
    return ResponseEntity.ok()
        .header("Cache-Control", "no-cache")
        .contentType(MediaType.TEXT_HTML)
        .body(new FileSystemResource(entry));
  }

  @GetMapping("/docs")
  String docs() {
    return "forward:/api-docs.html";
  }
}
