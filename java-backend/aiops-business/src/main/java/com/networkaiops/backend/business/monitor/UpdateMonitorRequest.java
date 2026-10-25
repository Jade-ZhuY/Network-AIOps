package com.networkaiops.backend.business.monitor;

import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;
import java.util.List;

public record UpdateMonitorRequest(
    @NotNull @Min(0) Long version,
    @NotBlank @Size(min = 2, max = 100) String name,
    @NotBlank @Size(max = 32) String type,
    @NotBlank @Size(max = 64) String hostname,
    List<@Size(max = 32) String> labels,
    @Size(max = 500) String description) {}
