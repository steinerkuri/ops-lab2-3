# 实验 2 记录：第 3 组

评分时依据本文件和 `runs/` 中的原始数据核对。本文件中的每一个数值，都须能在某个 `runs/<名字>/` 的文件中找到：表格用 `scripts/table.sh` 生成后粘贴，其他数值注明出处（例如“`runs/r1-pool4/red.csv` 第 6 阶段”）。不要只贴截图。将 `<填写>` 替换为本组的内容。

第 4.1、4.4、5.1、5.3 节的预测须在对应的测量之前写好，写好后不要修改。预测错误不扣分，与实测不一致之处在分析中讨论。

## 1. 基本信息

| 项 | 内容 |
|---|---|
| 小组 | 第 3 组 |
| 仓库地址 | <https://github.com/steinerkuri/ops-lab2-3> |
| 主机 | 华为云 ECS，通用计算型，4 vCPU、8 GiB |
| CPU | General Purpose Processor；4 个 vCPU；`CPU 0 → CORE 0`、`CPU 1 → CORE 0`、`CPU 2 → CORE 1`、`CPU 3 → CORE 1` |
| 内存 | 7556 MiB |
| 数据目录所在的盘 | `/dev/vda1`，`ext4`；华为云通用型 SSD 云盘，40 GiB |
| 操作系统与内核 | Ubuntu 24.04.5 LTS；`6.8.0-147-generic` |
| Go、Prometheus、node_exporter | `go version go1.26.9 linux/amd64`；`prometheus, version 3.13.4 (branch: HEAD, revision: 007a9e9ba628f815ce83e1ba9f29b97981996c3c)`； `node_exporter, version 1.12.1 (branch: HEAD, revision: 6044da783597cc3b57aef7580ddcdcff58a4ee99)` |
| 分核 | enrolld：`2-3`；loadgen、Prometheus、node_exporter：`0-1` |

## 2. 任务 0：基线

`bin/enrolld -bench-fsync 2000` 连续运行三次的输出：

```text
fsync 次数 2000，总耗时 2.98 s，数据目录 data
fsync 耗时（毫秒）：mean 1.485  p50 1.319  p90 1.961  p99 3.763  max 5.189
按平均值推算，一个写者串行 fsync 每秒最多约 673 次（= 1000 / 1.485）

fsync 次数 2000，总耗时 3.06 s，数据目录 data
fsync 耗时（毫秒）：mean 1.518  p50 1.332  p90 2.100  p99 3.904  max 5.857
按平均值推算，一个写者串行 fsync 每秒最多约 659 次（= 1000 / 1.518）

fsync 次数 2000，总耗时 2.87 s，数据目录 data
fsync 耗时（毫秒）：mean 1.427  p50 1.263  p90 1.831  p99 3.907  max 7.041
按平均值推算，一个写者串行 fsync 每秒最多约 701 次（= 1000 / 1.427）
```

按平均值计算，单个写者串行 fsync 每秒最多约 677 次。三次之间相差多少？三次 mean 的最大值与最小值相差 0.091 ms，约为平均值的 6.2%；换算出的上限为 659～701 次/秒，相差 42 次/秒

空载和运行 fsync 测试时各工具的读数（各观察 5 秒以上，填写典型值）：

| 工具与列 | 空载 | 运行 `-bench-fsync` 时 | 该列的含义 |
|---|---|---|---|
| `vmstat -w 1`：r、b | r=0，b=0 | r=0，b=1 | r 是正在运行或等待 CPU 的任务数；b 是因不可中断 I/O 等待而阻塞的任务数 |
| `vmstat -w 1`：us、sy、id、wa、st | us=0%，sy=0%，id=100%，wa=0%，st=0% | us=0%，sy=2%，id=75%，wa=23%，st=0% | 分别表示用户态 CPU、内核态 CPU、空闲 CPU、I/O 等待和被虚拟机宿主机占用的 CPU 时间比例 |
| `iostat -dx 1 vda`：w/s、wkB/s | w/s=1，wkB/s=4 KiB/s | w/s=2140，wkB/s=11676 KiB/s | 每秒完成的写请求数，以及每秒写入磁盘的数据量 |
| `iostat -dx 1 vda`：w_await、f/s、f_await | w_await=0 ms，f/s=0，f_await=0 ms | w_await=0.45 ms，f/s=1427，f_await=0.06 ms | 写请求的平均完成时间、每秒 flush 请求数，以及 flush 请求的平均完成时间 |
| `iostat -dx 1 vda`：aqu-sz、%util | aqu-sz=0，%util=0.1% | aqu-sz=1.05，%util=95.4% | 平均未完成或排队的 I/O 数量，以及采样期间设备处理 I/O 的时间比例 |

