package com.networkaiops.backend.business.monitor;

import java.time.LocalDateTime;
import java.util.List;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

/**
 * Hand-written SQL for the monitor table, shared by the MySQL production schema and the H2 test
 * schema. Application-supplied UTC timestamps, soft delete and optimistic versioning follow the
 * ticket tables.
 */
@Mapper
public interface MonitorMapper {
  record MonitorRow(
      String id,
      String ownerId,
      String tenantId,
      String name,
      String type,
      String hostname,
      String labels,
      String description,
      String status,
      long version,
      boolean deleted,
      LocalDateTime createdAt,
      LocalDateTime updatedAt) {}

  @Select(
      """
      <script>
      SELECT * FROM monitor
      WHERE id=#{id} AND owner_id=#{owner} AND tenant_id=#{tenant} AND deleted=FALSE
      <if test="lock">FOR UPDATE</if>
      </script>
      """)
  MonitorRow find(
      @Param("id") String id,
      @Param("owner") String owner,
      @Param("tenant") String tenant,
      @Param("lock") boolean lock);

  @Select(
      """
      <script>
      SELECT * FROM monitor
      WHERE owner_id=#{owner} AND tenant_id=#{tenant} AND deleted=FALSE
      AND (LOWER(name) LIKE #{query} ESCAPE '!' OR LOWER(hostname) LIKE #{query} ESCAPE '!'
           OR LOWER(type) LIKE #{query} ESCAPE '!')
      <if test="type != null">AND type=#{type}</if>
      <if test="status != null">AND status=#{status}</if>
      ORDER BY updated_at DESC, id DESC LIMIT #{limit} OFFSET #{offset}
      </script>
      """)
  List<MonitorRow> list(
      @Param("owner") String owner,
      @Param("tenant") String tenant,
      @Param("query") String query,
      @Param("type") String type,
      @Param("status") String status,
      @Param("limit") int limit,
      @Param("offset") int offset);

  @Select(
      """
      <script>
      SELECT COUNT(*) FROM monitor
      WHERE owner_id=#{owner} AND tenant_id=#{tenant} AND deleted=FALSE
      AND (LOWER(name) LIKE #{query} ESCAPE '!' OR LOWER(hostname) LIKE #{query} ESCAPE '!'
           OR LOWER(type) LIKE #{query} ESCAPE '!')
      <if test="type != null">AND type=#{type}</if>
      <if test="status != null">AND status=#{status}</if>
      </script>
      """)
  long count(
      @Param("owner") String owner,
      @Param("tenant") String tenant,
      @Param("query") String query,
      @Param("type") String type,
      @Param("status") String status);

  @Insert(
      """
      INSERT INTO monitor(id,owner_id,tenant_id,name,type,hostname,labels,description,status,
      version,deleted,created_at,updated_at)
      VALUES(#{id},#{owner},#{tenant},#{name},#{type},#{hostname},#{labels},#{description},
      'UNKNOWN',0,FALSE,#{at},#{at})
      """)
  int insert(
      @Param("id") String id,
      @Param("owner") String owner,
      @Param("tenant") String tenant,
      @Param("name") String name,
      @Param("type") String type,
      @Param("hostname") String hostname,
      @Param("labels") String labels,
      @Param("description") String description,
      @Param("at") LocalDateTime at);

  @Update(
      """
      UPDATE monitor
      SET name=#{name},type=#{type},hostname=#{hostname},labels=#{labels},
      description=#{description},version=version+1,updated_at=#{at}
      WHERE id=#{id} AND owner_id=#{owner} AND tenant_id=#{tenant}
      AND version=#{version} AND deleted=FALSE
      """)
  int update(
      @Param("id") String id,
      @Param("owner") String owner,
      @Param("tenant") String tenant,
      @Param("version") long version,
      @Param("name") String name,
      @Param("type") String type,
      @Param("hostname") String hostname,
      @Param("labels") String labels,
      @Param("description") String description,
      @Param("at") LocalDateTime at);

  @Update("UPDATE monitor SET deleted=TRUE,version=version+1,updated_at=#{at} WHERE id=#{id}")
  int softDelete(@Param("id") String id, @Param("at") LocalDateTime at);
}
