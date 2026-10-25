package com.networkaiops.backend.business.ticket;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;

public record CreateRequest(
    @NotBlank @Size(min = 2, max = 100, message = "标题长度应为 2–100 字符。") String title,
    @NotNull @Size(max = 64) String device,
    @NotBlank @Size(min = 10, max = 4000, message = "问题描述长度应为 10–4000 字符。") String description,
    @NotNull Priority priority) {}
