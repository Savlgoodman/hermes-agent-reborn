# Hermes Quick Docker

这个目录用于快速部署一个 Hermes Gateway 实例，并通过 Business API 插件对外提供接口。

当前部署只启动一个 `gateway` 容器，不再启动 dashboard 容器，也不再使用旧的 `context-usage` dashboard 插件。

## 初始化

1. 复制 `.env.example` 为 `.env`。
2. 在 `.env` 中设置 `BUSINESS_API_KEY`，请使用足够长的随机 token。
3. 如需在同一台机器部署多个实例，修改 `BUSINESS_API_PUBLISHED_PORT`。
4. 在当前目录创建或挂载 `workspace/` 目录。

## 编译镜像

在仓库根目录执行构建，不要在 `quick_docker/` 目录里执行，因为 Dockerfile 需要读取整个 Hermes 项目源码：

```bash
docker build -t kevinroo/hermes-agent:business-api .
```

如果要换成你自己的镜像名：

```bash
docker build -t your-registry/hermes-agent:business-api .
```

然后在 `quick_docker/.env` 中设置：

```env
HERMES_IMAGE=your-registry/hermes-agent:business-api
```

如果需要推送到远端镜像仓库：

```bash
docker push your-registry/hermes-agent:business-api
```

如果是全新的 `data/` 目录，先运行一次 Hermes 初始化流程，用来配置模型 provider、API key 等：

```bash
docker compose -f docker-compose.deploy.yml run --rm gateway setup
```

## 启动和停止

启动：

```bash
docker compose -f docker-compose.deploy.yml up -d
```

停止：

```bash
docker compose -f docker-compose.deploy.yml down
```

## Business API

常用接口：

- `POST /v1/responses`
- `GET /api/responses/{response_id}/context`
- `POST /api/files`

端口由 `.env` 控制：

```env
BUSINESS_API_PORT=24000
BUSINESS_API_PUBLISHED_PORT=24000
```

通常只需要改 `BUSINESS_API_PUBLISHED_PORT`。例如宿主机暴露 `25000`，容器内仍监听 `24000`：

```env
BUSINESS_API_PORT=24000
BUSINESS_API_PUBLISHED_PORT=25000
```

## 关于 command

Docker 镜像的 `entrypoint.sh` 末尾会自动给普通 Hermes 子命令补上 `hermes` 前缀。

所以这种写法是可以的：

```yaml
command: ["gateway", "run"]
```

它会被 entrypoint 执行为：

```bash
hermes gateway run
```

但是当前 compose 使用的是 `bash -lc`，因为启动前需要先确保 Business API 插件启用：

```yaml
command:
  - bash
  - -lc
  - |
    hermes plugins enable platforms/business_api >/dev/null 2>&1 || true
    exec hermes gateway run
```

这里第一个参数是 `bash`，entrypoint 会把它当成真实可执行文件直接运行，不会再自动补 `hermes`，所以脚本内部必须显式写 `hermes plugins ...` 和 `hermes gateway run`。

这样即使 `data/` 是空目录，容器第一次启动时也会先把 `platforms/business_api` 写入 Hermes 配置，再启动 gateway。

## 多实例部署

同一台机器部署多个实例时，至少修改：

- compose 顶层 `name:`
- `services.gateway.container_name`
- `.env` 里的 `BUSINESS_API_PUBLISHED_PORT`
- `./data` 和 `./workspace` 挂载目录，如果每个实例需要隔离状态
