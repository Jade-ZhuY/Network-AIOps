package com.networkaiops.backend.business.ticket;

import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;

public record UpdateRequest(
    @NotNull @Min(0) Long version,
    @NotBlank @Size(min = 2, max = 100) String title,
    @NotNull @Size(max = 64) String device,
    @NotBlank @Size(min = 10, max = 4000) String description,
    @NotNull Priority priority) {}