运行 fsync 测试时，CPU 是否繁忙？哪几列表明存在等待？
运行 fsync 测试时 CPU 并不繁忙。us=0%、sy=2%、id=75%，说明 CPU 仍有大量空闲时间；wa=23% 表示相当一部分 CPU 时间在等待 I/O。vmstat 中 b 从 0 增加到 1，说明一个任务因 I/O 阻塞；iostat 中 aqu-sz 增加到 1.05、%util 增加到 95.4%，同时 w_await 和 f_await 非零，说明测试主要受磁盘持久化等待限制，而不是受 CPU 计算能力限制。

## 3. 任务 1：指标流水线

两个抓取目标的状态（`curl -s 127.0.0.1:9090/api/v1/targets` 中两处 `"health"` 的值）：up、up

本组编写的四条查询（与 `deploy/queries-red.txt` 一致）：

```text
server_rps          sum(rate(http_requests_total{route="${route}"}[${window}]))
server_error_rate   (sum(rate(http_requests_total{route="${route}",code=~"5.."}[${window}])) or vector(0)) / sum(rate(http_requests_total{route="${route}"}[${window}]))
server_p99_ms       1000 * histogram_quantile(0.99, sum by (le) (rate(http_request_duration_seconds_bucket{route="${route}"}[${window}])))
server_slo_good     sum(rate(http_request_duration_seconds_bucket{route="${route}",code="200",le="${slo}"}[${window}])) / sum(rate(http_requests_total{route="${route}"}[${window}]))
```

`runs/t1-light` 的数据（`scripts/table.sh runs/t1-light ok_rps mean_ms p99_ms server_rps server_mean_ms server_p99_ms cpu_ms_per_req db_query_mean_ms`）：

| step | target_rps | ok_rps | mean_ms | p99_ms | server_rps | server_mean_ms | server_p99_ms | cpu_ms_per_req | db_query_mean_ms |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 0 | 0.0 | - | - | 0 | NaN | NaN | +Inf | NaN |
| 2 | 50 | 50.5 | 11.71 | 12.71 | 51.8333 | 10.8845 | 19.9 | 0.675064 | 10.4624 |
| 3 | 100 | 97.8 | 11.70 | 13.92 | 95.5 | 10.9583 | 19.9 | 0.635573 | 10.5017 |
| all | - | 74.2 | 11.70 | 12.98 | - | - | - | - | - |

从这次实验读出：每次查询实际占用连接 10.5017 ms（`db_query_mean_ms`）；每个请求消耗的 CPU 0.635573 ms（`cpu_ms_per_req`，取 100 请求/秒的阶段）。

## 4. 任务 2：读路径

### 4.1 预测（R1 之前写）

| 资源 | 容量 | 每个请求占用（数据来源） | 推算的上限（请求/秒） |
|---|---|---|---|
| 连接池 | <`-pool`> 个连接 | <填写> ms | <填写> |
| CPU | enrolld 的 <填写> 个核 | <填写> ms | <填写> |

先达到上限的是：<填写>。预计从多少请求/秒起，客户端 p99 超过 50 ms：<填写>，理由：<填写>

R1 的到达率（`scripts/rates.sh <较小的上限>` 的输出）：<填写>

### 4.2 R1：`-pool 4`

`scripts/table.sh runs/r1-<…> ok_rps error_rate p99_ms server_p99_ms server_mean_ms inflight_avg cpu_ms_per_req pool_in_use_avg pool_wait_p99_ms sched_wait_p99_ms svc_cpu_busy procs_running_avg`：

<粘贴表格>

最大吞吐量 <填写> 请求/秒，出现在第 <填写> 阶段；客户端 p99 首次超过 50 ms 是在第 <填写> 阶段（<填写> 请求/秒）。

### 4.3 CPU 消耗在何处

在约 0.8 倍上限的负载下采集 20 秒 CPU 剖析，`go tool pprof -top` 的前 10 行（同时保存在 `runs/<填写>/pprof-top.txt`）：

