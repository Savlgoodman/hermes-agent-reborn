# Hermes Business API 插件

Business API 是一个面向业务后端调用的 Hermes Gateway platform 插件。它复用 Hermes 内置的 OpenAI-compatible Responses 实现，同时额外提供会话上下文、token 用量查询，以及工作目录文件上传/下载能力。

这个插件适合把 Hermes 部署在 Docker 或远程服务器里，由你的业务服务通过 HTTP 调用 Hermes，并在业务侧完成用户、会话、计费、文件展示等逻辑。

## 启用方式

```bash
hermes plugins enable platforms/business_api
hermes gateway run
```

常用环境变量：

| 变量 | 默认值 | 用途 |
| --- | --- | --- |
| `BUSINESS_API_ENABLED` | 空 | 设置为 `true` 可通过环境变量启用插件 |
| `BUSINESS_API_KEY` | 空 | Bearer token，建议生产环境必须配置 |
| `BUSINESS_API_HOST` | `127.0.0.1` | 监听地址 |
| `BUSINESS_API_PORT` | `8765` | 监听端口 |
| `BUSINESS_API_WORKSPACE_ROOT` | `/opt/workspace` | 文件上传和下载允许访问的根目录 |
| `BUSINESS_API_MAX_UPLOAD_BYTES` | `104857600` | 单文件上传大小上限 |

请求鉴权：

```http
Authorization: Bearer <BUSINESS_API_KEY>
```

## 接口

### `POST /v1/responses`

调用 Hermes agent 的 Responses 接口。它兼容 Hermes 内置 API server 的 `/v1/responses` 行为，支持通过 `previous_response_id` 延续上下文。

示例：

```bash
curl -X POST http://127.0.0.1:8765/v1/responses \
  -H "Authorization: Bearer $BUSINESS_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"input":"你好，请生成一份 123.txt 的内容。"}'
```

### `GET /api/responses/{response_id}/context`

根据本次 response id 查询该 response 结束时的上下文快照、模型信息、本轮 token 用量，以及当前 Hermes session 的累计 token 用量。

示例：

```bash
curl "http://127.0.0.1:8765/api/responses/resp_xxx/context" \
  -H "Authorization: Bearer $BUSINESS_API_KEY"
```

如果不需要返回消息列表，可以传：

```bash
curl "http://127.0.0.1:8765/api/responses/resp_xxx/context?include_messages=false" \
  -H "Authorization: Bearer $BUSINESS_API_KEY"
```

### `POST /api/files`

把业务侧文件上传到 Hermes 工作目录。适合让远端 Docker 内的 agent 后续读取或处理文件。

表单字段：

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `file` | 是 | 上传文件 |
| `target_path` | 否 | 目标目录。为空时写入 `BUSINESS_API_WORKSPACE_ROOT` |
| `overwrite` | 否 | `true` 时覆盖同名文件，默认自动改名 |
| `conversation_id` | 否 | 业务侧会话 id，仅原样记录在返回值中 |

示例：

```bash
curl -X POST http://127.0.0.1:8765/api/files \
  -H "Authorization: Bearer $BUSINESS_API_KEY" \
  -F "target_path=/opt/workspace/user-a" \
  -F "overwrite=true" \
  -F "file=@123.txt"
```

### `GET /api/files`

从 Hermes 工作目录下载文件。业务后端可以根据自己保存的用户工作目录，加上前端点击的文件名，调用这个接口取回 agent 生成或编辑后的文件。

查询参数：

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| `path` | 否 | 文件所在目录。为空时使用 `BUSINESS_API_WORKSPACE_ROOT`。`/xxx` 会被视为 workspace 根下的 `xxx` |
| `file_name` | 是 | 文件名，只允许普通文件名，不允许带 `/`、`\`、`.` 或 `..` 目录跳转 |

示例：

```bash
curl -OJ "http://127.0.0.1:8765/api/files?path=/opt/workspace/user-a&file_name=123.txt" \
  -H "Authorization: Bearer $BUSINESS_API_KEY"
```

插件会把 `path + file_name` 解析为真实路径，并要求最终路径仍在 `BUSINESS_API_WORKSPACE_ROOT` 内。带前导 `/` 的路径会按 workspace 内路径处理，例如 `/reports` 表示 `<workspace_root>/reports`。`../../`、Windows 盘符绝对路径、符号链接跳出 workspace 等情况会被拒绝。

## 安全注意事项

生产环境请配置强随机 `BUSINESS_API_KEY`，并建议放在内网、反向代理或 TLS 后面。不要把未鉴权的 Business API 直接暴露到公网。

文件接口的权限模型应主要由业务后端负责：业务后端需要维护用户、会话和工作目录之间的关系，比如把某个 session 绑定到 `/opt/workspace/<tenant>/<conversation_id>`，并只允许该用户下载自己目录下的文件。

调用下载接口前，业务后端仍应验证 `path` 和 `file_name`，尤其要拒绝 `../`、跨租户目录、空文件名、目录名伪装等输入。插件层的 workspace-root containment 是兜底防护，不应作为唯一的租户隔离和授权边界。

`BUSINESS_API_WORKSPACE_ROOT` 应设置为专用目录，例如 Docker 内的 `/opt/workspace`。不要把它设置为 `/`、用户 home 或包含系统敏感文件的目录。

## 本地 Smoke Test

启动 gateway 后，可以运行：

```bash
python scripts/business_api_upload_smoke.py
```

脚本会上传一个内容为 `hello` 的 `123.txt`，再通过 `GET /api/files` 下载回来并校验内容一致。
