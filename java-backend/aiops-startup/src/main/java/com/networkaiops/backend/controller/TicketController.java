package com.networkaiops.backend.controller;

import com.networkaiops.backend.business.ticket.CreateRequest;
import com.networkaiops.backend.business.ticket.Status;
import com.networkaiops.backend.business.ticket.StatusRequest;
import com.networkaiops.backend.business.ticket.TicketService;
import com.networkaiops.backend.business.ticket.UpdateRequest;
import com.networkaiops.backend.common.identity.WorkspacePrincipal;
import com.networkaiops.backend.common.web.Result;
import jakarta.validation.Valid;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.Size;
import java.util.Map;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/v1/tickets")
@Validated
public class TicketController {
  private final TicketService service;

  public TicketController(TicketService service) {
    this.service = service;
  }

  @GetMapping
  Result list(
      @AuthenticationPrincipal WorkspacePrincipal user,
      @RequestParam(defaultValue = "") @Size(max = 100) String q,
      @RequestParam(required = false) Status status,
      @RequestParam(defaultValue = "0") @Min(0) int offset,
      @RequestParam(defaultValue = "20") @Min(1) @Max(100) int limit) {
    return Result.success(service.list(user, q, status, offset, limit));
  }

  @PostMapping
  ResponseEntity<Result> create(
      @Valid @RequestBody CreateRequest request, @AuthenticationPrincipal WorkspacePrincipal user) {
    return ResponseEntity.status(201).body(Result.success(service.create(request, user)));
  }

  @GetMapping("/{id}")
  Result get(@PathVariable String id, @AuthenticationPrincipal WorkspacePrincipal user) {
    return Result.success(service.get(id, user));
  }

  @PutMapping("/{id}")
  Result update(
      @PathVariable String id,
      @Valid @RequestBody UpdateRequest request,
      @AuthenticationPrincipal WorkspacePrincipal user) {
    return Result.success(service.update(id, request, user));
  }

  @PatchMapping("/{id}/status")
  Result status(
      @PathVariable String id,
      @Valid @RequestBody StatusRequest request,
      @AuthenticationPrincipal WorkspacePrincipal user) {
    return Result.success(service.status(id, request, user));
  }

  @DeleteMapping("/{id}")
  ResponseEntity<Void> delete(
      @PathVariable String id,
      @RequestParam @Min(0) long version,
      @AuthenticationPrincipal WorkspacePrincipal user) {
    service.delete(id, version, user);
    return ResponseEntity.noContent().build();
  }

  @GetMapping("/{id}/events")
  Result events(@PathVariable String id, @AuthenticationPrincipal WorkspacePrincipal user) {
    return Result.success(Map.of("events", service.events(id, user)));
  }
}
