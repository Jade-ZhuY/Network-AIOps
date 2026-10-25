package com.networkaiops.backend.business.metric;

import java.util.List;

/** Catalog entry aggregated from every monitor template referencing the metric. */
public record MetricDefinitionView(
    String id,
    String unit,
    Double warning,
    Double critical,
    boolean queryable,
    List<String> deviceTypes) {}
