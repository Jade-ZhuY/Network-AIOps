package com.networkaiops.backend.security;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.networkaiops.backend.common.ErrorResponse;
import com.networkaiops.backend.config.AuthProperties;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.List;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.web.filter.OncePerRequestFilter;

public class BearerTokenFilter extends OncePerRequestFilter {
  private final byte[] engineerHash;
  private final byte[] adminHash;
  private final ObjectMapper mapper;

  public BearerTokenFilter(AuthProperties properties, ObjectMapper mapper) {
    engineerHash = hash(properties.engineerToken());
    adminHash = hash(properties.adminToken());
    this.mapper = mapper;
  }

  private static byte[] hash(String value) {
    try {
      return MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8));
    } catch (NoSuchAlgorithmException impossible) {
      throw new IllegalStateException(impossible);
    }
  }

  @Override
  protected void doFilterInternal(
      HttpServletRequest request, HttpServletResponse response, FilterChain chain)
      throws ServletException, IOException {
    String header = request.getHeader("Authorization");
    if (header != null) {
      if (!header.regionMatches(true, 0, "Bearer ", 0, 7)
          || header.length() > 4096
          || java.util.Collections.list(request.getHeaders("Authorization")).size() != 1) {
        denied(response);
        return;
      }
      byte[] candidate = hash(header.substring(7));
      boolean admin = MessageDigest.isEqual(candidate, adminHash);
      boolean engineer = MessageDigest.isEqual(candidate, engineerHash);
      if (!admin && !engineer) {
        denied(response);
        return;
      }
      String role = admin ? "admin" : "engineer";
      var principal = WorkspacePrincipal.forRole(role);
      var authentication =
          new UsernamePasswordAuthenticationToken(
              principal,
              null,
              List.of(
                  new SimpleGrantedAuthority("ROLE_" + role.toUpperCase(java.util.Locale.ROOT))));
      SecurityContextHolder.getContext().setAuthentication(authentication);
    }
    chain.doFilter(request, response);
  }

  private void denied(HttpServletResponse response) throws IOException {
    response.setStatus(401);
    response.setHeader("WWW-Authenticate", "Bearer");
    response.setContentType("application/json;charset=UTF-8");
    mapper.writeValue(
        response.getOutputStream(), ErrorResponse.of("访问令牌无效，请重新登录。", "authentication_required"));
  }
}