```text
<粘贴>
```

`main.spin` 占 <填写>%；按本次的吞吐量和 enrolld 消耗的 CPU 计算，每个请求 <填写> ms，其中 spin 约 <填写> ms，其余 <填写> ms 消耗在：<填写>

### 4.4 R2：调大连接池（预测在 R2 之前写）

| 项 | 值与算法 |
|---|---|
| 每个请求占用的 CPU（取 R1 哪一阶段的 `cpu_ms_per_req`，选取理由） | <填写> |
| 推算的 CPU 上限 C | <填写> |
| R2 的池大小 P2 = ceil(2 × C × 每次查询的秒数) | <填写> |
| R2 的到达率（`scripts/rates.sh C 0.3 0.6 0.8 0.9 1.0 1.1 1.25 1.5`） | <填写> |
| 预测：R2 中先达到上限的是 | <填写> |

`scripts/table.sh runs/r2-<…> ok_rps error_rate p99_ms server_p99_ms inflight_avg cpu_cores cpu_ms_per_req cpu_wait_threads sched_wait_p99_ms pool_in_use_avg svc_cpu_busy procs_running_avg cpu_psi_some`：

<粘贴表格>

最大吞吐量 <填写> 请求/秒；与预测的 C 相差：<填写>

## 5. 任务 3：写路径

### 5.1 预测：`-sync each`（W1 之前写）

| 项 | 值与算法 |
|---|---|
| fsync 平均耗时（任务 0） | <填写> ms |
| 推算的最大 TPS | <填写> |
| 达到上限时 enrolld 大约使用几个核（写路径没有 spin，按 4.3 节拆分出的“spin 以外的开销”估计每个写请求的 CPU） | <填写> |
| W1 的到达率（`scripts/rates.sh <最大 TPS> 0.2 0.4 0.6 0.8 0.9 1.0 1.1 1.2`） | <填写> |

### 5.2 W1：`-sync each`

`scripts/table.sh runs/w1-<…> ok_rps error_rate p99_ms server_p99_ms cpu_cores fsync_per_s fsync_mean_ms batch_mean svc_cpu_busy cpu_iowait disk_w_per_s disk_w_await_ms disk_f_per_s disk_f_await_ms disk_aqu_sz disk_util`：

<粘贴表格>

### 5.3 预测：`-sync group`（W2 之前写）

在 W1 达到上限时的到达率下，改为组提交后：吞吐量 <填写>；平均每次 fsync 处理 <填写> 条记录；客户端 p99 约 <填写>。理由：<填写>

W2 的到达率：<填写>

### 5.4 W2：`-sync group`

（列与 5.2 相同）

<粘贴表格>

### 5.5 W3：`-sync interval`

（列与 5.2 相同）

<粘贴表格>

## 6. 分析问题

每题先列出所用数据（引用上面的表或 `runs/` 中的文件），再写结论，并说明结论的成立条件。每题 300～600 字。

**问题 1：上限由什么决定。** 按 L-07 第 25 页资源账的格式，为 enrolld 的读路径编制一份资源账：资源、每个请求占用（实测）、容量、推算的上限、实测的最大吞吐量、饱和观测项。预测与实测相差多少，差异来自何处？`cpu_ms_per_req` 随负载如何变化，原因是什么？这对“在低负载下测量每请求开销，再推算上限”的做法意味着什么？`db_query_mean_ms` 为什么大于 `-db-ms`？以“p99 ≤ 50 ms”为目标，R1 能承受的最大阶段相当于上限的多少比例？与 L-07 第 6 页“容量 = 上限 × 0.7”比较，为什么尚未达到上限延迟就已上升？R2 调大连接池后，瓶颈转移到了哪个资源？

<填写>

**问题 2：利用率不等于饱和。** R1 达到上限时，enrolld 所在核的 CPU 利用率是多少？哪个数值最先表明资源已经饱和？R2 中 CPU 利用率接近 100% 时，内核层的 `procs_running_avg`、`cpu_psi_some`、`cpu_wait_threads` 和 Go 运行时层的 `sched_wait_p99_ms` 分别如何变化？为什么内核层几乎观察不到排队，排队发生在哪里？这与 L-06 第 16、17 页 Tomcat 的线程池有何相同之处？最后用 Little's Law 核对：从 R1 选取三个阶段，用 `server_rps × server_mean_ms` 计算在途请求数，并与 `inflight_avg` 比较；W 为什么必须用平均值而不能用 p99？哪个阶段不一致，原因是什么？

