package com.networkaiops.backend.common.spring.config;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.networkaiops.backend.common.spring.security.BearerTokenFilter;
import com.networkaiops.backend.common.web.Result;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.HttpMethod;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.security.web.authentication.UsernamePasswordAuthenticationFilter;

@Configuration
public class SecurityConfig {
  @Bean
  SecurityFilterChain apiSecurity(HttpSecurity http, AuthProperties properties, ObjectMapper mapper)
      throws Exception {
    return http.csrf(
            csrf ->
                csrf.disable()) // Only explicit Bearer headers; no ambient cookie authentication.
        .httpBasic(basic -> basic.disable())
        .formLogin(form -> form.disable())
        .requestCache(cache -> cache.disable())
        .sessionManagement(
            session -> session.sessionCreationPolicy(SessionCreationPolicy.STATELESS))
        .authorizeHttpRequests(
            auth ->
                auth.requestMatchers(
                        HttpMethod.GET,
                        "/",
                        "/static/**",
                        "/docs",
                        "/api-docs.html",
                        "/api/v1/health",
                        "/health")
                    .permitAll()
                    .requestMatchers("/api/v1/admin/**")
                    .hasRole("ADMIN")
                    .requestMatchers("/api/**")
                    .authenticated()
                    .anyRequest()
                    .denyAll())
        .headers(
            headers ->
                headers.contentSecurityPolicy(
                    csp ->
                        csp.policyDirectives(
                            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'")))
        .exceptionHandling(
            errors ->
                errors
                    .authenticationEntryPoint(
                        (request, response, error) -> {
                          response.setStatus(401);
                          response.setHeader("WWW-Authenticate", "Bearer");
                          response.setContentType("application/json;charset=UTF-8");
                          mapper.writeValue(response.getOutputStream(), Result.error("请先登录工作台。"));
                        })
                    .accessDeniedHandler(
                        (request, response, error) -> {
                          response.setStatus(403);
                          response.setContentType("application/json;charset=UTF-8");
                          mapper.writeValue(
                              response.getOutputStream(), Result.error("当前身份没有此操作权限。"));
                        }))
        .addFilterBefore(
            new BearerTokenFilter(properties, mapper), UsernamePasswordAuthenticationFilter.class)
        .build();
  }
}
