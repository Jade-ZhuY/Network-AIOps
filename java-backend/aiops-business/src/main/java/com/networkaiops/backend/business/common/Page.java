package com.networkaiops.backend.business.common;

import java.util.List;

public record Page<T>(List<T> items, long total, int offset, int limit) {}
