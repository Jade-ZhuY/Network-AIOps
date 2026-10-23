package com.networkaiops.backend.agent;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.networkaiops.backend.common.BusinessException;
import com.networkaiops.backend.config.AgentProperties;
import com.networkaiops.backend.security.WorkspacePrincipal;
import java.net.http.HttpClient;
import java.util.Map;
import org.springframework.http.HttpMethod;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.http.client.JdkClientHttpRequestFactory;
import org.springframework.stereotype.Component;
import org.springframework.web.client.ResourceAccessException;
import org.springframework.web.client.RestClient;

/** Fixed-origin HTTP client. No automatic POST retries, redirects or shared admin credentials. */
@Component
public class AgentClient {
  private final AgentProperties properties;
  private final ObjectMapper mapper;
  private final RestClient client;

  public AgentClient(AgentProperties properties, ObjectMapper mapper) {
    this.properties = properties;
    this.mapper = mapper;
    var factory =
        new JdkClientHttpRequestFactory(
            HttpClient.newBuilder()
                .connectTimeout(properties.connectTimeout())
                .followRedirects(HttpClient.Redirect.NEVER)
                .build());
    factory.setReadTimeout(properties.readTimeout());
    client =
        RestClient.builder()
            .baseUrl(properties.baseUrl().toString().replaceAll("/$", ""))
            .requestFactory(factory)
            .build();
  }

  public boolean enabled() {
    return properties.enabled();
  }

  public void requireEnabled() {
    if (!enabled())
      throw new BusinessException(
          503, "agent_disabled", "Agent 服务尚未启用；Java 业务功能可正常使用，待 Python 服务就绪后再配置连接。");
  }

  public ResponseEntity<JsonNode> exchange(
      HttpMethod method, String path, Object body, String authorization, MediaType contentType) {
    requireEnabled();
    try {
      if (!path.startsWith("/api/v1/") || path.contains("\\"))
        throw new BusinessException(400, "invalid_agent_path", "Agent 接口路径无效。");
      var request =
          client
              .method(method)
              .uri(java.net.URI.create(properties.baseUrl().toString().replaceAll("/$", "") + path))
              .header("Authorization", authorization)
              .accept(MediaType.APPLICATION_JSON);
      if (body != null)
        request
            .contentType(contentType == null ? MediaType.APPLICATION_JSON : contentType)
            .body(body);
      return request.exchange(
          (outgoing, response) -> {
            int status = response.getStatusCode().value();
            if (status < 200 || status >= 300) {
              int mapped = status == 401 || status >= 500 || status < 400 ? 502 : status;
              String message =
                  switch (status) {
                    case 401 -> "Agent 访问令牌与 Java 配置不一致，请核对服务身份。";
                    case 403 -> "当前身份未获 Agent 数据访问权限。";
                    case 404 -> "Agent 记录不存在或接口未启用。";
                    case 409 -> "Agent 会话正在执行或记录版本已变化，请稍后核对。";
                    case 422 -> "Agent 请求未通过参数或业务范围校验。";
                    case 429 -> "Agent 并发已满，请稍后重试。";
                    default -> "Agent 返回异常，请检查 Python 服务状态。";
                  };
              throw new BusinessException(mapped, "agent_http_" + status, message);
            }
            if (status == 204) return ResponseEntity.noContent().build();
            byte[] bytes = response.getBody().readNBytes(properties.maxResponseBytes() + 1);
            if (bytes.length > properties.maxResponseBytes())
              throw new BusinessException(502, "agent_response_too_large", "Agent 响应超过配置上限。");
            try {
              JsonNode json = mapper.readTree(bytes);
              if (json == null || !json.isContainerNode()) throw new IllegalArgumentException();
              return ResponseEntity.status(status)
                  .contentType(MediaType.APPLICATION_JSON)
                  .body(json);
            } catch (BusinessException exception) {
              throw exception;
            } catch (Exception invalid) {
              throw new BusinessException(502, "agent_invalid_response", "Agent 未返回有效的 JSON 数据。");
            }
          });
    } catch (ResourceAccessException unavailable) {
      throw new BusinessException(
          503, "agent_unavailable", "暂未连接到 Agent 服务。咨询单已保留，请在 Python 服务就绪后再分析。");
    }
  }

  public void verifyIdentity(String authorization, WorkspacePrincipal user) {
    JsonNode me = exchange(HttpMethod.GET, "/api/v1/me", null, authorization, null).getBody();
    if (me == null
        || !user.userId().equals(me.path("user_id").asText())
        || !user.tenantId().equals(me.path("tenant_id").asText())
        || !user.role().equals(me.path("role").asText())
        || !mapper.valueToTree(user.scope()).equals(me.path("scope"))) {
      throw new BusinessException(
          502, "agent_identity_mismatch", "Java 与 Agent 的身份或授权范围不一致，已停止调用。");
    }
  }

  public String createSession(String title, String authorization) {
    JsonNode response =
        exchange(
                HttpMethod.POST,
                "/api/v1/sessions",
                Map.of("title", title, "timezone", "Asia/Shanghai"),
                authorization,
                null)
            .getBody();
    String id = response == null ? "" : response.path("session_id").asText();
    if (id.isBlank() || id.length() > 64)
      throw new BusinessException(502, "agent_invalid_session", "Agent 返回的会话标识不正确。");
    return id;
  }

  public JsonNode analyze(String sessionId, String question, String authorization) {
    JsonNode response =
        exchange(
                HttpMethod.POST,
                "/api/v1/chat",
                Map.of("session_id", sessionId, "message", question, "timezone", "Asia/Shanghai"),
                authorization,
                null)
            .getBody();
    if (response == null
        || !response.path("report").isObject()
        || !response.path("report").path("summary").isTextual()
        || response.path("request_id").asText().isBlank()
        || response.path("request_id").asText().length() > 64
        || !sessionId.equals(response.path("session_id").asText())) {
      throw new BusinessException(502, "agent_invalid_report", "Agent 响应缺少有效报告或会话标识。");
    }
    return response;
  }
}
