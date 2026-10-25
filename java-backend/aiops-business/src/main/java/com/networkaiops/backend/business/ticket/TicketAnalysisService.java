package com.networkaiops.backend.business.ticket;

import com.networkaiops.backend.common.identity.WorkspacePrincipal;
import java.util.List;

/** Async agent analysis contract for a ticket, including startup recovery of interrupted runs. */
public interface TicketAnalysisService {
  void recover();

  List<Analysis> list(String id, WorkspacePrincipal user);

  Analysis start(String id, long version, WorkspacePrincipal user, String authorization);
}