<填写>

**问题 3：持久性以延迟为代价。** W1 实测的最大 TPS 与 1000 ÷ fsync 平均耗时相比如何？W1 达到上限时 CPU、内存、磁盘的指标各是多少，哪几列表明磁盘饱和？应用测得的 `fsync_mean_ms` 与 `disk_w_await_ms`、`disk_f_await_ms` 为什么不同？一次 fsync 大约对应几次写和几次 flush？W1 与 W2 在 `disk_util` 相近时吞吐量相差多少，`%util` 接近 100% 能否说明磁盘已经饱和？组提交的 `batch_mean` 如何随负载变化，低负载时是否有收益，本组的预测是否正确？W3 快了多少，代价是什么？选课记录应采用哪一种方式，在什么条件下 interval 可以接受？

<填写>

**问题 4：延迟数值的测量位置与方法。** 同一阶段中，客户端与服务端的平均值、p99 各相差多少？列出只计入客户端的时间组成。找出一个服务端 p99 大于客户端 p99 的阶段，并解释原因（L-08 第 10 页）。比较服务端的 `server_slo_good` 与客户端的 `slo_good`；若存在过载阶段，二者为何相差很大？SLI 应在何处测量（L-08 第 19 页）？用 R1 的 `steps.csv`，将各阶段的 p99 求平均，与 `all` 行的 p99 比较，说明百分位数为什么不能平均，以及正确的合并方法。最后计算错误预算：SLO 为“30 天内 99% 的读请求在 50 ms 内成功返回”，若 R1 中第一个不达标阶段的负载持续下去，燃烧率是多少，30 天的预算多久耗尽（L-08 第 21 页）？

<填写>

## 7. 选做记录

| 选做 | 完成情况与证据 |
|---|---|
| O1 内存与 GC | <未做 / 预测、`runs/` 目录、结论> |
| O2 网络 | <未做 / 两台主机的规格与拓扑、`runs/` 或日志、结论> |
| O3 告警与看板 | <未做 / 规则文件、触发记录、看板说明> |
| O4 迁移到小组项目 | <未做 / 仓库链接、测了哪个资源、结论> |

### O2：网络上限

#### 两台主机的规格与拓扑

| 主机 | 规格与系统 | 实验角色 |
|---|---|---|
| 主机 A | 华为云 ECS，通用计算型 `x1.4u.8g`，4 vCPU、8 GiB，Ubuntu 24.04；位于华东-上海一、可用区3 | 运行 enrolld，使用 CPU 2～3，通过 `0.0.0.0:8080` 监听 |
| 主机 B | 华为云 ECS，通用计算型 `x1.4u.8g`，4 vCPU、8 GiB，Ubuntu 24.04；位于华东-上海一、可用区3 | 运行 loadgen，向主机 A 的私网地址发送请求 |

两台主机位于同一个 `vpc-default (192.168.0.0/16)` 和 `subnet-default (192.168.0.0/24)`。实验请求通过 VPC 私网传输，不经过弹性公网 IP。主机 A 的安全组仅允许来自主机 B 私网地址的 TCP 8080 流量；公网 IP 仅用于 SSH 管理，不参与实验测量。

#### 测量前预测

`/api/export?kb=256` 每个响应正文约为 256 KiB，因此每增加 1 请求/秒，理论响应正文带宽约增加 2 Mib/s。预计在低负载阶段，主机 A 的 `txkB/s` 会随请求率近似线性增长；接近网络上限后，继续提高目标请求率将不能使发送吞吐等比例增加，同时实际成功请求率可能低于目标值，并可能出现延迟、超时或 TCP 重传增加。

本实验两台主机均为 4 vCPU、8 GiB，测得的上限实际是主机 A 发送能力、主机 B 接收能力以及两端 CPU 能力共同决定的端到端上限。判断网络是否为主要限制时，还需结合 CPU 使用率、实际吞吐和 TCP 重传观察。

## 8. 成员分工

每位成员一行，只填写 GitHub 用户名，无需填写姓名；行数应与小组人数一致。

| GitHub 用户名 | 负责的部分 |
|---|---|
| steinerkuri | 任务0 任务1 选做O2 |
