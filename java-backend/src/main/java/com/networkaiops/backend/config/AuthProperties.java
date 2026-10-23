package com.networkaiops.backend.config;

import jakarta.validation.constraints.AssertTrue;
import jakarta.validation.constraints.Size;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.validation.annotation.Validated;

@Validated
@ConfigurationProperties("workspace.auth")
public record AuthProperties(
    @Size(min = 24, message = "请配置至少 24 字符的工程师访问令牌。") String engineerToken,
    @Size(min = 24, message = "请配置至少 24 字符的管理员访问令牌。") String adminToken) {
  @AssertTrue(message = "工程师与管理员令牌必须不同。")
  public boolean isDistinct() {
    return engineerToken != null && !engineerToken.equals(adminToken);
  }

  @Override
  public String toString() {
    return "AuthProperties[REDACTED]";
  }
}
