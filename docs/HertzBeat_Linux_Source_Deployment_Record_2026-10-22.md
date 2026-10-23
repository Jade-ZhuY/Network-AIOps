# HertzBeat Linux 服务器源码部署全流程实录

> **用途：**记录这一次已经完成的实际部署，解释从环境检查、工具安装、依赖下载、源码构建，到启动、验证、备份的完整过程。\
> **部署日期：**2026-10-21 至 2026-10-22，时间均按北京时间（UTC+8）说明。\
> **最后一次只读核对：**2026-10-22T00:24:06.726530+08:00。\
> **重要：**服务器目前已经部署成功。这不是要求你把所有初始化命令再执行一遍的脚本。日常启动、停止、查看状态，请直接使用第 22 节的管理命令。\
> **保密处理：**本文不记录 SSH 密码、管理员真实密码、数据库密码、JWT 密钥、AES 密钥或实际访问令牌。连接地址使用 `HOST` 占位，凭据使用 `TOKEN`、`ENCRYPT_KEY` 占位。

---

## 阅读导航

1. [部署目标与最终结果](#1-部署目标与最终结果)
2. [服务器原有环境与限制](#2-服务器原有环境与限制)
3. [为什么采用这套部署方式](#3-为什么采用这套部署方式)
4. [最终目录布局](#4-最终目录布局)
5. [从 Windows 连接 Linux](#5-从-windows-连接-linux)
6. [部署前的检查](#6-部署前的检查)
7. [创建目录、保护原有服务](#7-创建目录保护原有服务)
8. [下载与验证源码](#8-下载与验证源码)
9. [建立源码版本管理](#9-建立源码版本管理)
10. [安装和配置开发工具](#10-安装和配置开发工具)
11. [项目级环境变量与依赖缓存](#11-项目级环境变量与依赖缓存)
12. [构建前端](#12-构建前端)
13. [构建后端](#13-构建后端)
14. [打包完整服务端程序](#14-打包完整服务端程序)
15. [创建独立运行账户](#15-创建独立运行账户)
16. [配置数据库、历史存储和运行参数](#16-配置数据库历史存储和运行参数)
17. [生成和保护账号、密码、密钥](#17-生成和保护账号密码密钥)
18. [部署构建产物与目录链接](#18-部署构建产物与目录链接)
19. [配置进程管理与启动命令](#19-配置进程管理与启动命令)
20. [验证网页、认证和基础接口](#20-验证网页认证和基础接口)
21. [验证真实采集、历史数据和重启恢复](#21-验证真实采集历史数据和重启恢复)
22. [日常运维速查](#22-日常运维速查)
23. [本地浏览器访问服务器页面](#23-本地浏览器访问服务器页面)
24. [后续二次开发与重新发布](#24-后续二次开发与重新发布)
25. [数据、配置备份与恢复边界](#25-数据配置备份与恢复边界)
26. [实际遇到的问题与处理过程](#26-实际遇到的问题与处理过程)
27. [哪些事情已经完成，哪些尚未做](#27-哪些事情已经完成哪些尚未做)
28. [排查问题的推荐顺序](#28-排查问题的推荐顺序)
29. [下一阶段接入现有 Agent 的位置](#29-下一阶段接入现有-agent-的位置)
30. [官方资料与证据位置](#30-官方资料与证据位置)
31. [附录：实际脚本、校验值与验证摘要](#31-附录实际脚本校验值与验证摘要)

---

## 1. 部署目标与最终结果

### 1.1 这次真正要完成什么

本次目标不是只下载一个压缩包，也不是仅让一个端口打开，而是：

- 在已经运行 RAGFlow 和 Qwen 服务的 Linux 环境中，新增一套 HertzBeat。
- 按照原有服务的习惯组织目录：程序、工具、配置放在 `/opt`，源码及数据放在用户的数据挂载目录。
- 准备源码二次开发所需的 Java、Maven、Node.js、pnpm 环境。
- 获取固定版本源码，完成 Angular 前端及 Java 后端构建。
- 将自己构建的发布包部署并启动。
- 验证网页、认证、接口、真实采集和数据恢复。
- 不修改或重启已有的 RAGFlow、Qwen 服务。

### 1.2 最终完成情况

| 项目 | 结果 |
|---|---|
| 官方源码获取及 SHA512 校验 | 已完成 |
| JDK、Maven、前端构建工具准备 | 已完成 |
| 前端依赖安装及生产构建 | 已完成 |
| 后端 24 个 Maven Reactor 模块构建 | 已完成 |
| 自行构建完整服务端发布包 | 已完成 |
| 独立服务账户、配置、进程管理 | 已完成 |
| 网页、静态资源、登录、基础 API | 已验证 |
| H2 元数据及 DuckDB 历史数据目录 | 已落在指定数据卷 |
| 本机 HTTP 自检监控 | 已创建，周期 30 秒 |
| 实时指标、历史查询、重启恢复 | 已验证 |
| 原有 RAGFlow、Qwen | 未被修改或重启 |

最终运行的是**由本次源码构建生成的服务端程序**，不是只下载官方二进制安装包后直接启动。

### 1.3 当前服务的使用边界

当前是可以继续开发和验证业务的**单机部署基础环境**。本次没有完成：

- 现有 Network AIOps Agent 的 Java 接入和前端调查页面。
- HertzBeat 自带 AI 功能与现有 Qwen 的配置集成。
- 真实交换机、路由器等网络设备的批量接入。
- 完整单元测试、负载测试、性能 SLA 或生产高可用验收。
- 宿主机重启、容器重建之后的自动启动钩子。

这几项与“本次项目能正常运行”不同，后续应分别实施和验收。

## 2. 服务器原有环境与限制

### 2.1 系统识别结果

| 项目 | 实际情况 |
|---|---|
| SSH 登录用户 | `root` |
| 本次使用的 SSH 端口 | `20289` |
| 可见用户空间系统 | Ubuntu 20.04.6 LTS |
| CPU 架构 | x86_64 / amd64 |
| 内核 | `5.10.0-216.0.0.115.oe2203sp4.x86_64` |
| 根文件系统 | `overlay` |
| 数据挂载目录 | `/root/siton-data-zyh`，NFSv4 |
| Docker 命令 | 当时环境中未找到 |
| Node.js | 已存在，`/usr/bin/node`，版本 `22.23.1` |
| 全局 Java、Maven | 当时没有可用命令，另行独立安装 |
| Supervisor | 系统中已经安装，可供独立实例使用 |

**用户空间系统和宿主机内核不是一回事。**虽然内核版本字符串带有宿主机发行版信息，但 `/etc/os-release` 显示的是 Ubuntu 20.04。可见环境使用 `overlay` 根文件系统，因此没有把它当成一台具有完整 systemd 生命周期的裸机服务器来配置。

### 2.2 内存和 CPU 应怎样理解

最初检查时：

- `free -h` 显示的是约 1 TiB 的可见内存信息。
- `nproc` 返回 104。
- cgroup 的 `memory.limit_in_bytes` 为 `171798691840`，即 **160 GiB**。

这说明不应仅凭 `free -h` 就认定当前环境可以独占宿主机全部内存，也不应凭 `nproc` 就把全部 CPU 开满用于编译。

所以本次采用了相对保守的资源参数：

- Maven：两个 Reactor 构建线程，JVM 最大堆 2 GiB。
- 前端构建：V8 old space 上限 4 GiB。
- HertzBeat 服务：JVM 最大堆 2 GiB、直接内存上限 512 MiB，并将 JVM 可见处理器数设为 4。

这些是 JVM、Node 进程参数，**不是完整的操作系统 CPU/内存硬配额**。Java 进程的实际 RSS 还包含元空间、线程栈、代码缓存及原生库内存。

### 2.3 磁盘布局的含义

只读复核时，根文件系统约 258 GB，尚有约 230 GB 可用；用户 NFS 数据卷约 2 TB，尚有约 1.6 TB 可用。容量是当时的快照，并非承诺永久不变。

本次据此进行了区分：

- 程序、JDK、Maven、依赖缓存放在 `/opt/hertzbeat-native`。
- 源码、业务数据、日志、备份放在 `/root/siton-data-zyh/hertzbeat-native`。
- 源码可以保留在用户数据卷，但大量 Maven、pnpm 缓存不必全部挤在 NFS 上，以减少依赖目录的元数据访问开销。

独立挂载目录不等于已经拥有灾备。是否随平台实例删除而保留、存储端怎样备份，仍取决于服务器平台策略。

### 2.4 原有服务在哪里

| 原有服务 | 相关位置 | 当时的内部监听 |
|---|---|---|
| RAGFlow 程序 | `/opt/ragflow-native` | 网页 `127.0.0.1:18080` |
| RAGFlow 数据 | `/root/siton-data-zyh/ragflow-native` | 独立 MySQL、Redis、Elasticsearch 等配置 |
| Qwen 模型权重 | `/root/siton-data-zyh/models/Qwen3.8-27B` | vLLM `127.0.0.1:8000` |
| Qwen 运行环境 | `/opt/conda/envs/qwen38` | 不与 Java 环境混用 |
| Qwen 工作目录 | `/root/vllm` | 不修改其启动脚本 |

其中 Qwen 的目录/服务名与模型配置中的架构标识并不完全相同；本次部署没有重新识别或修改它的模型版本。

## 3. 为什么采用这套部署方式

### 3.1 不是照搬另一个 RAG 项目的全部组件

之前讨论过的 General RAG System 可以参考的是分工：

```text
前端负责交互
Java 后端负责业务与身份
Python 服务负责 AI
服务之间通过 HTTP 或必要的异步机制通信
```

本次还没有进入 Agent 接入阶段，所以没有为了“参考架构”额外安装 RabbitMQ、MinIO、Redis 或另一套 RAG 服务。

### 3.2 为什么没有采用 Docker 部署

本次实际采用原生进程方式，原因包括：

1. 当前 SSH 环境没有 Docker 命令。
2. 原有 RAGFlow 也是一套原生部署布局，便于保持目录管理习惯。
3. 你的目标包含二次开发，因此需要可编辑源码和编译环境。
4. 不需要为了首次启动再套一层完整容器编排。

打包过程中生成了 Docker 相关压缩包，属于上游 Maven `release` profile 的产物，**不代表最终服务使用了 Docker**。

### 3.3 为什么先用内置存储

| 用途 | 本次实际选择 |
|---|---|
| 业务元数据 | H2 文件数据库 |
| 历史指标 | DuckDB 文件数据库 |
| 实时指标 | 内存 |
| 内部消息队列 | 内存 |
| 分布式外部采集器 | 暂不启用 |

这样避免给现有服务器再增加一套数据库、消息队列、时序库的运维工作。正式扩大规模时，再单独评估 PostgreSQL、VictoriaMetrics 等外部存储。

## 4. 最终目录布局

### 4.1 程序、工具、配置目录

```text
/opt/hertzbeat-native/
├── env.sh                         # 仅供本项目使用的环境变量
├── DEPLOYMENT.md                  # 简版部署说明
├── bin/
│   ├── install-tools.sh           # 工具安装记录脚本
│   ├── build-backend.sh           # 后端源码构建
│   ├── build-frontend.sh          # 前端源码构建
│   ├── package-server.sh          # 发布包构建
│   ├── deploy-built-release.sh    # 首次发布部署；会拒绝覆盖现有发布
│   ├── configure-runtime.py       # 首次运行配置生成
│   ├── run-server.sh              # 前台运行 Java，交给 Supervisor 管理
│   ├── start.sh                   # 启动独立 Supervisor 或服务
│   ├── hertzbeatctl               # 管理本项目专用 Supervisor
│   ├── dev-frontend.sh            # Angular 开发服务器入口
│   ├── smoke-test.py              # HTTP/认证/静态资源冒烟
│   └── selfcheck-monitor.py       # 本机 HTTP 真实采集自检
├── config/
│   ├── application.yml            # 当前生效的运行配置
│   ├── sureness.yml               # 当前生效的认证、角色配置
│   ├── logback-spring.xml         # 日志配置
│   ├── supervisord.conf           # 独立进程管理配置
│   ├── maven-settings.xml         # 项目级 Maven 镜像
│   ├── credentials.json           # root 专用凭据/密钥文件，不提交 Git
│   ├── admin-login.txt            # root 专用登录信息，不提交 Git
│   └── deployment.json            # 不含真实密钥的部署清单
├── downloads/                     # 源码包、工具压缩包和校验文件
├── tools/
│   ├── jdk -> 已解压的 Corretto 目录
│   ├── maven -> 已解压的 Maven 目录
│   └── pnpm/                      # npm 私有 prefix 安装的 pnpm
├── cache/
│   ├── maven/                     # 本项目 Maven 本地仓库
│   ├── pnpm-store/                # pnpm 包缓存
│   └── pnpm-virtual-store/        # pnpm 实际依赖布局
├── releases/
│   └── apache-hertzbeat-1.9.0-bin/
├── source -> 用户数据卷上的源码
├── current -> 当前发布目录
└── run/
    ├── supervisor.sock            # 本地 Unix 管理套接字
    ├── supervisord.pid
    └── tmp/                       # 服务专用临时目录
```

### 4.2 用户数据卷目录

```text
/root/siton-data-zyh/hertzbeat-native/
├── source/
│   └── apache-hertzbeat-1.9.0-src/
├── data/
│   ├── metadata/
│   │   └── hertzbeat.mv.db         # H2 元数据库
│   └── history/
│       └── history.duckdb          # 历史指标库
├── logs/
│   ├── install-tools.log
│   ├── build-backend.log
│   ├── build-frontend.log
│   ├── package-server.log
│   ├── deploy-release.log
│   ├── supervisord.log
│   ├── runtime/                   # Java 标准输出、错误及应用日志
│   ├── smoke-before-restart.json
│   ├── smoke-after-restart.json
│   ├── selfcheck-before-restart.json
│   ├── selfcheck-after-restart.json
│   └── selfcheck-history.json
├── backups/
├── deployment.json
└── DEPLOYMENT.md
```

### 4.3 需要认清的链接

| 入口 | 实际指向 |
|---|---|
| `/opt/hertzbeat-native/source` | `/root/siton-data-zyh/hertzbeat-native/source/apache-hertzbeat-1.9.0-src` |
| `/opt/hertzbeat-native/current` | `/opt/hertzbeat-native/releases/apache-hertzbeat-1.9.0-bin` |
| 当前发布目录的 `config` | `/opt/hertzbeat-native/config` |
| 当前发布目录的 `data` | `/root/siton-data-zyh/hertzbeat-native/data` |
| 当前发布目录的 `logs` | `/root/siton-data-zyh/hertzbeat-native/logs/runtime` |

发布包原始配置保留为 `config.upstream`。**编辑 `config.upstream` 不会改变当前生效配置。**

## 5. 从 Windows 连接 Linux

### 5.1 实际使用的连接方式

最终使用 Windows 自带的 OpenSSH：

```powershell
ssh -T -p PORT root@HOST
```

- `HOST`：你实际服务器的地址。
- `PORT`：本次是 `20289`。
- `root`：本次已有的登录用户。
- 密码通过 SSH 交互提示输入，没有写在命令行参数或本文中。

最初连接测试只执行了用户、内核和工作目录检查；部署操作是在你随后明确要求安装环境、部署源码和启动项目之后开展的。

### 5.2 为什么不应直接复制 Windows 环境

源码可以跨平台使用，但运行环境需对应 Linux 和 CPU 架构：

- Linux x64 JDK，不使用 Windows JDK 压缩包。
- Linux 上的 Node.js 与包管理器。
- 不复制 Windows 的 `node_modules` 或 Python `.venv` 作为 Linux 环境。
- Linux 启动脚本使用 `.sh`，不使用 Windows 的 `.bat`。

Windows 在这次任务中主要是连接和操作的控制端，真正的编译、数据写入、Java 进程都发生在 Linux 环境。

## 6. 部署前的检查

### 6.1 检查系统及挂载

以下是当时检查内容的整理版：

```bash
cat /etc/os-release
uname -srm
free -h
nproc
df -hT / /root/siton-data-zyh
cat /sys/fs/cgroup/memory/memory.limit_in_bytes
```

还检查了目标目录是否存在，避免覆盖原有内容：

```bash
ls -ld /opt/hertzbeat-native
ls -ld /root/siton-data-zyh/hertzbeat-native
```

首次检查时，这两个新目录都尚未存在。

### 6.2 检查已有命令

检查了 Git、curl、tar、xz、unzip、Node、npm、corepack、Python、Supervisor、用户及 ACL 管理工具等。

结果是已有基础工具足够使用，不需要先升级整套操作系统。Java、Maven 和 pnpm 单独为 HertzBeat 准备。

### 6.3 检查端口

```bash
ss -lnt
```

重点区分：

| 端口 | 含义 | 本次处理 |
|---|---|---|
| 20289 | SSH | 保持原状 |
| 18080 | 原有 RAGFlow 网页 | 不占用、不调整 |
| 8000 | 原有 Qwen/vLLM | 不占用、不调整 |
| 1157 | HertzBeat 网页及 HTTP API | 使用，绑定回环地址 |
| 1158 | HertzBeat 外部采集器通信 | 本次关闭外部监听 |
| 4200 | Angular 开发服务器 | 提供启动脚本，但未长期运行 |

### 6.4 检查下载连通性

检查了 GitHub、Maven Central、npm registry、Node.js 下载站点等 HTTPS 地址。需要注意：

- HTTP HEAD 成功，只能说明这个请求成功。
- 它不保证 Git 的大文件传输、后续每一个依赖下载都一样快。
- 本次确实遇到了 GitHub 拉取慢和部分地址连接失败，因此后面准备了官方下载包路线。

## 7. 创建目录、保护原有服务

### 7.1 实际创建的基础目录

```bash
mkdir -p /opt/hertzbeat-native/{bin,config,downloads,releases,run,tools}
mkdir -p /root/siton-data-zyh/hertzbeat-native/{source,data,logs,cache,backups}
```

随后又创建了本项目专用缓存：

```bash
mkdir -p /opt/hertzbeat-native/cache/{maven,pnpm-store,pnpm-virtual-store}
```

### 7.2 对原有服务采取了哪些保护措施

- 不修改 `/opt/ragflow-native` 下的配置或脚本。
- 不修改 `/root/vllm` 下的 Qwen 启动配置。
- 不改变原有 Python/Conda 环境。
- 不替换系统默认 Node.js，也不切换现有服务的 Java。
- 不使用已有 RAGFlow 的数据库作为 HertzBeat 元数据库。
- 新建独立 Supervisor 配置、PID 文件和管理套接字。
- 对比已有进程，确认其 PID 在部署与验证期间保持一致。

检查已有进程只是一种旁证，不等同于对原有服务做了完整业务验收；本次没有发送模型推理请求去额外消耗它的 GPU 资源。

## 8. 下载与验证源码

### 8.1 最初尝试 GitHub 固定 tag

最初尝试的方式是：

```bash
git clone --depth 1 --branch v1.9.0 \
  https://github.com/apache/hertzbeat.git \
  /root/siton-data-zyh/hertzbeat-native/source/hertzbeat
```

这次 Git 拉取持续较慢，实际环境中访问 `raw.githubusercontent.com` 还出现过连接被重置。没有把这些网络现象当成项目源码错误。

### 8.2 切换到 Apache 官方源码压缩包

最终采用的是：

```text
https://dlcdn.apache.org/hertzbeat/1.9.0/apache-hertzbeat-1.9.0-src.tar.gz
https://downloads.apache.org/hertzbeat/1.9.0/apache-hertzbeat-1.9.0-src.tar.gz.sha512
```

下载位置：

```text
/opt/hertzbeat-native/downloads/
```

来源是官方源码发布包，**不是服务端二进制包**。源码压缩包下载时约 2.8 MB。

示例命令对应当时的操作：

```bash
cd /opt/hertzbeat-native/downloads

curl -fL --retry 2 --connect-timeout 10 --max-time 180 -sS \
  https://dlcdn.apache.org/hertzbeat/1.9.0/apache-hertzbeat-1.9.0-src.tar.gz \
  -o apache-hertzbeat-1.9.0-src.tar.gz

curl -fL --retry 2 --connect-timeout 10 --max-time 60 -sS \
  https://downloads.apache.org/hertzbeat/1.9.0/apache-hertzbeat-1.9.0-src.tar.gz.sha512 \
  -o apache-hertzbeat-1.9.0-src.tar.gz.sha512
```

### 8.3 校验与解压

实际使用 Python 读取官方 SHA512 文件，提取 128 位十六进制摘要，再与源码包计算结果比较。只有比较一致才解压。

解压前还检查了归档成员名称，拒绝绝对路径和包含 `..` 路径段的成员。

最终源码目录为：

```text
/root/siton-data-zyh/hertzbeat-native/source/apache-hertzbeat-1.9.0-src
```

本次完成了 SHA512 比对，**没有单独完成 GPG 签名验证**，不把两者混为一谈。

### 8.4 中止无效拉取时怎样避免影响其他进程

中止 GitHub 拉取前，核对了该进程命令行，确认它是这次任务创建的 HertzBeat clone，并只终止它及其子进程。

没有使用针对整台服务器的宽泛进程匹配去停止 Java、Python 或现有服务。

## 9. 建立源码版本管理

### 9.1 为什么解压后又执行 Git 初始化

官方源码发布包不等于一个包含完整 Git 历史的 clone。为了方便后续二次开发追踪修改，在解压目录初始化了本地 Git 仓库：

```bash
cd /opt/hertzbeat-native/source
git init
git checkout -b codex/hertzbeat-native
git add .
```

之后提交了：

1. 已校验的官方源码基线。
2. 本地构建产物的忽略规则。

提交身份是命令级别设置，没有修改全局 Git 用户配置。

### 9.2 添加的忽略规则

```gitignore
**/target/
**/node_modules/
web-app/.angular/
web-app/dist/
/dist/
.idea/
.vscode/
*.log
```

没有把数据库、真实凭据或依赖缓存放进源码仓库。

### 9.3 一个容易困惑的版本号

本次官方 `1.9.0` 源码包的实际配置中：

```text
hzb.version = 1.9.0
Maven project.version = 2.0-SNAPSHOT
Java requirement = 25+
Spring Boot parent = 4.0.3
```

这些是本次取得并实际构建的源码内容，没有为了让日志“看起来一致”而改版本号。

因此，日志中的 `Building ... 2.0-SNAPSHOT` 与生成的 `apache-hertzbeat-1.9.0.jar` 同时出现，不是本次误下载了两个程序。

后续如果要恢复完整上游 Git 历史或切换发行版本，应单独制定代码同步方案，不要直接对这个发布包导入仓库执行强制覆盖。

## 10. 安装和配置开发工具

### 10.1 最终工具版本

| 工具 | 实际版本 | 来源与使用方式 |
|---|---|---|
| JDK | Amazon Corretto 25.0.4.1 | Corretto 官方 Linux x64 包，私有目录 |
| Maven | 3.9.16 | 明确版本工具包，私有目录 |
| Node.js | 22.23.1 | 复用已有 `/usr/bin/node` |
| pnpm | 10.34.7 | 项目私有 npm prefix |

### 10.2 JDK：独立安装 Amazon Corretto 25

JDK 安装在项目自己的目录，而不是覆盖现有全局 Java：

```text
/opt/hertzbeat-native/tools/amazon-corretto-25.0.4.10.1-linux-x64
/opt/hertzbeat-native/tools/jdk -> 上述目录
```

最初尝试访问 Adoptium 元数据接口时收到 403，最终使用 Amazon Corretto 的官方 Linux x64 JDK 下载地址：

```text
https://corretto.aws/downloads/latest/amazon-corretto-25-x64-linux-jdk.tar.gz
https://corretto.aws/downloads/latest_sha256/amazon-corretto-25-x64-linux-jdk.tar.gz
```

下载后：

1. 计算归档 SHA256。
2. 与官方校验值比较。
3. 检查归档路径。
4. 解压到项目工具目录。
5. 建立 `tools/jdk` 链接。
6. 执行私有 JDK 的 `java -version`。

`latest` 地址会随时间变化。附录中的校验值是**本次实际下载文件**的校验值，不应拿来要求未来的 `latest` 文件也必须相同。

### 10.3 Maven：独立安装 3.9.16

安装位置：

```text
/opt/hertzbeat-native/tools/apache-maven-3.9.16
/opt/hertzbeat-native/tools/maven -> 上述目录
```

工具包从 Maven Central 对应版本路径取得，并比较了官方 SHA512。

选择明确版本，有利于后续重复构建。没有通过全局包升级去影响原有服务。

### 10.4 Node.js：复用已存在的版本

Node.js 当时已经存在：

```text
/usr/bin/node
v22.23.1
```

没有重新覆盖它。前端已在这个版本上实际构建成功。

这不是说任意 Node.js 版本都适用，也不是仅凭版本号就保证兼容；依据是本次锁文件安装和构建的真实结果。

### 10.5 pnpm：安装在项目私有 prefix

当时执行：

```bash
npm install --prefix /opt/hertzbeat-native/tools/pnpm \
  'pnpm@10' --no-audit --no-fund
```

实际解析并安装到的版本是 `10.34.7`。后续如果要精确重现，应固定为同一版本，而不是一直追随 `pnpm@10` 的最新补丁版本。

pnpm 命令入口：

```text
/opt/hertzbeat-native/tools/pnpm/node_modules/.bin/pnpm
```

没有使用 `npm install -g` 给整台服务器更换全局 pnpm。

## 11. 项目级环境变量与依赖缓存

### 11.1 环境入口

统一环境脚本：

```text
/opt/hertzbeat-native/env.sh
```

需要编译时执行：

```bash
source /opt/hertzbeat-native/env.sh
```

环境只影响当前 Shell 和它启动的子进程，没有改写整个服务器的登录配置，也没有修改现有 RAGFlow/Qwen 进程已经获得的环境变量。

### 11.2 实际参数的含义

| 配置 | 含义 |
|---|---|
| `JAVA_HOME` | 指向 HertzBeat 私有 JDK |
| `PATH` | 当前 Shell 优先使用私有 Java、Maven、pnpm |
| `MAVEN_OPTS=-Xms256m -Xmx2048m ...` | 控制 Maven 本身的 JVM |
| `NODE_OPTIONS=--max-old-space-size=4096` | 控制前端构建的 V8 old space |
| `-Dmaven.repo.local=...` | 使用项目自己的依赖仓库 |
| pnpm store / virtual-store | 将大量依赖文件放在本地工具盘缓存目录 |

Maven 缓存不是业务数据库，pnpm store 也不是监控历史数据。二者丢失后可以重新下载，不应与必须备份的数据库和密钥混淆。

### 11.3 Maven 下载加速

最初通过 Maven Central 下载依赖较慢，后来增加了：

```text
/opt/hertzbeat-native/config/maven-settings.xml
```

只对 `central` 配置了项目级镜像：

```text
https://maven.aliyun.com/repository/central
```

构建命令通过 `-s` 显式引用这个文件，没有修改全局的 Maven 配置。

这是依赖下载源设置，不是模型服务代理，也不影响原有 Python 服务。

## 12. 构建前端

### 12.1 前端在哪里

```text
/opt/hertzbeat-native/source/web-app
```

HertzBeat 前端是 Angular，而不是之前参考的 RAG 项目的 Vue。

### 12.2 安装依赖

本次依赖安装的关键参数：

```bash
pnpm install --frozen-lockfile \
  --store-dir /opt/hertzbeat-native/cache/pnpm-store \
  --virtual-store-dir /opt/hertzbeat-native/cache/pnpm-virtual-store \
  --network-concurrency 8
```

- `--frozen-lockfile`：按已有锁文件安装，不随意重写依赖解析。
- `--store-dir`：指定包内容缓存。
- `--virtual-store-dir`：指定实际依赖存放布局。
- `--network-concurrency 8`：限制下载并发，避免无限放大请求量。

没有手工逐个下载前端组件，而是由 pnpm 解析和安装依赖。

### 12.3 生成生产静态资源

执行：

```bash
pnpm exec ng build --configuration production
```

输出目录：

```text
/opt/hertzbeat-native/source/web-app/dist
```

本次确实生成了 `index.html`、带内容哈希的 JavaScript、CSS 等资源。

### 12.4 实际结果及告警

- 前端构建成功，记录了 `FRONTEND_BUILD_SUCCESS`。
- Angular 构建部分耗时约 89.7 秒；依赖安装另计，不应把这个数值当成从零部署总耗时。
- 初始 bundle 约 3.13 MB，超过原有 2 MB 预算，输出的是警告。
- Less loader 对部分依赖路径输出了警告，提示后续可能影响 watch/cache。
- pnpm 对部分依赖安装脚本给出了忽略提示；本次没有全量放开所有脚本，而是在当前安装结果上完成了真实构建。

这些告警没有被写成“完全没有任何问题”，也没有在本次基础部署中顺手重构上游前端。

## 13. 构建后端

### 13.1 不是只运行一个 Java 文件

后端是多模块 Maven 工程。构建 `hertzbeat-startup` 时，还需要它依赖的公共模块、仓储模块、采集模块、管理模块等。

本次构建共覆盖 24 个 Reactor 模块。

### 13.2 关键构建命令

实际脚本中使用了类似以下命令，完整版本见附录：

```bash
mvn -s /opt/hertzbeat-native/config/maven-settings.xml \
  -B -ntp -T 2 \
  -Daether.artifactResolver.threads=12 \
  -Dmaven.repo.local=/opt/hertzbeat-native/cache/maven \
  -Dmaven.test.skip=true \
  -Dcheckstyle.skip=true \
  -Djacoco.skip=true \
  -pl hertzbeat-startup -am install
```

| 参数 | 作用 |
|---|---|
| `-pl hertzbeat-startup` | 选择启动模块 |
| `-am` | 一并构建所需的其他模块 |
| `install` | 把构建产物安装到指定 Maven 本地仓库，不是安装操作系统软件 |
| `-T 2` | 使用两个 Reactor 构建线程 |
| `-B -ntp` | 适合日志记录的批处理输出 |
| `maven.test.skip=true` | 跳过测试编译及执行 |
| `checkstyle.skip=true` | 本次构建不执行完整代码风格检查 |
| `jacoco.skip=true` | 不运行覆盖率流程 |

**构建成功不等于完整测试通过。**本次验收采用了后面的运行冒烟、真实采集、历史查询和重启恢复检查。

### 13.3 为什么要求 JDK 25

源码的 Maven Enforcer 在 `validate` 阶段要求 Java 25 或更高版本。不应仅因为其他 Java 项目能用 8、11、17、21，就认为这个源码包也一样。

本次确认该规则通过后，才继续编译。

### 13.4 实际构建产物

启动模块生成：

```text
/opt/hertzbeat-native/source/hertzbeat-startup/target/apache-hertzbeat-1.9.0.jar
```

其他模块产物进入各自的 `target` 和项目 Maven 仓库。

本次后端最终记录了 `BUILD SUCCESS` 和 `BACKEND_BUILD_SUCCESS`。切换镜像后的成功构建日志显示约 3 分 28 秒；之前的网络尝试和依赖准备时间另外计算。

## 14. 打包完整服务端程序

### 14.1 为什么还有一个打包步骤

仅有启动模块 JAR 不足以表达完整部署，还需要：

- 依赖 JAR。
- 已构建好的前端静态资源。
- 配置模板。
- 监控模板。
- 启动脚本、许可证等随包文件。

所以在后端构建成功、前端 `dist/index.html` 存在后，执行启动模块的 `release` profile。

### 14.2 实际打包方式

```bash
mvn -s /opt/hertzbeat-native/config/maven-settings.xml \
  -B -ntp \
  -Dmaven.repo.local=/opt/hertzbeat-native/cache/maven \
  -Dmaven.test.skip=true \
  -Dcheckstyle.skip=true \
  -Djacoco.skip=true \
  -pl hertzbeat-startup -Prelease package
```

关键发布包：

```text
/opt/hertzbeat-native/source/dist/apache-hertzbeat-1.9.0-bin.tar.gz
```

本次打包记录为成功，成功阶段约 5 分 31 秒。

### 14.3 打包与发布是两个动作

- **打包**：产生新的压缩包。
- **发布**：解压到明确的运行目录、接入配置和数据目录、切换运行入口。

即使以后重新运行 `package-server.sh`，也不意味着当前运行中的 Java 进程已自动使用新代码。

## 15. 创建独立运行账户

### 15.1 为什么不是一直以 root 跑 Java

部署操作需要管理目录和工具，但长期服务运行不必继续使用 root。为 HertzBeat 新建了系统账户：

```bash
useradd --system \
  --home-dir /opt/hertzbeat-native \
  --shell /usr/sbin/nologin \
  hertzbeat-svc
```

Supervisor 管理进程使用 root，实际 Java 子进程使用 `hertzbeat-svc`。

### 15.2 目录遍历权限

数据目录位于 `/root` 下面。即使子目录本身可读，服务用户如果没有父目录的执行权限，也无法走到这个路径。

对 `/root` 增加了服务账户所需的最小目录遍历权限。对 NFS 挂载目录执行 ACL 操作时，出现 `Operation not supported`；检查发现该挂载根已有 POSIX `755` 权限，足以遍历，所以没有把它改成全员可写。

验证方式包括：

```bash
runuser -u hertzbeat-svc -- \
  test -x /root/siton-data-zyh/hertzbeat-native/data
```

### 15.3 重要权限分工

- 数据子目录、应用日志子目录：服务用户需要写入。
- 程序和工具目录：不因为运行 Java 就全部交给服务用户修改。
- Supervisor 套接字所在目录：由 root 管理。
- 临时目录：另建服务用户可写的 `run/tmp`。
- 管理员密码文件和完整凭据文件：仅 root 可读。

附录提供了本次复核时的具体权限表。

## 16. 配置数据库、历史存储和运行参数

### 16.1 当前生效文件

```text
/opt/hertzbeat-native/config/application.yml
```

它基于本次同版本源码的配置模板生成，不是从另一个版本随意拼接而来。

### 16.2 配置摘录

下面只展示关键设置的含义，真实文件保留上游的其他必要内容，并且包含多个 YAML 文档/环境段。**不要把这份摘录整段覆盖到真实配置文件。**

```yaml
server:
  address: 127.0.0.1
  port: 1157

spring:
  profiles:
    active: prod
  datasource:
    driver-class-name: org.h2.Driver
    username: sa
    password: TOKEN  # 单独生成的数据库密码
    url: jdbc:h2:/root/siton-data-zyh/hertzbeat-native/data/metadata/hertzbeat;MODE=MYSQL

common:
  secret: ENCRYPT_KEY  # 独立生成的 AES 密钥
  queue:
    type: memory

warehouse:
  store:
    duckdb:
      enabled: true
      expire-time: 90d
      store-path: /root/siton-data-zyh/hertzbeat-native/data/history/history.duckdb
  real-time:
    memory:
      enabled: true

scheduler:
  server:
    enabled: false
    port: 1158
```

`TOKEN` 在不同位置代表不同的独立凭据，不应把管理员密码、数据库密码和 JWT 密钥设置为同一个值。

### 16.3 H2、DuckDB、实时内存分别保存什么

| 存储 | 本次用途 | 重启后的特征 |
|---|---|---|
| H2 | 监控对象、配置等元数据 | 文件保留，已验证恢复 |
| DuckDB | 历史指标 | 文件保留，已查回重启前数据 |
| 内存实时存储 | 最近的实时指标 | 进程重启后需要重新采集，不应当作持久历史库 |
| 内存队列 | 进程内部数据流转 | 不承诺进程崩溃后的队列持久化 |

### 16.4 为什么 1158 没有监听

本次是单机基础部署，关闭了外部采集器的通信服务，不代表关闭全部采集。

HertzBeat 自带的本机采集器仍然运行，并已通过真实 HTTP 自检证明可以调度和采集。

以后启用外部采集器时，应同时评估监听地址、端口、认证和网络规则，而不是只把一个布尔值改为 `true`。

### 16.5 对 NFS 文件数据库的边界说明

本次已经验证在当前挂载环境下，单实例可以写入 H2、DuckDB 并在服务重启后恢复。但没有做：

- NFS 服务中断及重连测试。
- 多个 Java 实例同时写入相同数据库文件的测试。
- 长期大规模时序写入或存储容灾测试。

因此，不要启动第二个实例同时指向这些文件，也不要把这次单机验证写成“已具备数据库高可用”。

## 17. 生成和保护账号、密码、密钥

### 17.1 本次生成了哪些值

首次配置生成脚本使用 Python `secrets` 随机生成：

- 管理员密码。
- H2 数据库密码。
- JWT 签名密钥。
- AES 加密密钥。

没有继续使用默认管理员密码，也没有复用 SSH 密码。

### 17.2 保存在哪里

| 文件 | 用途 | 权限 |
|---|---|---|
| `/opt/hertzbeat-native/config/admin-login.txt` | 只保存管理员登录信息 | root，`600` |
| `/opt/hertzbeat-native/config/credentials.json` | 初始化及验证所需的完整凭据和密钥 | root，`600` |
| `/opt/hertzbeat-native/config/application.yml` | Java 必须读取的运行配置 | root:`hertzbeat-svc`，`640` |
| `/opt/hertzbeat-native/config/sureness.yml` | Java 必须读取的账户及权限配置 | root:`hertzbeat-svc`，`640` |

在服务器上以 root 查看登录信息：

```bash
cat /opt/hertzbeat-native/config/admin-login.txt
```

这条命令会显示真实密码，不应把输出随意贴进聊天、公开工单或 Git 仓库。

### 17.3 为什么密钥需要备份

数据库里可能存在使用 AES 密钥加密的监控凭据。只保留数据库、丢失原密钥，并不一定能完整恢复这些内容。

因此，配置备份与数据备份都重要。也不要为了“重新初始化”随意删除 `credentials.json` 后生成一套新密钥，再继续使用旧数据库。

## 18. 部署构建产物与目录链接

### 18.1 实际运行发布目录

自行构建的服务端包解压到了：

```text
/opt/hertzbeat-native/releases/apache-hertzbeat-1.9.0-bin
```

运行入口：

```text
/opt/hertzbeat-native/current
```

### 18.2 发布目录中怎样接入配置和数据

首次发布时进行了以下处理：

1. 检查归档成员路径后解压。
2. 拒绝直接覆盖已经存在的同名发布目录。
3. 将原始 `config` 改名保存为 `config.upstream`。
4. 将当前 `config` 链接到独立配置目录。
5. 将 `data`、`logs` 链接到指定的数据卷位置。
6. 建立 `current` 链接。

这使得源码、当前运行包、运行配置和业务数据各有位置。

### 18.3 为什么源码改动不会立即生效

服务执行的是 `current` 中的 JAR 和依赖，不是直接解释运行源码。

修改 Java 代码后，要重新编译和打包，再明确发布新产物；修改 Angular 代码后，要重新构建并发布静态资源，或者在开发阶段使用独立开发服务器。

## 19. 配置进程管理与启动命令

### 19.1 为什么使用独立 Supervisor

可见环境已有 Supervisor，但本次没有把 HertzBeat 塞进 RAGFlow 的进程配置。

单独创建：

```text
/opt/hertzbeat-native/config/supervisord.conf
/opt/hertzbeat-native/run/supervisor.sock
/opt/hertzbeat-native/run/supervisord.pid
```

这样停止 HertzBeat，不会因为管理命令指向错误而把原有服务一起停掉。

### 19.2 Java 启动参数

实际启动脚本是：

```text
/opt/hertzbeat-native/bin/run-server.sh
```

关键参数包括：

| 参数 | 作用 |
|---|---|
| `-Xms256m -Xmx2048m` | Java 初始堆、最大堆 |
| `-XX:ActiveProcessorCount=4` | 控制 JVM 看到的处理器数量 |
| `-XX:MaxDirectMemorySize=512m` | 直接内存上限 |
| `--enable-native-access=ALL-UNNAMED` | 允许相关 classpath 原生库使用所需能力 |
| `--add-opens=java.base/java.nio=ALL-UNNAMED` | 满足当前 Arrow 等 classpath 依赖访问需求 |
| `-Djava.io.tmpdir=.../run/tmp` | 服务专用临时目录 |
| `-Duser.timezone=Asia/Shanghai` | JVM 时区 |
| `-Dfile.encoding=UTF-8` | 文件编码 |
| `-Dspring.config.location=.../config/` | 指定当前生效配置 |
| `-Dlogging.config=.../logback-spring.xml` | 指定日志配置 |

脚本最终 `exec` Java 前台进程，由 Supervisor 负责后台管理，而不是在 Java 启动脚本内部再无限套 `nohup`。

### 19.3 Supervisor 的实际策略

- Java 子进程用户：`hertzbeat-svc`。
- 工作目录：`/opt/hertzbeat-native/current`。
- `autostart=true`：Supervisor 启动时启动该程序。
- `autorestart=unexpected`：非预期退出时重启。
- `startsecs=20`：进程稳定运行超过 20 秒后标记为 RUNNING。
- `stopwaitsecs=45`：给停止流程留出等待时间。
- `stopasgroup=true`、`killasgroup=true`：按本项目进程组处理停止。
- stdout/stderr 分别写入用户数据卷日志目录，并配置轮转。

进程管理器显示 RUNNING 只是一个条件，**不等于网页、登录和数据库就一定健康**，所以后面继续做了 HTTP 和功能验证。

### 19.4 退出 SSH 与机器重启的区别

Supervisor 已 daemonize，父进程为 PID 1，不依赖开发 SSH 会话存活。此前断开部署 SSH 后重新连接，也验证过服务仍然运行。

但这与“宿主机重启或容器重建后自动启动”不同。本次没有接管服务器平台的启动流程，也没有配置 systemd 或平台开机钩子。

## 20. 验证网页、认证和基础接口

### 20.1 使用的验证脚本

```bash
python3 /opt/hertzbeat-native/bin/smoke-test.py
```

它只在验证时读取 root 专用凭据文件，不把真实密码和签发令牌打印到报告里。

### 20.2 实际检查项目

| 检查 | 实际判定 |
|---|---|
| `GET /` | HTTP 200，并返回 HTML |
| HTML 引用的 CSS/JS | HTTP 200，响应不是伪装成资源的 HTML |
| `POST /api/account/auth/form` | 登录成功，业务码 0，签发 token |
| `GET /api/apps/hierarchy` | 目录接口成功 |
| `GET /api/monitors` | 认证后可查询 |
| 不带认证查询监控接口 | HTTP 401 |
| `GET /actuator/health` | 认证后返回 UP |
| 元数据库文件 | 在指定目录存在 |
| 历史库文件 | 在指定目录存在 |

本次核对的是 HTTP、资源、接口与功能，不把它等同于完整浏览器视觉验收或所有页面操作验收。

### 20.3 不是所有“HTTP 200”都代表成功

HertzBeat 的接口还包含业务码，所以验证同时检查了 HTTP 状态和 JSON 中的业务码。

登录报告只保存 `token_issued: true`，没有把真实 token 持久化到本文或测试摘要。

## 21. 验证真实采集、历史数据和重启恢复

### 21.1 创建的自检监控

| 项目 | 值 |
|---|---|
| 名称 | `hertzbeat-native-selfcheck` |
| 类型 | `website` |
| 目标 | `http://127.0.0.1:1157/` |
| 周期 | 30 秒 |
| 调度方式 | `interval` |
| 用途标签 | `purpose=deployment-selfcheck` |
| 监控 ID | `696820437611776` |

这个监控只访问 HertzBeat 自己的 HTTP 页面，不请求现有 Qwen 推理，也不对 RAGFlow 做业务变更。

### 21.2 为什么这属于真实采集

Collector 确实向本机 HTTP 服务发送请求，取得真实响应时间，然后通过实时指标接口读取出来。

验证接口包括：

```text
POST /api/monitor
GET  /api/monitors?search=hertzbeat-native-selfcheck&pageSize=20
GET  /api/monitor/696820437611776
GET  /api/monitor/696820437611776/metrics/summary
```

测试时监控状态为 `1`，即正常状态；`summary.responseTime` 出现了实际毫秒值，例如初次测试读取到 6 ms。

单个毫秒值只是某次采集结果，不是服务器性能保证或延迟 SLA。

### 21.3 真实数据与空字段如何区分

本次以状态、实际采样时间、响应时间值、历史数据点作为验证依据，不仅判断返回对象是否存在。

HTTP 头部指标中的部分字段曾返回 null，不应把这些空值写成已经测得对应响应头数据。它不影响此次对响应时间采集链路的验证，但该模板细节仍可在后续业务测试中继续核查。

### 21.4 重启后怎样确认恢复

执行的停止、启动只针对 HertzBeat：

```bash
/opt/hertzbeat-native/bin/hertzbeatctl restart hertzbeat
```

重启后重新查询，确认：

1. 监控 ID 仍为 `696820437611776`。
2. 监控配置恢复，而非另建一个同名对象。
3. 内置采集器恢复执行。
4. 重新出现真实实时指标。
5. 登录、网页和健康检查仍然通过。

### 21.5 历史数据验证

使用了类似以下查询：

```text
GET /api/monitor/127.0.0.1%3A1157/metric/website.summary.responseTime?history=1h
```

业务码为 0，测试时返回了 5 个历史数据点，包括重启前的数据。

这比“看到数据库文件存在”更进一步，证明了当前历史采集、写入、读取和重启后的保留链路。

### 21.6 数据库迁移恢复证据

首次启动日志显示应用执行了 6 个迁移，元数据 schema 到达 `v190`。

重启日志显示：

```text
Current version of schema "PUBLIC": 190
Schema "PUBLIC" is up to date. No migration necessary.
```

没有因为重启而重新创建一个空元数据库。

### 21.7 自检监控是否保留

已保留这个每 30 秒执行一次的自检监控，方便打开平台后直接看到一个真实监控对象。

后续如果删除它，应在 HertzBeat 界面中确认对象名称后操作，或者使用精确的监控 ID。不要使用无条件批量删除。

## 22. 日常运维速查

以下命令在 Linux 服务器上执行。

### 22.1 查看状态

```bash
/opt/hertzbeat-native/bin/hertzbeatctl status
```

### 22.2 启动

如果需要连独立 Supervisor 一起启动：

```bash
/opt/hertzbeat-native/bin/start.sh
```

如果 Supervisor 已运行，只是 Java 服务处于停止状态：

```bash
/opt/hertzbeat-native/bin/hertzbeatctl start hertzbeat
```

### 22.3 停止、重启

```bash
/opt/hertzbeat-native/bin/hertzbeatctl stop hertzbeat
/opt/hertzbeat-native/bin/hertzbeatctl restart hertzbeat
```

管理命令明确指向本项目的 Supervisor 配置，不操作 RAGFlow 的 Supervisor。

### 22.4 查看日志

```bash
tail -n 100 /root/siton-data-zyh/hertzbeat-native/logs/runtime/stdout.log
tail -n 100 /root/siton-data-zyh/hertzbeat-native/logs/runtime/stderr.log
tail -n 80 /root/siton-data-zyh/hertzbeat-native/logs/supervisord.log
```

### 22.5 健康冒烟及自检

```bash
python3 /opt/hertzbeat-native/bin/smoke-test.py
python3 /opt/hertzbeat-native/bin/selfcheck-monitor.py
```

第二个脚本会按固定名称复用已有自检监控；监控不存在时会创建，并非纯只读检查。执行前应知道它的这一行为。

### 22.6 查看工具环境

```bash
source /opt/hertzbeat-native/env.sh
java -version
mvn -version
node --version
pnpm --version
```

## 23. 本地浏览器访问服务器页面

### 23.1 为什么直接输入本机地址可能打不开

`127.0.0.1:1157` 是**服务器自己的回环地址**，不是自动指向你 Windows 电脑。

当前部署没有为了打开网页去修改防火墙或直接开放服务端口，采用 SSH 转发访问。

### 23.2 在 Windows 建立转发

在 Windows PowerShell 中执行：

```powershell
ssh -N -p PORT `
  -L 127.0.0.1:1157:127.0.0.1:1157 `
  root@HOST
```

将 `HOST` 换成你的服务器地址，`PORT` 换成本次的 SSH 端口 `20289`。

保持这个窗口打开，再访问：

[本地转发后的 HertzBeat 页面](http://127.0.0.1:1157/)

`-N` 表示只做转发，不在远端执行交互命令。

### 23.3 本地 1157 已被占用时

可以只改左侧本地端口，例如：

```powershell
ssh -N -p PORT `
  -L 127.0.0.1:21157:127.0.0.1:1157 `
  root@HOST
```

然后访问：

[使用替代本地端口的页面](http://127.0.0.1:21157/)

服务器仍然运行在 1157，无须因此去修改应用配置。

### 23.4 登录信息

通过另一个 SSH 终端在服务器读取：

```bash
cat /opt/hertzbeat-native/config/admin-login.txt
```

不要把 root 的 SSH 登录密码当成 HertzBeat 管理员密码。

## 24. 后续二次开发与重新发布

### 24.1 进入源码目录

```bash
source /opt/hertzbeat-native/env.sh
cd /opt/hertzbeat-native/source
git status
```

当前分支是 `codex/hertzbeat-native`。

### 24.2 修改前后端分别在哪里

| 内容 | 位置 |
|---|---|
| Angular 前端 | `/opt/hertzbeat-native/source/web-app` |
| Java 管理与业务代码 | `/opt/hertzbeat-native/source/hertzbeat-manager` |
| 启动模块 | `/opt/hertzbeat-native/source/hertzbeat-startup` |
| 采集模块 | `/opt/hertzbeat-native/source/hertzbeat-collector` |
| 历史及实时存储 | `/opt/hertzbeat-native/source/hertzbeat-warehouse` |
| 上游自带 AI 模块 | `/opt/hertzbeat-native/source/hertzbeat-ai` |

### 24.3 前端开发服务器

```bash
/opt/hertzbeat-native/bin/dev-frontend.sh
```

该脚本在回环地址 4200 启动 Angular 开发服务器，适用于前端修改和调试。需要另外转发 4200，生产静态资源模式不依赖它持续运行。

### 24.4 构建顺序

```bash
bash /opt/hertzbeat-native/bin/build-backend.sh
bash /opt/hertzbeat-native/bin/build-frontend.sh
bash /opt/hertzbeat-native/bin/package-server.sh
```

每一步都要检查本次的退出码和输出，不应只在旧日志里搜索一个历史 `SUCCESS` 就宣称新代码构建成功。

当前辅助打包脚本带有首次部署时的就绪等待逻辑，它不是一套完整 CI/CD 系统。以后自动化发布时，建议改为明确的构建批次、退出码、产物摘要和发布清单。

### 24.5 重新发布的原则

这是后续建议，**本次没有为新业务代码执行过升级发布**：

1. 提交或备份源码修改。
2. 构建并确认新产物成功。
3. 备份当前配置和数据库，尤其在涉及 schema 迁移时。
4. 解压到新的、带版本或批次标识的发布目录。
5. 接入相同的配置和数据目录，核对兼容性。
6. 停止旧实例，确认没有第二个实例同时写同一套文件数据库。
7. 切换 `current`，启动并执行冒烟。
8. 如果升级已迁移数据库，回滚程序前先确认数据库向后兼容；切回链接本身不等于完整回滚。

当前首次部署脚本会拒绝覆盖现有发布目录，不应为了省事去删除这一保护。

## 25. 数据、配置备份与恢复边界

### 25.1 已经生成的备份

| 文件 | 含义 |
|---|---|
| `config-bootstrap-20261021.tar.gz` | 首次部署配置、脚本等记录，后续补充了说明 |
| `data-bootstrap-20261021.tar.gz` | 首次停止 HertzBeat 后创建的离线数据快照 |
| `config-verified-20261022.tar.gz` | 后续功能验证阶段的配置及脚本备份 |

这些文件位于：

```text
/root/siton-data-zyh/hertzbeat-native/backups
```

备份目录为 root `700`，备份文件为 root `600`，因为配置归档内含真实凭据和加密密钥。

### 25.2 不要误解备份的新旧程度

- 配置备份不等于数据库备份。
- `data-bootstrap-20261021.tar.gz` 是最初的启动快照，早于后来创建的自检监控。
- 不应把这个 bootstrap 快照说成“当前所有数据的最新全量备份”。
- 当前最新数据仍持续写在实际数据目录中。

### 25.3 后续备份建议

文件数据库需要考虑一致性。后续可以在停止 HertzBeat 后备份，或采用经过验证的数据库备份机制，不要直接把随时拷贝正在写入的文件称作一致性备份。

源码、配置、密钥、数据库和版本清单应一并纳入恢复方案。可重建的 Maven/pnpm 缓存不是最优先的备份对象。

## 26. 实际遇到的问题与处理过程

| 现象 | 判断与处理 | 是否改了 HertzBeat 业务源码 |
|---|---|---|
| GitHub clone 较慢 | 换官方源码发布包，校验后使用；仅停止本次 clone | 否 |
| raw GitHub 地址连接被重置 | 识别为网络问题，不据此判断项目坏了 | 否 |
| Adoptium 元数据接口 403 | 使用 Corretto 官方下载，验证 SHA256 | 否 |
| Maven 下载较慢 | 使用项目级 Maven Central 镜像，保留独立缓存 | 否 |
| NFS 设置 ACL 返回不支持 | 检查已有 POSIX 权限并验证服务用户实际访问 | 否 |
| 源码包没有完整 Git 历史 | 本地初始化、保存源码基线和构建忽略规则 | 只添加 `.gitignore` |
| 以为 `/api/apps` 是目录查询入口而得到 404 | 核对源码，改测 `/api/apps/hierarchy` | 否，是验证脚本路径问题 |
| 一个验证输出文件带前置进度行，不应作为纯 JSON 解析 | 使用规范 JSON 报告文件，并把进度改到 stderr | 否，是自检脚本输出格式问题 |
| PowerShell/Bash 的变量及引号相互干扰 | 改用明确的远程 Shell 和受控脚本传输 | 否 |
| 通过终端写中文或超长单行脚本失败 | 将文本转成分段 ASCII 转义，再在服务器写 UTF-8 | 否 |
| Arrow 命名模块告警 | 启动参数改为当前 classpath 所需的 `ALL-UNNAMED` | 否，只改启动脚本 |
| Angular bundle、Less 路径警告 | 记录为警告，确认真实构建成功 | 否 |
| Logback/Unsafe 等弃用警告 | 记录为兼容性提示，没有写成“日志完全无警告” | 否 |

### 26.1 进程管理器中的一个 CRIT 日志

Supervisor 日志中出现过：

```text
Server 'unix_http_server' running without any HTTP authentication checking
```

这次使用的是本地 Unix socket，而不是对外开放的 TCP 管理端口。套接字配置为 `0700`，管理目录也受权限限制，因此应结合部署方式理解此日志。

它不代表 HertzBeat 网页没有认证。如果以后把 Supervisor 改成 TCP 服务，必须重新评估认证和网络访问限制。

### 26.2 停止时看到 143 是否就是崩溃

两次受控停止的 Supervisor 日志均记录了 `exit status 143`，对应 SIGTERM 的常见退出表示；它们发生在明确发出的 stop/restart 操作之后。

日志显示大约等待十秒左右后停止，没有证据表明本次使用了超时后的 SIGKILL。

不应只摘出 `143`，不看前后的人工停止记录，就判定服务自动崩溃。

### 26.3 哪些工具最终没有成为依赖

部署控制端曾尝试临时准备 Paramiko 辅助会话，下载较慢后中止。最终操作使用的是 Windows OpenSSH。

Paramiko 不是 HertzBeat 服务运行依赖，也没有加入现有 Agent 项目的依赖文件。

## 27. 哪些事情已经完成，哪些尚未做

### 27.1 已完成

- 固定官方源码包获取和校验。
- 私有 JDK、Maven、pnpm，以及现有 Node.js 环境确认。
- 前后端构建、发布包构建与部署。
- 独立账户、目录权限、配置和进程管理。
- 指定数据卷上的元数据与历史存储。
- 网页、认证、基础 API、实时及历史采集、重启恢复验证。
- 初始备份、脚本、部署清单和操作说明。

### 27.2 未完成，不应混淆

- 未执行完整单元测试和所有采集协议测试。
- 未完成全部页面的浏览器交互、视觉及兼容性验收。
- 未完成高负载、长时间稳定性、NFS 故障恢复或高可用验证。
- 未配置外部时序数据库、集群采集器和开机自启。
- 未把现有 Agent 的用户、会话、指标目录、证据报告接到 HertzBeat。
- 未将现有 Qwen 配置成 HertzBeat 内置 AI 的模型提供者。

“已经具备源码开发和正常单机运行基础”不等于“全部生产化工作完成”。

## 28. 排查问题的推荐顺序

### 28.1 页面打不开

依次确认：

1. 服务器上的 Supervisor 状态。
2. 服务器内 `127.0.0.1:1157` 是否返回页面。
3. 本地 SSH 转发终端是否还开着。
4. 本地端口有没有冲突。
5. 浏览器访问的是本地转发端口，而不是误把服务器回环地址当作远程公网入口。

### 28.2 服务显示 RUNNING，但接口不正常

继续查看：

- Java stdout、stderr。
- 健康检查及认证结果。
- H2、DuckDB 文件路径和写入权限。
- 磁盘是否足够。
- 是否有人更换了密钥、数据库密码或错误的配置版本。

不建议直接重复运行初始化脚本去覆盖配置。

### 28.3 编译时 Java 版本错误

先确认：

```bash
source /opt/hertzbeat-native/env.sh
which java
java -version
mvn -version
```

IDE、远程终端、Maven 可能使用不同的 JDK，不应只看 Windows 本机安装了什么。

### 28.4 前端依赖丢失或换机器

不要复制旧机器的 `node_modules`。在正确版本工具环境下，按锁文件重新安装，并重新确认缓存/virtual store 路径。

### 28.5 重启后实时图表短暂为空

实时存储在内存中，需要等下一次采集。检查监控是否恢复、采集时间是否更新；重启前的历史数据应通过历史接口查询。

### 28.6 怀疑影响了原有服务

对照原有服务的独立配置和进程，避免把所有 Java、Python 进程一起处理。HertzBeat 使用自己的管理脚本，不要拿 RAGFlow 的控制脚本代替。

## 29. 下一阶段接入现有 Agent 的位置

下面是后续方向，不属于本次已部署功能：

```text
HertzBeat Angular 页面
         ↓
Java 新增调查接口、AgentClient
         ↓ HTTP / JSON；需要流式时再设计 SSE
现有 FastAPI Agent
         ↓
SQL / RAG / Report 与证据
```

可以参考之前 RAG 项目用 WebClient 调用 Python 的方式，但还需要独立处理：

- HertzBeat 用户与 Agent 身份/数据权限映射。
- Java 会话与 Agent 会话的对应。
- HertzBeat 指标、告警到现有指标语义层的数据适配。
- 报告、证据、引用、Trace 的展示。
- 超时、重试、幂等和失败状态。

当前 Agent 返回业务 JSON，不是直接兼容任意模型配置入口。只填一个模型 Base URL，并不等于完成业务集成。

## 30. 官方资料与证据位置

### 30.1 官方资料

- [HertzBeat 官方仓库](https://github.com/apache/hertzbeat)
- [HertzBeat 下载说明](https://hertzbeat.apache.org/docs/download/)
- [HertzBeat 快速开始及源码启动说明](https://hertzbeat.apache.org/docs/start/quickstart/)
- [HertzBeat 安装包部署说明](https://hertzbeat.apache.org/docs/start/package-deploy/)
- [HertzBeat 账户和密钥配置](https://hertzbeat.apache.org/docs/start/account-modify/)
- [Maven 官方下载说明](https://maven.apache.org/download.cgi)
- [Amazon Corretto 25 官方下载说明](https://docs.aws.amazon.com/corretto/latest/corretto-25-ug/downloads-list.html)

以上链接用于说明来源与后续查阅。本文中的版本、参数、验证结果以本次服务器实际记录为准，不把网页未来更新后的内容倒推成本次操作。

### 30.2 服务器上的记录

```text
/root/siton-data-zyh/hertzbeat-native/DEPLOYMENT.md
/root/siton-data-zyh/hertzbeat-native/deployment.json
/opt/hertzbeat-native/config/deployment.json
/root/siton-data-zyh/hertzbeat-native/logs/
```

### 30.3 本地只读证据快照

本次写文档时，把不含真实凭据的部署信息、脚本及验证摘要保存到了你的电脑：

```text
D:\Network AIOps\outputs\hertzbeat-deployment-evidence-20261022.json
```

这一步仅查询既有部署信息，没有再次安装依赖、修改远程配置或重启服务。快照没有读取管理员真实密码或完整敏感运行配置。

---

## 31. 附录：实际脚本、校验值与验证摘要

以下附录根据本次只读采集的实际文件生成。包含凭据生成逻辑，但不包含生成后的真实凭据。

### 31.1 只读核对时的状态与已有进程

采集时间：`2026-10-22T00:24:06.726530+08:00`。PID 和 uptime 是这个时点的快照。

```text
hertzbeat                        RUNNING   pid 34630, uptime 0:12:49
```

原有服务进程：

```text
    PID    PPID USER         ELAPSED COMMAND
  27850   20009 ragflow+    06:41:51 python
  30193      56 root        02:55:09 vllm
```

关键监听：

```text
LISTEN  0        2048           127.0.0.1:8000           0.0.0.0:*
LISTEN  0        511            127.0.0.1:18080          0.0.0.0:*
LISTEN  0        100            127.0.0.1:1157           0.0.0.0:*
```


### 31.2 实际工具版本输出

**java**

```text
openjdk version "25.0.4.1" 2026-08-18 LTS
OpenJDK Runtime Environment Corretto-25.0.4.10.1 (build 25.0.4.1+10-LTS)
OpenJDK 64-Bit Server VM Corretto-25.0.4.10.1 (build 25.0.4.1+10-LTS, mixed mode, sharing)
```

**maven**

```text
Apache Maven 3.9.16 (2bdd9fddda4b155ebf8000e807eb73fd829a51d5)
Maven home: /opt/hertzbeat-native/tools/maven
Java version: 25.0.4.1, vendor: Amazon.com Inc., runtime: /opt/hertzbeat-native/tools/amazon-corretto-25.0.4.10.1-linux-x64
Default locale: en_US, platform encoding: UTF-8
OS name: "linux", version: "5.10.0-216.0.0.115.oe2203sp4.x86_64", arch: "amd64", family: "unix"
```

**node**

```text
v22.23.1
```

**pnpm**

```text
10.34.7
```


### 31.3 本次文件校验值

以下对应当时实际下载的文件。JDK 的 latest 地址未来发生变化时，校验值也会变化。

**源码包 SHA512**

```text
143c563971a57d8ce5088f357f9040d0c0615e785dfedd0ac665575ee553d89d1a4beda883f33e4fb23423e6555722685caddc7c00590e945d4b23908ee3541c
```

**JDK 包 SHA256**

```text
a45f1d385da8221fe1225dde5b6afa8e932a6acb93571b55eff4a39a2ebe7378
```

**Maven 包 SHA512**

```text
831a8591fe20c8243b1dbe7d71e3244f31d1665b0804b2e825e38cbbe5ce0cafb8338851f90780735568773e0a6cd07bbec107cda0b896b008b861075358b6f6
```


### 31.4 实际权限表

| 路径 | 属主:属组 | 权限 |
|---|---|---|
| `/opt/hertzbeat-native/config` | `root:hertzbeat-svc` | `0750` |
| `/opt/hertzbeat-native/config/admin-login.txt` | `root:root` | `0600` |
| `/opt/hertzbeat-native/config/credentials.json` | `root:root` | `0600` |
| `/opt/hertzbeat-native/config/application.yml` | `root:hertzbeat-svc` | `0640` |
| `/opt/hertzbeat-native/config/sureness.yml` | `root:hertzbeat-svc` | `0640` |
| `/opt/hertzbeat-native/run` | `root:hertzbeat-svc` | `0750` |
| `/opt/hertzbeat-native/run/tmp` | `hertzbeat-svc:hertzbeat-svc` | `0750` |
| `/root/siton-data-zyh/hertzbeat-native/data` | `hertzbeat-svc:hertzbeat-svc` | `0755` |
| `/root/siton-data-zyh/hertzbeat-native/data/metadata` | `hertzbeat-svc:hertzbeat-svc` | `0755` |
| `/root/siton-data-zyh/hertzbeat-native/data/history` | `hertzbeat-svc:hertzbeat-svc` | `0755` |
| `/root/siton-data-zyh/hertzbeat-native/backups` | `root:root` | `0700` |


### 31.5 环境入口 env.sh

服务器文件：`/opt/hertzbeat-native/env.sh`

```bash
export HERTZBEAT_NATIVE_HOME=/opt/hertzbeat-native
export HERTZBEAT_DATA_HOME=/root/siton-data-zyh/hertzbeat-native
export JAVA_HOME=/opt/hertzbeat-native/tools/jdk
export PATH="$JAVA_HOME/bin:/opt/hertzbeat-native/tools/maven/bin:/opt/hertzbeat-native/tools/pnpm/node_modules/.bin:$PATH"
export MAVEN_OPTS='-Xms256m -Xmx2048m -XX:ActiveProcessorCount=4'
export NODE_OPTIONS='--max-old-space-size=4096'
```


### 31.6 工具安装脚本

服务器文件：`/opt/hertzbeat-native/bin/install-tools.sh`

这是本次安装记录，不是日常启动入口。其中 pnpm@10 和 JDK latest 会随时间变化，复现时需明确版本和校验值。

```bash
#!/usr/bin/env bash
set -euo pipefail
BASE=/opt/hertzbeat-native
cd "$BASE/downloads"
echo "Tool installation started: $(date -Is)"
(
 curl -fL --retry 2 --connect-timeout 15 --max-time 1200 -sS https://corretto.aws/downloads/latest/amazon-corretto-25-x64-linux-jdk.tar.gz -o corretto25.tar.gz
 curl -fL --retry 2 --connect-timeout 15 --max-time 90 -sS https://corretto.aws/downloads/latest_sha256/amazon-corretto-25-x64-linux-jdk.tar.gz -o corretto25.sha256
 python3 - <<'PY'
import hashlib,pathlib,re,tarfile,os
base=pathlib.Path('/opt/hertzbeat-native')
p=base/'downloads/corretto25.tar.gz'
want=re.search(r'[a-fA-F0-9]{64}',(base/'downloads/corretto25.sha256').read_text()).group().lower()
h=hashlib.sha256()
with p.open('rb') as f:
 for c in iter(lambda:f.read(1024*1024),b''):h.update(c)
assert h.hexdigest()==want,'JDK SHA256 mismatch'
with tarfile.open(p) as t:
 names=t.getnames();assert all(not n.startswith('/') and '..' not in n.split('/') for n in names)
 root=names[0].split('/')[0];t.extractall(base/'tools')
link=base/'tools/jdk'
if not link.exists():link.symlink_to(base/'tools'/root)
print('JDK SHA256 VERIFIED',want,flush=True)
PY
 "$BASE/tools/jdk/bin/java" -version
) &
JDK_PID=$!
(
 V=3.9.16
 U="https://repo.maven.apache.org/maven2/org/apache/maven/apache-maven/$V/apache-maven-$V-bin.tar.gz"
 curl -fL --retry 2 --connect-timeout 15 --max-time 180 -sS "$U" -o maven.tar.gz
 curl -fL --retry 2 --connect-timeout 15 --max-time 90 -sS "$U.sha512" -o maven.sha512
 python3 - <<'PY'
import hashlib,pathlib,re,tarfile
base=pathlib.Path('/opt/hertzbeat-native');p=base/'downloads/maven.tar.gz'
want=re.search(r'[a-fA-F0-9]{128}',(base/'downloads/maven.sha512').read_text()).group().lower()
assert hashlib.sha512(p.read_bytes()).hexdigest()==want,'Maven SHA512 mismatch'
with tarfile.open(p) as t:
 names=t.getnames();assert all(not n.startswith('/') and '..' not in n.split('/') for n in names)
 root=names[0].split('/')[0];t.extractall(base/'tools')
link=base/'tools/maven'
if not link.exists():link.symlink_to(base/'tools'/root)
print('MAVEN SHA512 VERIFIED',want,flush=True)
PY
) &
MAVEN_PID=$!
npm install --prefix "$BASE/tools/pnpm" 'pnpm@10' --no-audit --no-fund
wait "$MAVEN_PID"
wait "$JDK_PID"
export JAVA_HOME="$BASE/tools/jdk"
export PATH="$JAVA_HOME/bin:$BASE/tools/maven/bin:$BASE/tools/pnpm/node_modules/.bin:$PATH"
java -version
mvn -version
node --version
pnpm --version
echo "TOOLS_READY $(date -Is)"
```


### 31.7 项目级 Maven 镜像

服务器文件：`/opt/hertzbeat-native/config/maven-settings.xml`

```xml
<settings xmlns="http://maven.apache.org/SETTINGS/1.2.0" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:schemaLocation="http://maven.apache.org/SETTINGS/1.2.0 https://maven.apache.org/xsd/settings-1.2.0.xsd">
  <mirrors><mirror><id>hertzbeat-central-mirror</id><name>Project-local Central mirror</name><url>https://maven.aliyun.com/repository/central</url><mirrorOf>central</mirrorOf></mirror></mirrors>
</settings>
```


### 31.8 前端构建脚本

服务器文件：`/opt/hertzbeat-native/bin/build-frontend.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail
source /opt/hertzbeat-native/env.sh
cd /opt/hertzbeat-native/source/web-app
pnpm install --frozen-lockfile --store-dir /opt/hertzbeat-native/cache/pnpm-store --virtual-store-dir /opt/hertzbeat-native/cache/pnpm-virtual-store --network-concurrency 8
pnpm exec ng build --configuration production
printf '\nFRONTEND_BUILD_SUCCESS\n'
```


### 31.9 后端构建脚本

服务器文件：`/opt/hertzbeat-native/bin/build-backend.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail
source /opt/hertzbeat-native/env.sh
cd /opt/hertzbeat-native/source
mvn -s /opt/hertzbeat-native/config/maven-settings.xml -B -ntp -T 2 -Daether.artifactResolver.threads=12 -Dmaven.repo.local=/opt/hertzbeat-native/cache/maven -Dmaven.test.skip=true -Dcheckstyle.skip=true -Djacoco.skip=true -pl hertzbeat-startup -am install
printf '\nBACKEND_BUILD_SUCCESS\n'
```


### 31.10 发布包构建脚本

服务器文件：`/opt/hertzbeat-native/bin/package-server.sh`

该辅助脚本保留了首次部署的日志就绪等待方式。后续修改代码后，仍需先确认最新后端、前端构建成功，不以旧日志代替本次结果。

```bash
#!/usr/bin/env bash
set -euo pipefail
source /opt/hertzbeat-native/env.sh
for n in $(seq 1 600); do
 if grep -q BACKEND_BUILD_SUCCESS /root/siton-data-zyh/hertzbeat-native/logs/build-backend.log; then break; fi
 if [ "$n" = 600 ]; then echo 'Backend build was not ready'; exit 1; fi
 sleep 2
done
test -f /opt/hertzbeat-native/source/web-app/dist/index.html
cd /opt/hertzbeat-native/source
mvn -s /opt/hertzbeat-native/config/maven-settings.xml -B -ntp -Dmaven.repo.local=/opt/hertzbeat-native/cache/maven -Dmaven.test.skip=true -Dcheckstyle.skip=true -Djacoco.skip=true -pl hertzbeat-startup -Prelease package
printf '\nPACKAGE_BUILD_SUCCESS\n'
```


### 31.11 首次运行配置生成脚本

服务器文件：`/opt/hertzbeat-native/bin/configure-runtime.py`

**初始化脚本提示：**它会从上游模板重新生成运行配置；已有手工配置时不要为了重启服务重复执行。代码中的 `secrets` 是生成逻辑，没有在本文展开实际密码或密钥。

```python
#!/usr/bin/env python3
import pathlib,re,secrets,json,os,shutil,grp
base=pathlib.Path('/opt/hertzbeat-native')
data=pathlib.Path('/root/siton-data-zyh/hertzbeat-native')
src=base/'source/hertzbeat-startup/src/main/resources'
creds_file=base/'config/credentials.json'
if creds_file.exists():
 creds=json.loads(creds_file.read_text())
else:
 creds={'username':'admin','password':secrets.token_urlsafe(24),'h2_password':secrets.token_urlsafe(24),'jwt_secret':secrets.token_urlsafe(96),'aes_secret':secrets.token_hex(16)}
 fd=os.open(str(creds_file),os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
 with os.fdopen(fd,'w') as f:json.dump(creds,f,indent=2)
text=(src/'application.yml').read_text()
text,n=re.subn(r'(?m)^server:\n  port: 1157$', 'server:\n  address: 127.0.0.1\n  port: 1157',text,count=1);assert n==1
text=text.replace('name: ${HOSTNAME:@hertzbeat@}${PID}','name: hertzbeat-native')
text,n=re.subn(r"(?ms)(  jwt:\n    secret:) '.*?'",lambda m:m.group(1)+" '"+creds['jwt_secret']+"'",text,count=1);assert n==1
text,n=re.subn(r'(?m)(    username: sa\n    password:) [^\n]+',lambda m:m.group(1)+" '"+creds['h2_password']+"'",text,count=1);assert n==1
text=text.replace('jdbc:h2:./data/hertzbeat;MODE=MYSQL','jdbc:h2:'+str(data/'data/metadata/hertzbeat')+';MODE=MYSQL')
text=text.replace('store-path: data/history.duckdb','store-path: '+str(data/'data/history/history.duckdb'))
text=text.replace('common:\n  queue:',"common:\n  secret: '"+creds['aes_secret']+"'\n  queue:")
text,n=re.subn(r'(?m)(scheduler:\n  server:\n    enabled:) true',r'\1 false',text,count=1);assert n==1
text=text.replace('${HERTZBEAT_OTLP_GRPC_HOST:0.0.0.0}','${HERTZBEAT_OTLP_GRPC_HOST:127.0.0.1}')
(base/'config/application.yml').write_text(text)
auth=(src/'sureness.yml').read_text()
auth=re.sub(r'(?ms)^account:\n.*',"account:\n  - appId: admin\n    credential: '"+creds['password']+"'\n    role: [admin]\n",auth,count=1)
auth=re.sub(r'(?m)^  - /h2-console/\*\*===\*\n','',auth)
(base/'config/sureness.yml').write_text(auth)
shutil.copy2(src/'logback-spring.xml',base/'config/logback-spring.xml')
gid=grp.getgrnam('hertzbeat-svc').gr_gid
for name in ('application.yml','sureness.yml','logback-spring.xml'):
 p=base/'config'/name;os.chown(p,0,gid);os.chmod(p,0o640)
print('Runtime configuration prepared; credentials stored only in '+str(creds_file))
```


### 31.12 首次发布脚本

服务器文件：`/opt/hertzbeat-native/bin/deploy-built-release.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail
for n in $(seq 1 300); do
 if grep -q PACKAGE_BUILD_SUCCESS /root/siton-data-zyh/hertzbeat-native/logs/package-server.log; then break; fi
 if [ "$n" = 300 ]; then echo 'Package was not ready'; exit 1; fi
 sleep 2
done
python3 -u - <<'PY'
import pathlib,tarfile,os,json
base=pathlib.Path('/opt/hertzbeat-native')
archive=base/'source/dist/apache-hertzbeat-1.9.0-bin.tar.gz'
assert archive.is_file(),str(archive)
with tarfile.open(archive) as t:
 names=t.getnames();assert all(not n.startswith('/') and '..' not in n.split('/') for n in names)
 root=names[0].split('/')[0]
 release=base/'releases'/root
 assert not release.exists(),'Refusing to overwrite existing release'
 t.extractall(base/'releases')
config=release/'config'
if config.is_dir():config.rename(release/'config.upstream')
config.symlink_to(base/'config')
for name,destination in {'data':'/root/siton-data-zyh/hertzbeat-native/data','logs':'/root/siton-data-zyh/hertzbeat-native/logs/runtime'}.items():
 p=release/name
 if not p.exists():p.symlink_to(destination)
current=base/'current'
assert not current.exists(),'Existing current release must be upgraded explicitly'
current.symlink_to(release)
assert (release/'apache-hertzbeat-1.9.0.jar').is_file()
creds=json.loads((base/'config/credentials.json').read_text())
p=base/'config/admin-login.txt'
fd=os.open(str(p),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
with os.fdopen(fd,'w') as f:f.write('username: '+creds['username']+'\npassword: '+creds['password']+'\n')
print('BUILT_RELEASE_DEPLOYED',str(release))
PY
chown root:hertzbeat-svc /opt/hertzbeat-native/config
chmod 750 /opt/hertzbeat-native/config
/usr/bin/python3 -m supervisor.supervisord -c /opt/hertzbeat-native/config/supervisord.conf
sleep 4
/opt/hertzbeat-native/bin/hertzbeatctl status
printf '\nINITIAL_DEPLOYMENT_STARTED\n'
```


### 31.13 Java 运行入口

服务器文件：`/opt/hertzbeat-native/bin/run-server.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail
source /opt/hertzbeat-native/env.sh
cd /opt/hertzbeat-native/current
export TMPDIR=/opt/hertzbeat-native/run/tmp
exec "$JAVA_HOME/bin/java" -Xms256m -Xmx2048m -XX:ActiveProcessorCount=4 -XX:MaxDirectMemorySize=512m --enable-native-access=ALL-UNNAMED --add-opens=java.base/java.nio=ALL-UNNAMED -Djava.io.tmpdir=/opt/hertzbeat-native/run/tmp -Duser.timezone=Asia/Shanghai -Dfile.encoding=UTF-8 -Dlogging.config=/opt/hertzbeat-native/config/logback-spring.xml -Dspring.config.location=/opt/hertzbeat-native/config/ -cp '/opt/hertzbeat-native/config:/opt/hertzbeat-native/current/apache-hertzbeat-1.9.0.jar:/opt/hertzbeat-native/current/lib/*:/opt/hertzbeat-native/current/ext-lib/*' org.apache.hertzbeat.startup.HertzBeatApplication
```


### 31.14 独立 Supervisor 配置

服务器文件：`/opt/hertzbeat-native/config/supervisord.conf`

```ini
[unix_http_server]
file=/opt/hertzbeat-native/run/supervisor.sock
chmod=0700
[supervisord]
logfile=/root/siton-data-zyh/hertzbeat-native/logs/supervisord.log
pidfile=/opt/hertzbeat-native/run/supervisord.pid
childlogdir=/root/siton-data-zyh/hertzbeat-native/logs/runtime
user=root
[rpcinterface:supervisor]
supervisor.rpcinterface_factory=supervisor.rpcinterface:make_main_rpcinterface
[supervisorctl]
serverurl=unix:///opt/hertzbeat-native/run/supervisor.sock
[program:hertzbeat]
command=/opt/hertzbeat-native/bin/run-server.sh
directory=/opt/hertzbeat-native/current
user=hertzbeat-svc
autostart=true
autorestart=unexpected
startsecs=20
startretries=3
stopwaitsecs=45
stopasgroup=true
killasgroup=true
umask=0027
stdout_logfile=/root/siton-data-zyh/hertzbeat-native/logs/runtime/stdout.log
stdout_logfile_maxbytes=20MB
stdout_logfile_backups=3
stderr_logfile=/root/siton-data-zyh/hertzbeat-native/logs/runtime/stderr.log
stderr_logfile_maxbytes=10MB
stderr_logfile_backups=3
environment=HOME="/opt/hertzbeat-native",USER="hertzbeat-svc",LANG="C.UTF-8"
```


### 31.15 启动与控制脚本

服务器文件：`/opt/hertzbeat-native/bin/start.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail
if /opt/hertzbeat-native/bin/hertzbeatctl pid >/dev/null 2>&1; then
 state=$(/opt/hertzbeat-native/bin/hertzbeatctl status hertzbeat || true)
 if [[ "$state" == *RUNNING* || "$state" == *STARTING* ]]; then printf '%s\n' "$state"; else /opt/hertzbeat-native/bin/hertzbeatctl start hertzbeat; fi
else
 /usr/bin/python3 -m supervisor.supervisord -c /opt/hertzbeat-native/config/supervisord.conf
 sleep 3
 /opt/hertzbeat-native/bin/hertzbeatctl status
fi
```


### 31.16 Supervisor 控制命令包装

服务器文件：`/opt/hertzbeat-native/bin/hertzbeatctl`

```bash
#!/usr/bin/env bash
exec /usr/bin/supervisorctl -c /opt/hertzbeat-native/config/supervisord.conf "$@"
```


### 31.17 前端开发入口

服务器文件：`/opt/hertzbeat-native/bin/dev-frontend.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail
source /opt/hertzbeat-native/env.sh
cd /opt/hertzbeat-native/source/web-app
exec pnpm start --host 127.0.0.1 --port 4200
```


### 31.18 本地源码提交记录

```text
0744170 Ignore local Maven and frontend build artifacts
c87cb84 Import verified Apache HertzBeat 1.9.0 source release
```


### 31.19 运行配置、源码和数据链接的实际指向

```json
{
  "/opt/hertzbeat-native/source": {
    "realpath": "/root/siton-data-zyh/hertzbeat-native/source/apache-hertzbeat-1.9.0-src",
    "is_symlink": true
  },
  "/opt/hertzbeat-native/current": {
    "realpath": "/opt/hertzbeat-native/releases/apache-hertzbeat-1.9.0-bin",
    "is_symlink": true
  },
  "/opt/hertzbeat-native/current/config": {
    "realpath": "/opt/hertzbeat-native/config",
    "is_symlink": true
  },
  "/opt/hertzbeat-native/current/data": {
    "realpath": "/root/siton-data-zyh/hertzbeat-native/data",
    "is_symlink": true
  },
  "/opt/hertzbeat-native/current/logs": {
    "realpath": "/root/siton-data-zyh/hertzbeat-native/logs/runtime",
    "is_symlink": true
  },
  "/opt/hertzbeat-native/tools/jdk": {
    "realpath": "/opt/hertzbeat-native/tools/amazon-corretto-25.0.4.10.1-linux-x64",
    "is_symlink": true
  },
  "/opt/hertzbeat-native/tools/maven": {
    "realpath": "/opt/hertzbeat-native/tools/apache-maven-3.9.16",
    "is_symlink": true
  }
}
```


### 31.20 基础 HTTP 冒烟报告摘录

这是实际报告，不包含登录密码或 token。此后又执行了包含自检监控的继续验证。

```json
{
  "checks": {
    "web_ui": {
      "http_status": 200,
      "html_bytes": 4157
    },
    "frontend_assets": [
      {
        "path": "styles.4302bcbcdd3b970a.css",
        "http_status": 200,
        "bytes": 669994
      },
      {
        "path": "styles.4302bcbcdd3b970a.css",
        "http_status": 200,
        "bytes": 669994
      },
      {
        "path": "runtime.b0fa5a4e0f22b4ee.js",
        "http_status": 200,
        "bytes": 3069
      },
      {
        "path": "polyfills.e173e51724d2438e.js",
        "http_status": 200,
        "bytes": 34494
      },
      {
        "path": "scripts.6a73cb79a425cb60.js",
        "http_status": 200,
        "bytes": 129456
      },
      {
        "path": "main.05425243ada4f979.js",
        "http_status": 200,
        "bytes": 2441655
      }
    ],
    "login": {
      "http_status": 200,
      "business_code": 0,
      "token_issued": true
    },
    "/api/apps/hierarchy": {
      "http_status": 200,
      "business_code": 0,
      "data_type": "list",
      "top_level_items": 140
    },
    "/api/monitors?pageIndex=0&pageSize=8": {
      "http_status": 200,
      "business_code": 0,
      "data_type": "dict",
      "total_elements": 0
    },
    "unauthenticated_api": {
      "http_status": 401
    },
    "actuator_health": {
      "http_status": 200,
      "status": "UP"
    },
    "metadata_db": {
      "path": "/root/siton-data-zyh/hertzbeat-native/data/metadata/hertzbeat.mv.db",
      "exists": true,
      "bytes": 176128
    },
    "history_db": {
      "path": "/root/siton-data-zyh/hertzbeat-native/data/history/history.duckdb",
      "exists": true,
      "bytes": 274432
    }
  },
  "base_url": "http://127.0.0.1:1157",
  "tested_at": "2026-10-21T23:03:49+0800",
  "passed": true
}
```


### 31.21 真实采集与重启恢复摘要

```json
{
  "monitor_name": "hertzbeat-native-selfcheck",
  "monitor_id_before_restart": 696820437611776,
  "monitor_id_after_restart": 696820437611776,
  "same_monitor_restored": true,
  "monitor_status_after_restart": 1,
  "interval_seconds": 30,
  "real_collection_verified": true,
  "history_business_code": 0,
  "history_points_at_test_time": 5,
  "history_response_time_values_ms": [
    "7",
    "98",
    "4",
    "6",
    "6"
  ]
}
```


### 31.22 Java 启动与 schema 恢复日志

保留关键事件，未拷贝完整应用日志。

```text
2026-10-21 22:59:36 [main] INFO  org.flywaydb.core.internal.command.DbMigrate - Current version of schema "PUBLIC": 1
2026-10-21 22:59:40 [main] INFO  org.flywaydb.core.internal.command.DbMigrate - Successfully applied 6 migrations to schema "PUBLIC", now at version v190 (execution time 00:04.466s)
2026-10-21 22:59:40 [main] WARN  org.apache.hertzbeat.ai.config.LlmConfig - LLM Provider is not set, ChatClient bean will not be created
2026-10-21 22:59:41 [main] INFO  org.springframework.boot.tomcat.TomcatWebServer - Tomcat started on port 1157 (http) with context path '/'
2026-10-21 22:59:41 [main] INFO  org.apache.hertzbeat.startup.HertzBeatApplication - Started HertzBeatApplication in 15.568 seconds (process running for 15.943)
2026-10-21 23:03:39 [main] INFO  org.flywaydb.core.internal.command.DbMigrate - Current version of schema "PUBLIC": 190
2026-10-21 23:03:39 [main] INFO  org.flywaydb.core.internal.command.DbMigrate - Schema "PUBLIC" is up to date. No migration necessary.
2026-10-21 23:03:39 [main] WARN  org.apache.hertzbeat.ai.config.LlmConfig - LLM Provider is not set, ChatClient bean will not be created
2026-10-21 23:03:40 [main] INFO  org.springframework.boot.tomcat.TomcatWebServer - Tomcat started on port 1157 (http) with context path '/'
2026-10-21 23:03:40 [main] INFO  org.apache.hertzbeat.startup.HertzBeatApplication - Started HertzBeatApplication in 11.435 seconds (process running for 11.816)
2026-10-22 00:11:27 [main] INFO  org.flywaydb.core.internal.command.DbMigrate - Current version of schema "PUBLIC": 190
2026-10-22 00:11:27 [main] INFO  org.flywaydb.core.internal.command.DbMigrate - Schema "PUBLIC" is up to date. No migration necessary.
2026-10-22 00:11:28 [main] WARN  org.apache.hertzbeat.ai.config.LlmConfig - LLM Provider is not set, ChatClient bean will not be created
2026-10-22 00:11:29 [main] INFO  org.springframework.boot.tomcat.TomcatWebServer - Tomcat started on port 1157 (http) with context path '/'
2026-10-22 00:11:29 [main] INFO  org.apache.hertzbeat.startup.HertzBeatApplication - Started HertzBeatApplication in 11.049 seconds (process running for 11.436)
```


### 31.23 Supervisor 生命周期日志

可观察到首次后台化、受控停止及重新进入 RUNNING。CRIT 的 Unix socket 认证提示已在第 26 节解释。

```text
2026-10-21 22:59:24,829 INFO Set uid to user 0 succeeded
2026-10-21 22:59:24,853 INFO RPC interface 'supervisor' initialized
2026-10-21 22:59:24,853 CRIT Server 'unix_http_server' running without any HTTP authentication checking
2026-10-21 22:59:24,854 INFO daemonizing the supervisord process
2026-10-21 22:59:24,855 INFO supervisord started with pid 33579
2026-10-21 22:59:25,858 INFO spawned: 'hertzbeat' with pid 33581
2026-10-21 22:59:46,029 INFO success: hertzbeat entered RUNNING state, process has stayed up for > than 20 seconds (startsecs)
2026-10-21 23:03:18,336 INFO waiting for hertzbeat to stop
2026-10-21 23:03:20,336 INFO waiting for hertzbeat to stop
2026-10-21 23:03:22,336 INFO waiting for hertzbeat to stop
2026-10-21 23:03:24,336 INFO waiting for hertzbeat to stop
2026-10-21 23:03:26,336 INFO waiting for hertzbeat to stop
2026-10-21 23:03:28,336 INFO waiting for hertzbeat to stop
2026-10-21 23:03:28,742 INFO stopped: hertzbeat (exit status 143)
2026-10-21 23:03:28,906 INFO spawned: 'hertzbeat' with pid 33782
2026-10-21 23:03:49,020 INFO success: hertzbeat entered RUNNING state, process has stayed up for > than 20 seconds (startsecs)
2026-10-22 00:11:07,267 INFO waiting for hertzbeat to stop
2026-10-22 00:11:09,267 INFO waiting for hertzbeat to stop
2026-10-22 00:11:11,267 INFO waiting for hertzbeat to stop
2026-10-22 00:11:13,267 INFO waiting for hertzbeat to stop
2026-10-22 00:11:15,267 INFO waiting for hertzbeat to stop
2026-10-22 00:11:17,267 INFO waiting for hertzbeat to stop
2026-10-22 00:11:17,907 INFO stopped: hertzbeat (exit status 143)
2026-10-22 00:11:17,913 INFO spawned: 'hertzbeat' with pid 34630
2026-10-22 00:11:38,659 INFO success: hertzbeat entered RUNNING state, process has stayed up for > than 20 seconds (startsecs)
```


### 31.24 构建完成证据

**install-tools.log**

```text
TOOLS_READY 2026-10-21T22:40:13+08:00
```

**build-backend.log**

```text
[INFO] hertzbeat .......................................... SUCCESS [ 16.899 s]
[INFO] hertzbeat-common-core .............................. SUCCESS [ 42.675 s]
[INFO] hertzbeat-common-spring ............................ SUCCESS [ 27.793 s]
[INFO] hertzbeat-base ..................................... SUCCESS [  0.342 s]
[INFO] hertzbeat-plugin ................................... SUCCESS [  7.214 s]
[INFO] hertzbeat-warehouse ................................ SUCCESS [ 20.083 s]
[INFO] hertzbeat-alerter .................................. SUCCESS [ 13.846 s]
[INFO] hertzbeat-remoting ................................. SUCCESS [ 11.368 s]
[INFO] hertzbeat-collector ................................ SUCCESS [  0.480 s]
[INFO] hertzbeat-collector-common ......................... SUCCESS [  4.681 s]
[INFO] hertzbeat-collector-basic .......................... SUCCESS [ 26.910 s]
[INFO] hertzbeat-collector-mysql-r2dbc .................... SUCCESS [ 10.210 s]
[INFO] hertzbeat-collector-kafka .......................... SUCCESS [  0.703 s]
[INFO] hertzbeat-collector-mongodb ........................ SUCCESS [  2.494 s]
[INFO] hertzbeat-collector-nebulagraph .................... SUCCESS [  4.086 s]
[INFO] hertzbeat-collector-rocketmq ....................... SUCCESS [  5.553 s]
[INFO] hertzbeat-collector-collector ...................... SUCCESS [  7.669 s]
[INFO] hertzbeat-push ..................................... SUCCESS [  0.889 s]
[INFO] hertzbeat-grafana .................................. SUCCESS [  1.966 s]
[INFO] hertzbeat-otel ..................................... SUCCESS [ 26.741 s]
[INFO] hertzbeat-observability ............................ SUCCESS [  2.517 s]
[INFO] hertzbeat-manager .................................. SUCCESS [ 22.069 s]
[INFO] hertzbeat-ai ....................................... SUCCESS [ 21.735 s]
[INFO] hertzbeat-startup .................................. SUCCESS [  1.361 s]
[INFO] BUILD SUCCESS
[INFO] Total time:  03:28 min (Wall Clock)
[INFO] Finished at: 2026-10-21T22:53:18+08:00
BACKEND_BUILD_SUCCESS
```

**build-frontend.log**

```text
Build at: 2026-10-21T14:50:43.008Z - Hash: 9ff6d1619593b149 - Time: 89677ms
FRONTEND_BUILD_SUCCESS
```

**package-server.log**

```text
[INFO] BUILD SUCCESS
[INFO] Total time:  05:31 min
[INFO] Finished at: 2026-10-21T22:59:18+08:00
PACKAGE_BUILD_SUCCESS
```

**deploy-release.log**

```text
INITIAL_DEPLOYMENT_STARTED
```


### 31.25 备份文件快照

| 归档 | 字节数 |
|---|---|
| `config-bootstrap-20261021.tar.gz` | 15592 |
| `config-verified-20261022.tar.gz` | 16730 |
| `data-bootstrap-20261021.tar.gz` | 23167 |


### 31.26 脱敏部署清单

`git_commit` 是本地发布包导入仓库的提交，不冒充 GitHub 上游 tag 的 commit。

```json
{
  "deployed_at": "2026-10-21T23:08:51.469285+08:00",
  "release": "Apache HertzBeat 1.9.0 source distribution",
  "upstream_maven_version": "2.0-SNAPSHOT (unchanged)",
  "source": "/root/siton-data-zyh/hertzbeat-native/source/apache-hertzbeat-1.9.0-src",
  "source_alias": "/opt/hertzbeat-native/source",
  "git_branch": "codex/hertzbeat-native",
  "git_commit": "07441700366bd8d64cd3e382c0e7e858f595ab21",
  "git_clean": true,
  "runtime": "/opt/hertzbeat-native/releases/apache-hertzbeat-1.9.0-bin",
  "config": "/opt/hertzbeat-native/config",
  "data": "/root/siton-data-zyh/hertzbeat-native/data",
  "logs": "/root/siton-data-zyh/hertzbeat-native/logs",
  "tools": {
    "jdk": "Amazon Corretto 25.0.4.1",
    "maven": "3.9.16",
    "node": "22.23.1",
    "pnpm": "10.34.7"
  },
  "service_user": "hertzbeat-svc",
  "listen": "127.0.0.1:1157",
  "metadata_storage": "H2",
  "history_storage": "DuckDB",
  "source_sha512": "143c563971a57d8ce5088f357f9040d0c0615e785dfedd0ac665575ee553d89d1a4beda883f33e4fb23423e6555722685caddc7c00590e945d4b23908ee3541c",
  "admin_credentials_file": "/opt/hertzbeat-native/config/admin-login.txt",
  "http_smoke_passed": true,
  "restart_smoke_passed": true,
  "full_unit_suite_run": false,
  "agent_integration_done": false,
  "existing_services_restarted": false,
  "last_verified_at": "2026-10-22T00:12:41.094619+08:00",
  "selfcheck_monitor_id": 696820437611776,
  "selfcheck_monitor_name": "hertzbeat-native-selfcheck",
  "live_collection_verified": true,
  "monitor_restored_after_restart": true,
  "history_query_passed": true
}
```



---

## 最后总结

这次部署形成的是一套可以继续二次开发的独立 HertzBeat 单机环境：

1. Linux 私有开发工具已准备好。
2. 官方固定版本源码已校验并保存在用户数据卷。
3. 前后端由源码构建，生成了完整运行包。
4. 程序、配置、数据、缓存、日志和备份有明确分工。
5. Java 以独立服务账户运行，管理进程与原有服务分开。
6. 网页、认证、监控 API、真实 HTTP 采集、历史读取和重启恢复均有证据。
7. 现有 RAGFlow、Qwen 没有被本次部署修改或重启。

后续最重要的是在这套基础上完成 Agent 的业务接入，而不是重新安装一遍环境。
