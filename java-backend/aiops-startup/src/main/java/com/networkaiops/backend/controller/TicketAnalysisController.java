package com.networkaiops.backend.controller;

import com.networkaiops.backend.business.ticket.TicketAnalysisService;
import com.networkaiops.backend.common.identity.WorkspacePrincipal;
import com.networkaiops.backend.common.web.Result;
import jakarta.validation.Valid;
import jakarta.validation.constraints.Min;
import java.util.Map;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/v1/tickets/{id}/analyses")
public class TicketAnalysisController {
  public record AnalyzeRequest(@jakarta.validation.constraints.NotNull @Min(0) Long version) {}

  private final TicketAnalysisService service;

  public TicketAnalysisController(TicketAnalysisService service) {
    this.service = service;
  }

  @GetMapping
  Result list(@PathVariable String id, @AuthenticationPrincipal WorkspacePrincipal user) {
    return Result.success(Map.of("analyses", service.list(id, user)));
  }

  @PostMapping
  ResponseEntity<Result> analyze(
      @PathVariable String id,
      @Valid @RequestBody AnalyzeRequest request,
      @AuthenticationPrincipal WorkspacePrincipal user,
      @RequestHeader("Authorization") String authorization) {
    // Accepted: the RUNNING record is persisted and execution continues on the analysis pool.
    return ResponseEntity.accepted()
        .body(Result.success(service.start(id, request.version(), user, authorization)));
  }
}
