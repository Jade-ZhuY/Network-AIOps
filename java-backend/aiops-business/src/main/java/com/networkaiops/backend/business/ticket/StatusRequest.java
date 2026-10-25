package com.networkaiops.backend.business.ticket;

import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;

public record StatusRequest(
    @NotNull @Min(0) Long version,
    @NotNull Status status,
    @NotBlank @Size(min = 5, max = 1200, message = "请填写至少 5 字符的处理说明。") String note) {}
