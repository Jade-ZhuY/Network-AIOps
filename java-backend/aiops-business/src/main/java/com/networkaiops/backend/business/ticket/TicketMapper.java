package com.networkaiops.backend.business.ticket;

import java.time.LocalDateTime;
import java.util.List;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

/**
 * Hand-written SQL for the ticket tables, shared by the MySQL production schema and the H2 test
 * schema. Timestamps are always supplied by the application as UTC wall clock so DATETIME columns
 * never depend on a database session time zone.
 */
@Mapper
public interface TicketMapper {
  record TicketRow(
      String id,
      String ownerId,
      String tenantId,
      String title,
      String device,
      String description,
      String priority,
      String status,
      String analysisStatus,
      String agentSessionId,
      long version,
      boolean deleted,
      LocalDateTime createdAt,
      LocalDateTime updatedAt) {}

  record AnalysisRow(
      String id,
      String status,
      String requestId,
      String responseJson,
      String errorCode,
      LocalDateTime startedAt,
      LocalDateTime completedAt) {}

  @Select(
      """
      <script>
      SELECT * FROM tickets
      WHERE id=#{id} AND owner_id=#{owner} AND tenant_id=#{tenant} AND deleted=FALSE
      <if test="lock">FOR UPDATE</if>
      </script>
      """)
  TicketRow find(
      @Param("id") String id,
      @Param("owner") String owner,
      @Param("tenant") String tenant,
      @Param("lock") boolean lock);

  @Select(
      """
      <script>
      SELECT * FROM tickets
      WHERE owner_id=#{owner} AND tenant_id=#{tenant} AND deleted=FALSE
      AND (LOWER(title) LIKE #{query} ESCAPE '!' OR LOWER(device) LIKE #{query} ESCAPE '!')
      <if test="status != null">AND status=#{status}</if>
      ORDER BY updated_at DESC, id DESC LIMIT #{limit} OFFSET #{offset}
      </script>
      """)
  List<TicketRow> list(
      @Param("owner") String owner,
      @Param("tenant") String tenant,
      @Param("query") String query,
      @Param("status") String status,
      @Param("limit") int limit,
      @Param("offset") int offset);

  @Select(
      """
      <script>
      SELECT COUNT(*) FROM tickets
      WHERE owner_id=#{owner} AND tenant_id=#{tenant} AND deleted=FALSE
      AND (LOWER(title) LIKE #{query} ESCAPE '!' OR LOWER(device) LIKE #{query} ESCAPE '!')
      <if test="status != null">AND status=#{status}</if>
      </script>
      """)
  long count(
      @Param("owner") String owner,
      @Param("tenant") String tenant,
      @Param("query") String query,
      @Param("status") String status);

  @Insert(
      """
      INSERT INTO tickets(id,owner_id,tenant_id,title,device,description,priority,status,
      analysis_status,version,deleted,created_at,updated_at)
      VALUES(#{id},#{owner},#{tenant},#{title},#{device},#{description},#{priority},'OPEN',
      'NOT_STARTED',0,FALSE,#{at},#{at})
      """)
  int insert(
      @Param("id") String id,
      @Param("owner") String owner,
      @Param("tenant") String tenant,
      @Param("title") String title,
      @Param("device") String device,
      @Param("description") String description,
      @Param("priority") String priority,
      @Param("at") LocalDateTime at);

  @Update(
      """
      UPDATE tickets
      SET title=#{title},device=#{device},description=#{description},priority=#{priority},
      version=version+1,updated_at=#{at}
      WHERE id=#{id} AND owner_id=#{owner} AND tenant_id=#{tenant}
      AND version=#{version} AND deleted=FALSE
      """)
  int update(
      @Param("id") String id,
      @Param("owner") String owner,
      @Param("tenant") String tenant,
      @Param("version") long version,
      @Param("title") String title,
      @Param("device") String device,
      @Param("description") String description,
      @Param("priority") String priority,
      @Param("at") LocalDateTime at);

  @Update(
      """
      UPDATE tickets SET status=#{status},version=version+1,updated_at=#{at}
      WHERE id=#{id}
      """)
  int changeStatus(
      @Param("id") String id, @Param("status") String status, @Param("at") LocalDateTime at);

  @Update("UPDATE tickets SET deleted=TRUE,version=version+1,updated_at=#{at} WHERE id=#{id}")
  int softDelete(@Param("id") String id, @Param("at") LocalDateTime at);

  @Insert(
      """
      INSERT INTO ticket_analyses(id,ticket_id,status,started_at)
      VALUES(#{analysis},#{id},'RUNNING',#{at})
      """)
  int insertAnalysis(
      @Param("analysis") String analysis, @Param("id") String id, @Param("at") LocalDateTime at);

  @Update(
      """
      UPDATE tickets SET analysis_status='RUNNING',version=version+1,updated_at=#{at}
      WHERE id=#{id}
      """)
  int markTicketAnalysisRunning(@Param("id") String id, @Param("at") LocalDateTime at);

  @Update("UPDATE tickets SET agent_session_id=#{session} WHERE id=#{id}")
  int saveAgentSession(@Param("id") String id, @Param("session") String session);

  @Update(
      """
      UPDATE ticket_analyses
      SET status=#{status},request_id=#{request},response_json=#{json},error_code=#{error},
      completed_at=#{at}
      WHERE id=#{analysis} AND status='RUNNING'
      """)
  int completeAnalysisRow(
      @Param("analysis") String analysis,
      @Param("status") String status,
      @Param("request") String request,
      @Param("json") String json,
      @Param("error") String error,
      @Param("at") LocalDateTime at);

  @Update(
      """
      UPDATE tickets SET analysis_status=#{status},version=version+1,updated_at=#{at}
      WHERE id=#{id}
      """)
  int completeAnalysisTicket(
      @Param("id") String id, @Param("status") String status, @Param("at") LocalDateTime at);

  @Select(
      """
      SELECT * FROM ticket_analyses WHERE ticket_id=#{id}
      ORDER BY started_at DESC, id DESC LIMIT 50
      """)
  List<AnalysisRow> analyses(@Param("id") String id);

  @Update(
      """
      UPDATE ticket_analyses
      SET status='FAILED',error_code='server_restarted',completed_at=#{at}
      WHERE status='RUNNING'
      """)
  int failInterruptedAnalyses(@Param("at") LocalDateTime at);

  @Update(
      """
      UPDATE tickets SET analysis_status='FAILED',version=version+1,updated_at=#{at}
      WHERE analysis_status='RUNNING'
      """)
  int failInterruptedTickets(@Param("at") LocalDateTime at);
}
