package com.networkaiops.backend.ticket;

import static com.networkaiops.backend.ticket.TicketModels.*;

import com.networkaiops.backend.audit.AuditRepository;
import com.networkaiops.backend.common.BusinessException;
import com.networkaiops.backend.security.WorkspacePrincipal;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class TicketService {
  private final TicketRepository repository;
  private final AuditRepository audit;

  public TicketService(TicketRepository repository, AuditRepository audit) {
    this.repository = repository;
    this.audit = audit;
  }

  public Ticket owned(String id, WorkspacePrincipal user, boolean lock) {
    return repository
        .find(id, user, lock)
        .orElseThrow(() -> new BusinessException(404, "ticket_not_found", "咨询单不存在或不在当前身份范围。"));
  }

  @Transactional(readOnly = true)
  public Page list(WorkspacePrincipal user, String query, Status status, int offset, int limit) {
    return new Page(
        repository.list(user, query, status, offset, limit).stream().map(View::from).toList(),
        repository.count(user, query, status),
        offset,
        limit);
  }

  @Transactional(readOnly = true)
  public View get(String id, WorkspacePrincipal user) {
    return View.from(owned(id, user, false));
  }

  @Transactional
  public View create(CreateRequest request, WorkspacePrincipal user) {
    validateText(request.title(), 2);
    validateText(request.description(), 10);
    Instant now = Instant.now();
    Ticket ticket =
        new Ticket(
            UUID.randomUUID().toString(),
            user.userId(),
            user.tenantId(),
            request.title().trim(),
            request.device().trim(),
            request.description().trim(),
            request.priority(),
            Status.OPEN,
            "NOT_STARTED",
            null,
            0,
            false,
            now,
            now);
    repository.insert(ticket);
    audit.record(user, "TICKET_CREATED", ticket.id(), "completed");
    return View.from(ticket);
  }

  @Transactional
  public View update(String id, UpdateRequest request, WorkspacePrincipal user) {
    Ticket ticket = owned(id, user, true);
    checkEditable(ticket, request.version());
    if (ticket.status() == Status.CLOSED)
      throw new BusinessException(409, "ticket_closed", "请先重新打开已关闭的咨询单。");
    validateText(request.title(), 2);
    validateText(request.description(), 10);
    if (repository.update(id, user, request) != 1) conflict();
    audit.record(user, "TICKET_UPDATED", id, "completed");
    return get(id, user);
  }

  @Transactional
  public View status(String id, StatusRequest request, WorkspacePrincipal user) {
    Ticket ticket = owned(id, user, true);
    checkEditable(ticket, request.version());
    validateText(request.note(), 5);
    if (!ticket.status().allowed().contains(request.status()))
      throw new BusinessException(409, "invalid_transition", "当前状态不支持此流转，请刷新咨询单。");
    repository.changeStatus(id, request.status());
    // User-authored handling notes are business records, never application log messages.
    audit.record(
        user,
        "STATUS_" + ticket.status() + "_TO_" + request.status(),
        id,
        "completed",
        request.note().trim());
    return get(id, user);
  }

  @Transactional
  public void delete(String id, long version, WorkspacePrincipal user) {
    Ticket ticket = owned(id, user, true);
    checkEditable(ticket, version);
    repository.softDelete(id);
    audit.record(user, "TICKET_DELETED", id, "completed");
  }

  public List<Map<String, Object>> events(String id, WorkspacePrincipal user) {
    owned(id, user, false);
    return audit.list(user, id, 100);
  }

  private static void validateText(String text, int minimum) {
    if (text.trim().length() < minimum || text.indexOf('\0') >= 0)
      throw new BusinessException(422, "invalid_text", "文本去除首尾空白后的长度不足，或包含无效字符。");
  }

  public static void checkEditable(Ticket ticket, long version) {
    if (ticket.version() != version) conflict();
    if ("RUNNING".equals(ticket.analysisStatus()))
      throw new BusinessException(409, "analysis_running", "该咨询单正在分析，请等待完成后再修改。");
  }

  private static void conflict() {
    throw new BusinessException(409, "version_conflict", "记录已被修改，请刷新后重试。");
  }
}
