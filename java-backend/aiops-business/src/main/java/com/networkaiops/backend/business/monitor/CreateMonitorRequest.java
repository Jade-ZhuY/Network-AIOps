package com.networkaiops.backend.business.monitor;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;
import java.util.List;

public record CreateMonitorRequest(
    @NotBlank @Size(min = 2, max = 100, message = "监控名称长度应为 2–100 字符。") String name,
    @NotBlank @Size(max = 32, message = "监控类型不存在或未注册。") String type,
    @NotBlank @Size(max = 64, message = "设备主机名长度不能超过 64 字符。") String hostname,
    List<@Size(max = 32, message = "单个标签长度不能超过 32 字符。") String> labels,
    @Size(max = 500, message = "描述长度不能超过 500 字符。") String description) {}
