package com.networkaiops.backend.controller;

import com.networkaiops.backend.business.monitor.CreateMonitorRequest;
import com.networkaiops.backend.business.monitor.MonitorService;
import com.networkaiops.backend.business.monitor.MonitorStatus;
import com.networkaiops.backend.business.monitor.UpdateMonitorRequest;
import com.networkaiops.backend.common.identity.WorkspacePrincipal;
import com.networkaiops.backend.common.web.Result;
import jakarta.validation.Valid;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.Size;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/v1/monitors")
@Validated
public class MonitorController {
  private final MonitorService service;

  public MonitorController(MonitorService service) {
    this.service = service;
  }

  @GetMapping
  Result list(
      @AuthenticationPrincipal WorkspacePrincipal user,
      @RequestParam(defaultValue = "") @Size(max = 100) String q,
      @RequestParam(required = false) String type,
      @RequestParam(required = false) MonitorStatus status,
      @RequestParam(defaultValue = "0") @Min(0) int offset,
      @RequestParam(defaultValue = "20") @Min(1) @Max(100) int limit) {
    return Result.success(service.list(user, q, type, status, offset, limit));
  }

  @PostMapping
  ResponseEntity<Result> create(
      @Valid @RequestBody CreateMonitorRequest request,
      @AuthenticationPrincipal WorkspacePrincipal user) {
    return ResponseEntity.status(201).body(Result.success(service.create(request, user)));
  }

  @GetMapping("/{id}")
  Result get(@PathVariable String id, @AuthenticationPrincipal WorkspacePrincipal user) {
    return Result.success(service.get(id, user));
  }

  @PutMapping("/{id}")
  Result update(
      @PathVariable String id,
      @Valid @RequestBody UpdateMonitorRequest request,
      @AuthenticationPrincipal WorkspacePrincipal user) {
    return Result.success(service.update(id, request, user));
  }

  @DeleteMapping("/{id}")
  ResponseEntity<Void> delete(
      @PathVariable String id,
      @RequestParam @Min(0) long version,
      @AuthenticationPrincipal WorkspacePrincipal user) {
    service.delete(id, version, user);
    return ResponseEntity.noContent().build();
  }
}
