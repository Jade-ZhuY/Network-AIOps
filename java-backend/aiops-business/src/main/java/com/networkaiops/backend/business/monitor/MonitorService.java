package com.networkaiops.backend.business.monitor;

import com.networkaiops.backend.business.common.Page;
import com.networkaiops.backend.common.identity.WorkspacePrincipal;

/** Monitor instance business contract: template-checked CRUD with workspace scoping. */
public interface MonitorService {
  Monitor owned(String id, WorkspacePrincipal user);

  Page<MonitorView> list(
      WorkspacePrincipal user,
      String query,
      String type,
      MonitorStatus status,
      int offset,
      int limit);

  MonitorView get(String id, WorkspacePrincipal user);

  MonitorView create(CreateMonitorRequest request, WorkspacePrincipal user);

  MonitorView update(String id, UpdateMonitorRequest request, WorkspacePrincipal user);

  void delete(String id, long version, WorkspacePrincipal user);
}
