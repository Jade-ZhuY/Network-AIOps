package com.networkaiops.backend.business.ticket;

import com.networkaiops.backend.business.common.Page;
import com.networkaiops.backend.common.identity.WorkspacePrincipal;
import java.util.List;
import java.util.Map;

/** Ticket business contract: CRUD, status transitions, ownership scoping and event queries. */
public interface TicketService {
  Ticket owned(String id, WorkspacePrincipal user, boolean lock);

  void checkEditable(Ticket ticket, long version);

  Page list(WorkspacePrincipal user, String query, Status status, int offset, int limit);

  View get(String id, WorkspacePrincipal user);

  View create(CreateRequest request, WorkspacePrincipal user);

  View update(String id, UpdateRequest request, WorkspacePrincipal user);

  View status(String id, StatusRequest request, WorkspacePrincipal user);

  void delete(String id, long version, WorkspacePrincipal user);

  List<Map<String, Object>> events(String id, WorkspacePrincipal user);
}
