package com.networkaiops.backend.business.ticket;

import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * Bounded analysis execution capacity, after HertzBeat's collector worker pool: fixed concurrency
 * plus a bounded queue instead of one blocked HTTP thread per analysis. Missing values fall back to
 * the same defaults as application.yml.
 */
@ConfigurationProperties("workspace.analysis")
public record AnalysisProperties(Integer maxConcurrent, Integer queueCapacity) {
  public int concurrency() {
    return maxConcurrent == null ? 2 : Math.min(16, Math.max(1, maxConcurrent));
  }

  public int queue() {
    return queueCapacity == null ? 50 : Math.min(500, Math.max(0, queueCapacity));
  }
}
