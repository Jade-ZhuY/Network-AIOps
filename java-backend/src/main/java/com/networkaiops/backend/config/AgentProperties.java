package com.networkaiops.backend.config;

import jakarta.validation.constraints.AssertTrue;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import java.net.URI;
import java.time.Duration;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.validation.annotation.Validated;

@Validated
@ConfigurationProperties("workspace.agent")
public record AgentProperties(
    boolean enabled,
    URI baseUrl,
    Duration connectTimeout,
    Duration readTimeout,
    @Min(1024) @Max(16777216) int maxResponseBytes) {
  @AssertTrue(message = "Agent 地址必须是无凭据、无查询参数的 HTTP(S) 服务根地址，且超时必须为正。")
  public boolean isValid() {
    return baseUrl != null
        && ("http".equals(baseUrl.getScheme()) || "https".equals(baseUrl.getScheme()))
        && baseUrl.getHost() != null
        && baseUrl.getUserInfo() == null
        && baseUrl.getQuery() == null
        && baseUrl.getFragment() == null
        && (baseUrl.getPath().isEmpty() || baseUrl.getPath().equals("/"))
        && connectTimeout != null
        && !connectTimeout.isNegative()
        && !connectTimeout.isZero()
        && readTimeout != null
        && !readTimeout.isNegative()
        && !readTimeout.isZero();
  }
}
