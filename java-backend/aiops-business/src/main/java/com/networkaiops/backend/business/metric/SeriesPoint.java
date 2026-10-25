package com.networkaiops.backend.business.metric;

import java.time.Instant;

/** One sampled value of a metric series, keyed by interface when the sample has one. */
public record SeriesPoint(Instant sampleTime, String interfaceName, Double value) {}
