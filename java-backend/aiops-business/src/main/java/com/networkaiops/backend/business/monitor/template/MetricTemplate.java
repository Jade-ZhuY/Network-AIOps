package com.networkaiops.backend.business.monitor.template;

/**
 * Metric watched by a device category. Ids align with the Python metric catalog ({@code
 * data/metric_catalog.json}); the SQL caliber stays owned by that catalog while the template only
 * carries presentation metadata and default thresholds.
 */
public record MetricTemplate(
    String id, String unit, Double warning, Double critical, boolean queryable) {}
