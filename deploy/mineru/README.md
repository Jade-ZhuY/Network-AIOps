# 独立云端 MinerU

此目录只部署 MinerU，不容器化本机 Network AIOps，也不修改 MySQL/PostgreSQL。

- MinerU 4.0.12，mineru-llama-cpp 0.1.3。
- ONNX 小模型在 CPU 上运行，Standard VLM 使用 llama.cpp / NVIDIA Vulkan。
- 显式要求 Vulkan，GPU 未就绪时失败，不静默改成 CPU 推理。
- Python 基础镜像固定 digest；使用 Debian 收录的 USTC HTTPS 镜像源，保留发行版签名校验。依赖解析结果在部署验收时记录。
- 该组合避免升级云端 CUDA 12.8 / NVIDIA 570 驱动；不同于官方 CUDA 13 + vLLM 镜像。
- 只发布服务器回环端口 18000，API bearer key 保存在服务器 secrets 目录。
- 模型、配置、上传源文件及产物挂载到独立 data 目录；API job/file 索引仍是进程内状态，不保证服务重启后恢复任务 ID。

## 目录

在服务器的独立部署目录保存：

```text
network-aiops-mineru/
  app/                 本目录中的配置文件
  data/home/           MinerU 配置、模型缓存
  data/uploads/        上传原文
  data/results/        验收与解析产物
  secrets/mineru_api_key  随机令牌，权限 600，不提交 Git
```

使用非 root 容器 UID 1000，服务器挂载目录及密钥需由对应 UID 读取。

## 操作

```bash
cd ~/network-aiops-mineru/app
sudo docker compose build
# 模型下载使用相同的 small-backend / vlm-engine，之后再启动服务。
sudo docker compose run --rm --entrypoint mineru-kit \
  -e MINERU_MODEL_SOURCE=modelscope api models download \
  --tier standard --small-backend onnx --vlm-engine llama-cpp --source modelscope
sudo docker compose run --rm --entrypoint mineru-kit api models verify \
  --tier standard --small-backend onnx --vlm-engine llama-cpp
sudo docker compose up -d
sudo docker compose ps
```

## 安全连接

在调用端建立 SSH 隧道，不开放无认证的外部解析端口：

```bash
ssh -N -L 127.0.0.1:18000:127.0.0.1:18000 ubuntu@HOST
```

然后将客户端连接到 `http://127.0.0.1:18000`，使用单独的 MinerU bearer key。不要复用 LLM_API_KEY 或应用登录令牌，不把密钥放入 URL、代码或 Git。

本机 RAG 解析适配器尚未切换到 MinerU；此任务只部署独立解析服务。部署验收结果另见 verification.md。

## 验收调用

本机建立隧道后，使用忽略的 `.env.mineru-cloud` 配置；工具支持 dotenv 或纯令牌文件，并先校验格式，避免传输错误回显凭据。

```powershell
uv run python deploy/mineru/probe.py --base-url http://127.0.0.1:18000 `
  --token-file .env.mineru-cloud --input outputs/mineru-smoke-scan.pdf `
  --output outputs/mineru-cloud-final.json
```

部署源文件是独立目录；本机原有 Dockerfile/Compose 和 RAG 入口没有修改。
