package com.networkaiops.backend.controller;

import com.networkaiops.backend.business.metric.MetricCatalogService;
import com.networkaiops.backend.business.metric.MetricQueryService;
import com.networkaiops.backend.common.identity.WorkspacePrincipal;
import com.networkaiops.backend.common.web.Result;
import java.time.Instant;
import java.util.Map;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class MetricsController {
  private final MetricCatalogService catalog;
  private final MetricQueryService queries;

  public MetricsController(MetricCatalogService catalog, MetricQueryService queries) {
    this.catalog = catalog;
    this.queries = queries;
  }

  @GetMapping("/api/v1/metric-definitions")
  Result definitions() {
    return Result.success(Map.of("definitions", catalog.definitions()));
  }

  @GetMapping("/api/v1/monitors/{id}/metrics/{metricId}/series")
  Result series(
      @PathVariable String id,
      @PathVariable String metricId,
      @RequestParam Instant start,
      @RequestParam Instant end,
      @RequestParam(name = "interface", required = false) String interfaceName,
      @AuthenticationPrincipal WorkspacePrincipal user) {
    return Result.success(queries.series(id, metricId, start, end, interfaceName, user));
  }
}
