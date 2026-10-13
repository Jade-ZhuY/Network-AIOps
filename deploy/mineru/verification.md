# 云端 MinerU Docker 部署验收

日期：2026-10-13（Asia/Shanghai）。部署对象为用户指定的 Ubuntu 云服务器；SSH 密码不存入配置、脚本或 Git。

## 环境与部署

- Ubuntu 22.04.4 / Linux 5.15；16 vCPU、约 64GB RAM、RTX 4090 24GB。
- 保留 NVIDIA 570.153.02 / CUDA 12.8 驱动，不升级驱动或重启云服务器。
- 安装 Docker Engine 29.9.0、Compose 5.6.0、NVIDIA Container Toolkit 1.20.1。
- 使用独立容器 `network-aiops-mineru`，MinerU 4.0.12、mineru-llama-cpp 0.1.3。
- Standard 档位：ONNX 小模型使用 CPU，llama.cpp VLM 显式使用 Vulkan GPU；不是官方 CUDA 13/vLLM 镜像。
- ONNX 模型包 `MinerU-4_models_onnx` 和 `MinerU2.5-Pro-2605-1.2B-GGUF` 下载并验证通过。模型目录约 2.0GiB，镜像约 1.5GiB，不代表任意配置的固定大小。
- 基础镜像来自 Docker 官方 Python 仓库，固定 digest `sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258`。云端 Docker Hub 连接超时，使用已校验 SHA256 的镜像归档通过 SSH 传入。
- Debian 依赖使用其收录的 USTC HTTPS 镜像源，保留签名校验。NVIDIA Vulkan ICD 动态依赖 EGL，镜像补齐 libegl1/libgbm1 后 GPU 预检通过。
- 实际 Python 依赖版本记录在 requirements-resolved.txt，后续重建可据此约束依赖；它不是 Python/系统包/模型文件的统一锁文件。

## 安全与访问

- 仅绑定服务器 `127.0.0.1:18000`，容器内监听 8000；不新增外部 HTTP 监听。
- 本机 SSH 隧道连接同名回环端口；实际经隧道访问已验证。
- 独立随机 bearer key，服务器权限 600。客户端配置在本机 Git 忽略的 `.env.mineru-cloud`，限制为当前用户及 SYSTEM 访问。
- 容器非 root 用户、只读根文件系统、cap_drop ALL、no-new-privileges；数据目录单独挂载。
- 自动重启策略 unless-stopped，限制 8 CPU / 24GiB RAM / 一个并发解析任务，日志轮换。
- 一次测试将 dotenv 文件误作为纯令牌读取，客户端异常回显了旧的测试服务令牌。该令牌已失效并轮换；密钥读取增加格式校验和回归测试，当前有效令牌未提交 Git。SSH 密码与已有应用/模型密钥未受此问题影响。

## 实际验收

1. 容器内 Vulkan 检测为 `NVIDIA GeForce RTX 4090`，设备类型 DISCRETE_GPU；不是软件 Vulkan/CPU 替代。
2. 模型 verify：ONNX 和 VLM 两套模型均 ok。
3. 认证 health：200；无认证上传：401。
4. 使用自生成、非敏感的两页 PDF，转换为扫描版后以 Standard / OCR 解析，文本中的 BGP、R3、6.06 保留。
5. 初次扫描解析 13.103 秒；容器重建后经本机 SSH 隧道再次解析，Markdown、middle_json、structured_content 均返回，结构化页数为 2，耗时 9.5 秒；最终镜像再验收为 9.828 秒。
6. GPU 采样峰值约 1941MiB、使用率 53%。该单样本不是吞吐量、P95 或生产质量评估。
7. 容器重建后模型、源文件和密钥保留，不重新下载模型，服务恢复 healthy。

原始非敏感结果位于本机 outputs/mineru-cloud-*.json / gpu.csv，不提交 Git。

## 代码回归与范围

