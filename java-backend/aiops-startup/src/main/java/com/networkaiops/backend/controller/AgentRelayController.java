package com.networkaiops.backend.controller;

import com.fasterxml.jackson.databind.JsonNode;
import com.networkaiops.backend.agent.client.AgentClient;
import com.networkaiops.backend.business.audit.AuditRepository;
import com.networkaiops.backend.common.exception.BusinessException;
import com.networkaiops.backend.common.identity.WorkspacePrincipal;
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
 * enforcement. Knowledge mutations additionally leave a Java-side audit trail, because they change
 * what later AI analyses will retrieve.
 */
@RestController
@RequestMapping("/api/v1")
public class AgentRelayController {
  private final AgentClient agent;
  private final AuditRepository audit;

  public AgentRelayController(AgentClient agent, AuditRepository audit) {
    this.agent = agent;
    this.audit = audit;
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
    String note = title.isBlank() ? finalName : finalName + " | " + title;
    try {
      agent.verifyIdentity(token, user);
      ResponseEntity<JsonNode> response =
          agent.exchange(
              HttpMethod.POST,
              "/api/v1/knowledge/documents",
              body,
              token,
              MediaType.MULTIPART_FORM_DATA);
      audit.record(user, "KNOWLEDGE_DOCUMENT_UPLOADED", null, "completed", note);
      return response;
    } catch (BusinessException failure) {
      audit.record(
          user, "KNOWLEDGE_DOCUMENT_UPLOADED", null, "failed", "error_code:" + failure.getReason());
      throw failure;
    }
  }

  private ResponseEntity<JsonNode> relay(
      HttpServletRequest request, WorkspacePrincipal user, Object body) {
    String path = request.getRequestURI();
    String knowledgeAction = null;
    if (!"GET".equals(request.getMethod()) && path.startsWith("/api/v1/knowledge/")) {
      requireAdmin(user);
      knowledgeAction = knowledgeAuditAction(request.getMethod());
    }
    if (request.getContentLengthLong() > 1024 * 1024)
      throw new BusinessException(413, "request_too_large", "请求内容超过 1 MB。");
    String token = request.getHeader("Authorization");
    if (knowledgeAction == null) return forward(request, user, body, path, token);
    // Identity checks stay inside the audited span: a mutation blocked by an outage or
    // mismatch is still a knowledge-change attempt worth tracing.
    try {
      ResponseEntity<JsonNode> response = forward(request, user, body, path, token);
      audit.record(
          user,
          knowledgeAction,
          null,
          "completed",
          knowledgeNote(request.getMethod(), request.getRequestURI()));
      return response;
    } catch (BusinessException failure) {
      audit.record(user, knowledgeAction, null, "failed", "error_code:" + failure.getReason());
      throw failure;
    }
  }

  private ResponseEntity<JsonNode> forward(
      HttpServletRequest request, WorkspacePrincipal user, Object body, String path, String token) {
    agent.verifyIdentity(token, user);
    if (request.getQueryString() != null) path += "?" + request.getQueryString();
    return agent.exchange(HttpMethod.valueOf(request.getMethod()), path, body, token, null);
  }

  private String knowledgeAuditAction(String method) {
    return "POST".equals(method) ? "KNOWLEDGE_REINDEXED" : "KNOWLEDGE_DOCUMENT_DELETED";
  }

  private String knowledgeNote(String method, String path) {
    return "DELETE".equals(method) ? "document:" + path.substring(path.lastIndexOf('/') + 1) : null;
  }

  private void requireAdmin(WorkspacePrincipal user) {
    if (!"admin".equals(user.role()))
      throw new BusinessException(403, "forbidden", "知识资料变更仅对管理员开放。");
  }
}
