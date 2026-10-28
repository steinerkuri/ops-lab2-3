# enrolld 看板：三行九格

看板由 Prometheus Query 页面生成。下面按业务、服务 RED、资源 USE 三组索引实际图表；同一格存在多个单位或细节视图时分图展示。查询中 `[1m]` 表示每个绘图时刻以前一分钟为统计窗口，第三格使用 `[10m]`。

截图时间为 UTC，北京时间加 8 小时。UTC 约 02:31～02:37 存在 node_exporter 采集缺口，不能把缺失值解释为零；第一行使用适配示例程序的业务指标，第三格统计记录条数而非在线人数。详细说明见 [截图 readme](../runs/cmm-o3-dashboard/readme.md)。

## 图表索引

| 层次 | 第 1 列 | 第 2 列 | 第 3 列 |
|---|---|---|---|
| 业务 | 第 1 格：[读请求达标比例](../runs/cmm-o3-dashboard/第一格.png)，目标 99% | 第 2 格：[选课成功率](../runs/cmm-o3-dashboard/第二格.png) | 第 3 格：[近 10 分钟确认记录数](../runs/cmm-o3-dashboard/第三格.png) |
| 服务 RED | 第 4 格：[请求速率](../runs/cmm-o3-dashboard/第四格1.png)、[5xx 比例](../runs/cmm-o3-dashboard/第四格2.png) | 第 5 格：[p50/p99 总体](../runs/cmm-o3-dashboard/第五格1.png)、[选课接口细节](../runs/cmm-o3-dashboard/第五格2.png)，单位 ms | 第 6 格：[在途请求](../runs/cmm-o3-dashboard/第六格1.png)、[连接占用](../runs/cmm-o3-dashboard/第六格2.png)、[等待 p99](../runs/cmm-o3-dashboard/第六格3.png) |
| 资源 USE | 第 7 格：[服务核 CPU 忙碌率](../runs/cmm-o3-dashboard/第七格1.png)，单位 %；[可用内存](../runs/cmm-o3-dashboard/第七格2.png)，单位 MiB | 第 8 格：[磁盘写 await](../runs/cmm-o3-dashboard/第八格1.png)，单位 ms；[磁盘 util](../runs/cmm-o3-dashboard/第八格2.png)，单位 % | 第 9 格：[网络接收](../runs/cmm-o3-dashboard/第九格1.png)、[网络发送](../runs/cmm-o3-dashboard/第九格2.png)，单位 Mbps |

各截图选取的时间范围可能不同。例如磁盘 util 图包含此前 W1 的写负载；对照分析前需核对时间，不能把不同时刻的峰值直接关联。网络图中的 lo 是本机回环接口，不代表公网 EIP 带宽。

## 第一行：业务查询

**第 1 格：读请求达标比例。** 越接近 1 越好，目标是至少 0.99。

```promql
sum(rate(http_request_duration_seconds_bucket{job="enrolld",route="/api/courses/{id}",code="200",le="0.05"}[1m])) / sum(rate(http_requests_total{job="enrolld",route="/api/courses/{id}"}[1m]))
```

**第 2 格：选课提交成功率。** 1 表示这段时间观察到的选课请求全部成功。

```promql
sum(rate(http_requests_total{job="enrolld",route="/api/enroll",code="200"}[1m])) / sum(rate(http_requests_total{job="enrolld",route="/api/enroll"}[1m]))
```

**第 3 格：最近 10 分钟确认的选课记录数。** 

```promql
sum(increase(enroll_commits_total{job="enrolld"}[10m]))
```

## 第二行：服务 RED 查询

**第 4 格：每秒处理多少请求，以及失败比例。**

请求数，单位是次/秒：

```promql
sum by(route)(rate(http_requests_total{job="enrolld"}[1m]))
```

服务器失败比例，1 表示 100%：

```promql
(sum by(route)(rate(http_requests_total{job="enrolld",code=~"5.."}[1m])) or on(route) (0 * sum by(route)(rate(http_requests_total{job="enrolld"}[1m])))) / sum by(route)(rate(http_requests_total{job="enrolld"}[1m]))
```

**第 5 格：请求耗时 p50 和 p99。** 单位都是毫秒。

p50：

```promql
1000 * histogram_quantile(0.50, sum by(route,le)(rate(http_request_duration_seconds_bucket{job="enrolld"}[1m])))
```

p99：

```promql
1000 * histogram_quantile(0.99, sum by(route,le)(rate(http_request_duration_seconds_bucket{job="enrolld"}[1m])))
```

**第 6 格：同时处理的请求数、占用的数据库连接数、等待连接的时间。**

正在处理的请求数：

```promql
sum by(route)(http_inflight_requests{job="enrolld"})
```

正在使用的连接数：

```promql
db_pool_in_use{job="enrolld"}
```

等连接的 p99 时间，单位毫秒：

```promql
1000 * histogram_quantile(0.99, sum by(le)(rate(db_pool_wait_seconds_bucket{job="enrolld"}[1m])))
```

## 第三行：资源 USE 查询

**第 7 格：CPU 忙碌百分比、剩余内存。**

选课程序所用 CPU 的忙碌百分比，接近 100 表示很忙：

```promql
100 * sum(rate(node_cpu_seconds_total{job="node",cpu=~"2|3",mode!~"idle|iowait"}[1m])) / count(node_cpu_seconds_total{job="node",cpu=~"2|3",mode="idle"})
```

服务器可用内存，单位 MiB：

```promql
node_memory_MemAvailable_bytes{job="node"} / 1048576
```

**第 8 格：磁盘写入有多慢、有多忙。** 本实验文件所在的磁盘是 vda。

一次磁盘写操作的平均耗时，单位毫秒：

```promql
1000 * rate(node_disk_write_time_seconds_total{job="node",device="vda"}[1m]) / rate(node_disk_writes_completed_total{job="node",device="vda"}[1m])
```

磁盘忙碌时间的百分比：

```promql
100 * rate(node_disk_io_time_seconds_total{job="node",device="vda"}[1m])
```

**第 9 格：网络接收、发送速度。** 单位 Mbps。这次程序与测试工具都在同一台服务器，名称为 `lo` 的本机网络也需要看。

接收速度：

```promql
rate(node_network_receive_bytes_total{job="node"}[1m]) * 8 / 1000000
```

发送速度：

```promql
rate(node_network_transmit_bytes_total{job="node"}[1m]) * 8 / 1000000
```

## 第五格实际使用的合并查询

以下查询通过 `percentile` 标签区分 p50 与 p99，放在同一个输入框中生成同图曲线；选择 Unstacked。p50、p99 都是服务端直方图估算值，不是客户端 CSV 中的精确分位数。

```promql
label_replace(
  1000 * histogram_quantile(0.50, sum by(route,le)(rate(http_request_duration_seconds_bucket{job="enrolld"}[1m]))),
  "percentile", "p50", "route", ".*"
)
or
label_replace(
  1000 * histogram_quantile(0.99, sum by(route,le)(rate(http_request_duration_seconds_bucket{job="enrolld"}[1m]))),
  "percentile", "p99", "route", ".*"
)
```