- 本次部署工具的 6 项单元测试通过，覆盖同源 URL 校验、synthetic PDF、密钥文件格式与错误不回显。
- Ruff 检查与格式检查通过。
- 离线全套回归 149 passed / 15 skipped。包括外部数据库的回归曾出现 4 个 PostgreSQL 连接超时（此前 159 passed / 4 failed 的运行含 5 项部署测试）；本次没有修改 PostgreSQL 配置或服务。
- 本机原有 Milvus、MinIO、etcd 容器保持运行。没有在本机启动 MinerU 模型服务，没有改变应用、业务数据库或原有 RAG 解析器。
- 此任务只部署独立解析服务；将其接入 Network AIOps 上传/索引流程属于下一步。现有 RAG 尚未自动切换到 MinerU。
- MinerU V1 上传/任务/文件索引属于进程内状态，重启不保证旧 task/file ID 可继续使用；调用方需保存下载产物并重新提交中断任务。

## WebUI 补充验收

- 独立可选服务 `webui` / 容器 `network-aiops-mineru-webui` 已启动并 healthy，
  复用现有镜像，不重建、不重新下载模型。没有给 WebUI 分配 GPU；Standard
  解析连接已有 `http://api:8000`。原 API 容器 ID 保持不变且仍为 healthy。
- 网页只发布 `127.0.0.1:7860`，本机另建 SSH 隧道访问，不开放云端公网端口。
  两个容器均保持非 root 与只读根文件系统，WebUI 密钥从 secret 读取到进程环境，
  不写入命令参数或浏览器配置。检查 `/config` 未包含实际 bearer key。
- `webui_start.py` 使用只读绑定挂载，因此只补充配置即可使用已有镜像。
  WebUI 输出与 Gradio 临时文件写入其 `/data/output`、`/data/tmp`；该容器的
  `/data` 对应宿主机 `/home/ubuntu/network-aiops-mineru/data/webui`。
- 实际网页 `/`、`/config` 均返回 200。通过浏览器上传自生成的两页扫描 PDF，
  Standard + 强制 OCR，网页显示“已完成（3.38 秒）”，两页 PDF 预览与 Markdown
  内容正常，保留 BGP、R3、6.06。服务已预热，该值不代表冷启动或吞吐量。
- 非敏感截图保存在本机 `outputs/mineru-webui.png` 与
  `outputs/mineru-webui-completed.png`，不提交 Git。
- 部署工具测试 10 passed，包含新增 WebUI 密钥不进入参数、固定已有 API、
  可写输出目录和无凭据回显的校验。默认全套测试 153 passed / 15 skipped；
  Ruff 检查、格式检查与两端 Compose 配置校验通过。
- 本次仅补充 MinerU WebUI，仍未切换 Network AIOps 的 RAG 解析器。

## 按用户要求更改 WebUI 公网绑定

本节覆盖上节 WebUI 的回环绑定配置，API 配置保持不变。

- WebUI 改为 `0.0.0.0:7860:7860`，仅重新创建 WebUI 容器，状态 healthy。
  服务器 `ss` 确认监听 `0.0.0.0:7860`。API 仍为 `127.0.0.1:18000:8000`，
  容器 ID 与更改前一致，状态 healthy。
- 从本机绕过 HTTP 代理直接测试：服务器 TCP 22 可连接；TCP 7860 连接超时。
  公网网页访问尚未验证通过。原 SSH 隧道访问网页仍为 HTTP 200。
- 主机未安装 ufw，iptables INPUT 为 ACCEPT，DOCKER-USER 无额外规则，
  Docker 链中 7860 已为对应容器放行。需在云平台检查安全组/外部网络入站规则；
  本次未更改云平台规则，也未关闭任何服务器防火墙保护。
- WebUI 仍未增加登录或 HTTPS。用户在已说明公网暴露影响后要求修改绑定；
  建议公网入口限制来源 IP，并在长期使用前补充认证和 HTTPS。
- 部署测试 11 passed；Ruff 检查、格式检查与两端 Compose 配置校验通过。
