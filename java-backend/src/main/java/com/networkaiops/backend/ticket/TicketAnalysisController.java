package com.networkaiops.backend.ticket;

import com.networkaiops.backend.security.WorkspacePrincipal;
import jakarta.validation.Valid;
import jakarta.validation.constraints.Min;
import java.util.List;
import java.util.Map;
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
  Map<String, List<TicketModels.Analysis>> list(
      @PathVariable String id, @AuthenticationPrincipal WorkspacePrincipal user) {
    return Map.of("analyses", service.list(id, user));
  }

  @PostMapping
  TicketModels.Analysis analyze(
      @PathVariable String id,
      @Valid @RequestBody AnalyzeRequest request,
      @AuthenticationPrincipal WorkspacePrincipal user,
      @RequestHeader("Authorization") String authorization) {
    return service.analyze(id, request.version(), user, authorization);
  }
}
