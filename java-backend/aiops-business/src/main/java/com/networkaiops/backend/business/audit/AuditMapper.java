package com.networkaiops.backend.business.audit;

import java.time.LocalDateTime;
import java.util.List;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

@Mapper
public interface AuditMapper {
  record AuditRow(
      String id,
      String action,
      String ticketId,
      String resourceId,
      String traceId,
      String outcome,
      String note,
      LocalDateTime createdAt) {}

  @Insert(
      """
      INSERT INTO audit_events(id,owner_id,tenant_id,action,ticket_id,resource_id,trace_id,
      outcome,note,created_at)
      VALUES(#{id},#{owner},#{tenant},#{action},#{ticketId},#{resourceId},#{traceId},#{outcome},
      #{note},#{at})
      """)
  int insert(
      @Param("id") String id,
      @Param("owner") String owner,
      @Param("tenant") String tenant,
      @Param("action") String action,
      @Param("ticketId") String ticketId,
      @Param("resourceId") String resourceId,
      @Param("traceId") String traceId,
      @Param("outcome") String outcome,
      @Param("note") String note,
      @Param("at") LocalDateTime at);

  @Select(
      """
      <script>
      SELECT * FROM audit_events
      WHERE owner_id=#{owner} AND tenant_id=#{tenant}
      <if test="ticketId != null">AND ticket_id=#{ticketId}</if>
      ORDER BY created_at DESC, id DESC LIMIT #{limit}
      </script>
      """)
  List<AuditRow> list(
      @Param("owner") String owner,
      @Param("tenant") String tenant,
      @Param("ticketId") String ticketId,
      @Param("limit") int limit);
}
