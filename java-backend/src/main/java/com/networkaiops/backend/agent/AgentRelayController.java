package com.networkaiops.backend.agent;

import com.fasterxml.jackson.databind.JsonNode;
import com.networkaiops.backend.common.BusinessException;
import com.networkaiops.backend.security.WorkspacePrincipal;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.core.io.ByteArrayResource;
import org.springframework.http.*;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.util.LinkedMultiValueMap;
import org.springframework.util.MultiValueMap;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;

/**
 * Explicit endpoint allowlist, not a catch-all open reverse proxy. Python retains data ACL
 * enforcement.
 */
@RestController
@RequestMapping("/api/v1")
public class AgentRelayController {
  private final AgentClient agent;

  public AgentRelayController(AgentClient agent) {
    this.agent = agent;
  }

  @GetMapping({
    "/sessions",
    "/sessions/{sid}",
    "/sessions/{sid}/messages",
    "/requests/{rid}",
    "/requests/{rid}/queries/{qid}/review",
    "/requests/{rid}/queries/{qid}/metric-candidate",
    "/knowledge/documents",
    "/knowledge/documents/{did}",
    "/metrics",
    "/metrics/reviewed",
    "/governance/cases",
    "/governance/cases/{cid}"
  })
  ResponseEntity<JsonNode> get(
      HttpServletRequest request, @AuthenticationPrincipal WorkspacePrincipal user) {
    return relay(request, user, null);
  }

  @PostMapping({
    "/sessions",
    "/chat",
    "/sessions/{sid}/resume",
    "/metrics/resolve",
    "/requests/{rid}/queries/{qid}/metric",
    "/governance/cases/{cid}/verify",
    "/governance/collect",
    "/governance/capture/{rid}",
    "/knowledge/reindex"
  })
  ResponseEntity<JsonNode> post(
      HttpServletRequest request,
      @AuthenticationPrincipal WorkspacePrincipal user,
      @RequestBody(required = false) JsonNode body) {
    return relay(request, user, body);
  }

  @PutMapping("/requests/{rid}/queries/{qid}/review")
  ResponseEntity<JsonNode> put(
      HttpServletRequest request,
      @AuthenticationPrincipal WorkspacePrincipal user,
      @RequestBody JsonNode body) {
    return relay(request, user, body);
  }

  @PatchMapping("/governance/cases/{cid}")
  ResponseEntity<JsonNode> patch(
      HttpServletRequest request,
      @AuthenticationPrincipal WorkspacePrincipal user,
      @RequestBody JsonNode body) {
    return relay(request, user, body);
  }

  @DeleteMapping({"/sessions/{sid}", "/knowledge/documents/{did}", "/metrics/reviewed/{mid}"})
  ResponseEntity<JsonNode> delete(
      HttpServletRequest request, @AuthenticationPrincipal WorkspacePrincipal user) {
    return relay(request, user, null);
  }

  @PostMapping(value = "/knowledge/documents", consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
  ResponseEntity<JsonNode> upload(
      HttpServletRequest request,
      @AuthenticationPrincipal WorkspacePrincipal user,
      @RequestPart MultipartFile file,
      @RequestParam(defaultValue = "") String title)
      throws java.io.IOException {
    requireAdmin(user);
    agent.requireEnabled();
    if (file.getSize() > 10 * 1024 * 1024 || title.length() > 100)
      throw new BusinessException(413, "upload_too_large", "文档或标题超过允许的大小。");
    String filename =
        file.getOriginalFilename() == null
            ? "document"
            : file.getOriginalFilename().replace('\\', '/');
    filename = filename.substring(filename.lastIndexOf('/') + 1);
    if (filename.isBlank() || filename.chars().anyMatch(c -> c < 32))
      throw new BusinessException("文件名无效。");
    String finalName = filename;
    var resource =
        new ByteArrayResource(file.getBytes()) {
          @Override
          public String getFilename() {
            return finalName;
          }
        };
    MultiValueMap<String, Object> body = new LinkedMultiValueMap<>();
    body.add("file", resource);
    body.add("title", title);
    String token = request.getHeader("Authorization");
    agent.verifyIdentity(token, user);
    return agent.exchange(
        HttpMethod.POST, "/api/v1/knowledge/documents", body, token, MediaType.MULTIPART_FORM_DATA);
  }

  private ResponseEntity<JsonNode> relay(
      HttpServletRequest request, WorkspacePrincipal user, Object body) {
    String path = request.getRequestURI();
    if (!"GET".equals(request.getMethod()) && path.startsWith("/api/v1/knowledge/"))
      requireAdmin(user);
    if (request.getContentLengthLong() > 1024 * 1024)
      throw new BusinessException(413, "request_too_large", "请求内容超过 1 MB。");
    String token = request.getHeader("Authorization");
    agent.verifyIdentity(token, user);
    if (request.getQueryString() != null) path += "?" + request.getQueryString();
    return agent.exchange(HttpMethod.valueOf(request.getMethod()), path, body, token, null);
  }

  private void requireAdmin(WorkspacePrincipal user) {
    if (!"admin".equals(user.role()))
      throw new BusinessException(403, "forbidden", "知识资料变更仅对管理员开放。");
  }
}
