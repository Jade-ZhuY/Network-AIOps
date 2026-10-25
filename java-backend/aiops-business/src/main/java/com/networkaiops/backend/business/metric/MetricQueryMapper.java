package com.networkaiops.backend.business.metric;

import java.time.LocalDateTime;
import java.util.List;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

/**
 * Read-only sampling queries against the shared demo dataset tables ({@code network_devices}/{@code
 * network_metrics}). Those tables are owned by {@code scripts/init_mysql.sql} and the SQL agent's
 * views; this backend never writes them and binds the value column per metric explicitly instead of
 * interpolating identifiers.
 */
@Mapper
public interface MetricQueryMapper {
  record SeriesRow(String interfaceName, LocalDateTime sampleTime, Double metricValue) {}

  @Select(
      """
      <script>
      SELECT i.interface_name AS interfaceName, m.sample_time AS sampleTime, m.latency_ms AS metricValue
      FROM network_metrics m
      JOIN network_devices d ON m.device_id = d.device_id
      LEFT JOIN network_interfaces i ON m.interface_id = i.interface_id
      WHERE d.hostname = #{hostname} AND m.sample_time &gt;= #{start} AND m.sample_time &lt; #{end}
      <if test="interfaceName != null">AND i.interface_name = #{interfaceName}</if>
      ORDER BY m.sample_time ASC, m.metric_id ASC
      LIMIT #{limit}
      </script>
      """)
  List<SeriesRow> latencySeries(
      @Param("hostname") String hostname,
      @Param("start") LocalDateTime start,
      @Param("end") LocalDateTime end,
      @Param("interfaceName") String interfaceName,
      @Param("limit") int limit);

  @Select(
      """
      <script>
      SELECT i.interface_name AS interfaceName, m.sample_time AS sampleTime,
             m.packet_loss_pct AS metricValue
      FROM network_metrics m
      JOIN network_devices d ON m.device_id = d.device_id
      LEFT JOIN network_interfaces i ON m.interface_id = i.interface_id
      WHERE d.hostname = #{hostname} AND m.sample_time &gt;= #{start} AND m.sample_time &lt; #{end}
      <if test="interfaceName != null">AND i.interface_name = #{interfaceName}</if>
      ORDER BY m.sample_time ASC, m.metric_id ASC
      LIMIT #{limit}
      </script>
      """)
  List<SeriesRow> packetLossSeries(
      @Param("hostname") String hostname,
      @Param("start") LocalDateTime start,
      @Param("end") LocalDateTime end,
      @Param("interfaceName") String interfaceName,
      @Param("limit") int limit);

  @Select(
      """
      <script>
      SELECT i.interface_name AS interfaceName, m.sample_time AS sampleTime,
             m.utilization_pct AS metricValue
      FROM network_metrics m
      JOIN network_devices d ON m.device_id = d.device_id
      LEFT JOIN network_interfaces i ON m.interface_id = i.interface_id
      WHERE d.hostname = #{hostname} AND m.sample_time &gt;= #{start} AND m.sample_time &lt; #{end}
      <if test="interfaceName != null">AND i.interface_name = #{interfaceName}</if>
      ORDER BY m.sample_time ASC, m.metric_id ASC
      LIMIT #{limit}
      </script>
      """)
  List<SeriesRow> utilizationSeries(
      @Param("hostname") String hostname,
      @Param("start") LocalDateTime start,
      @Param("end") LocalDateTime end,
      @Param("interfaceName") String interfaceName,
      @Param("limit") int limit);
}
