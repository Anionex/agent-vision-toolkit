# codex-deepseek-vision

如果你的 Codex 已经接入 DeepSeek ，却烦恼于模型没有多模态，不能看图、每次调用看图都会被系统拦下，本仓库提供了一种方式，可以在不引入额外mcp、skills、cli、其他工具的情况下，让纯文本模型调用codex内置view image的时候不报错，而是给出图片的详细描述，尽量让纯文本模型的交互体验和多模态模型的交互体验保持一致，免去反复配置的风险。

所有代码均已在真实 Codex + DeepSeek 会话中验证过。

## 实际效果

<p align="center">
  <img src="assets/effect-1.jpg" alt="Codex 里的 DeepSeek 看 UI 图回答风格问题" width="49%">
  <img src="assets/effect-2.jpg" alt="Codex 里的 DeepSeek 看图排查界面字段不一致 bug" width="49%">
</p>

## 亮点

- **贴图和 `view_image` 都支持**：直接粘贴图片（`message.content`）和模型调用 `view_image`（`function_call_output.output`）两种结构都会被改写为文字描述。
- **多图并行看图**：一次请求里的多张图并发调用视觉模型，N 张图约等于 1 张图的延迟，不必逐张等待。
- **同图只调一次**：按图片 sha256 缓存描述，同一张图反复出现不重复调用视觉 API，缓存命中近乎零延迟。
- **可选 `glance`**：需要在 Codex 之外直接进行图片描述、问答或 OCR 时，可以单独使用。

## 使用方式

本仓库是一份可以运行的方案，不提供通用一键安装器。推荐把仓库链接交给当前 macOS 上的 Codex Agent，并让它按照本文检查现有配置、备份、部署和验证：

> 我已经在 Codex 中接入并可正常使用 DeepSeek。请阅读这个仓库的 README，在 macOS 上部署代理。保留现有模型、provider、显示名称和鉴权，只按文档的条件修改配置，完成后验证 `view_image`。

Agent 应以用户机器上的真实配置为准，不得假设 provider 名、模型名、catalog 文件名或 DeepSeek 上游地址。

## 前置条件

- macOS 和已可正常使用 DeepSeek 的 Codex
- Python 3.11+
- 一个支持 `/chat/completions` 与 `image_url` 的 OpenAI-compatible 视觉 API

## macOS 部署步骤

以下步骤是给 Codex Agent 的执行规范。路径可以根据用户环境调整，但不要扩大配置改动范围。

### 1. 定位并备份现有配置

读取 `~/.codex/config.toml`：

1. 读取顶层 `model_provider` 和 `model`。
2. 在对应的 `[model_providers.<name>]` 中读取当前 `base_url`，保存为代理的上游地址。
3. 如果配置了 `model_catalog_json`，按该值定位 catalog；相对路径按 `~/.codex/` 解析。
4. 修改前分别创建带时间戳的备份。

如果现有 `base_url` 已经是 `http://127.0.0.1:19100`，应从既有部署信息或备份中确认真正的上游地址，绝不能把代理自身设为上游。

### 2. 只做两项条件修改

**config.toml：**只把当前 provider 的 `base_url` 改为：

```toml
base_url = "http://127.0.0.1:19100"
```

不要修改 provider 名、`model`、`wire_api`、`requires_openai_auth`、认证配置或其他设置。

**model catalog：**找到与当前 `model` 对应的条目，只在它明确配置为：

```json
"input_modalities": ["text"]
```

时追加 `image`：

```json
"input_modalities": ["text", "image"]
```

- 字段不存在：不修改。
- 已经包含 `image`：不修改。
- 不新增模型，不修改 slug、模型名、`display_name` 或其他能力字段。

应使用 TOML/JSON 解析器进行结构化编辑，不能用不受约束的文本替换。

### 3. 部署代理与视觉配置

将以下运行文件复制到一个稳定的用户目录，例如：

```text
~/.local/share/codex-deepseek-vision/
├── deepseek-vision-proxy.py
└── vision_client.py
```

将 `.env.example` 复制为：

```text
~/.config/codex-deepseek-vision/env
```

只填写视觉 API 配置，并限制读取权限：

```bash
chmod 600 ~/.config/codex-deepseek-vision/env
```

先在前台启动验证。`--upstream` 必须使用第 1 步记录的原始 `base_url`：

```bash
python3 ~/.local/share/codex-deepseek-vision/deepseek-vision-proxy.py \
  --port 19100 \
  --upstream "原始 DeepSeek base_url" \
  --env-file ~/.config/codex-deepseek-vision/env
```

代理监听 `127.0.0.1`，不会向局域网开放端口。

### 4. 配置简单的 launchd 用户服务

前台验证通过后，Agent 可以创建 `~/Library/LaunchAgents/com.codex.deepseek-vision-proxy.plist`。plist 只需包含：

- 当前 Python 3 的绝对路径
- 代理脚本绝对路径
- `--port 19100`
- `--upstream` 与修改前记录的原始上游地址
- `--env-file` 的绝对路径
- `RunAtLoad` 和 `KeepAlive`
- 标准输出/错误日志路径

不要把任何 API key 写进 plist。用下面的最小流程加载服务：

```bash
launchctl bootout "gui/$(id -u)/com.codex.deepseek-vision-proxy" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" ~/Library/LaunchAgents/com.codex.deepseek-vision-proxy.plist
launchctl kickstart -k "gui/$(id -u)/com.codex.deepseek-vision-proxy"
```

不需要迁移旧服务、事务式安装或复杂自动回滚。失败时保留备份并直接修正明确的问题。

### 5. 重启 Codex 并验证

至少完成以下检查：

```bash
nc -z 127.0.0.1 19100
python3 test_image_rewrite_shapes.py
python3 smoke_test_proxy.py
python3 test_vision_client.py
```

然后重启 Codex，要求当前 DeepSeek 对一张本地图片调用 `view_image`，确认：

1. `view_image` 成功返回，而不是 modality 拒绝错误。
2. 代理调用视觉 API，并把图片描述交给 DeepSeek。
3. DeepSeek 能基于图片内容回答。
4. 普通文本、认证和流式输出仍正常。

## 配置

视觉 env 只包含：

| 变量 | 必需 | 说明 |
|---|---:|---|
| `VISION_API_KEY` | 是 | 视觉 API key |
| `VISION_BASE_URL` | 是 | OpenAI-compatible API 根地址 |
| `VISION_MODEL` | 是 | 视觉模型名 |

DeepSeek 的认证继续由 Codex 发送并由代理透传，不要在 env 中重复保存。

## 可选：glance

`glance` 是独立工具，不是代理回退路径。它复用同一份视觉配置：

```bash
CODEX_DEEPSEEK_VISION_ENV=~/.config/codex-deepseek-vision/env python3 bin/glance screenshot.png
CODEX_DEEPSEEK_VISION_ENV=~/.config/codex-deepseek-vision/env python3 bin/glance screenshot.png -q "这个报错应该怎么修？"
CODEX_DEEPSEEK_VISION_ENV=~/.config/codex-deepseek-vision/env python3 bin/glance screenshot.png --ocr
```

如需全局命令，Agent 可以在 `~/.local/bin/glance` 创建一个调用仓库内 `bin/glance` 的简单 wrapper，但不得覆盖用户已有的同名命令。

## 可选兼容功能

以下行为与图片主链路无关，默认关闭；只有确认上游确实需要时才在 launchd 参数中启用：

- `--codex-header-compat`：调整部分 Codex 身份请求头。
- `--inject-reasoning-summary`：将兼容的 reasoning 内容注入 summary；该模式可能需要缓冲对应响应。

## 工作原理

```text
Codex -> 127.0.0.1:19100 -> 用户原有的 DeepSeek 上游
             |
             +-- 请求含图片时：视觉 API -> 文字描述 -> 替换图片
```

第一次模型响应只要求 Codex 调用 `view_image`。Codex 在本机执行工具后，第二次请求才携带图片；代理在这个请求方向完成图片转文字。若 catalog 明确声明仅支持 `text`，Codex 的 handler 会先拒绝工具，因此只在这一种情况下给现有条目追加 `image`。

## 常见问题

### `base_url` 指向本地代理后，代理也需要配置 DeepSeek API key 吗？

不需要。访问 DeepSeek 上游的网络请求虽然由 `127.0.0.1:19100` 的代理进程发出，但 DeepSeek API key 仍由 Codex 按原有配置放在 `Authorization` 请求头中，代理会将这个请求头原样转发给 DeepSeek：

```text
Codex（携带原有 Authorization）
  -> 127.0.0.1:19100
  -> DeepSeek 上游（原样收到 Authorization）
```

因此不要修改 Codex 原有的认证配置，也不要在代理 env 中重复保存 `DEEPSEEK_API_KEY`。代理 env 只需配置 `VISION_API_KEY`、`VISION_BASE_URL` 和 `VISION_MODEL`。

## 文件清单

| 文件 | 作用 |
|---|---|
| `deepseek-vision-proxy.py` | 本地图片改写代理与 SSE 转发 |
| `vision_client.py` | 代理与 `glance` 共用的视觉 API 客户端 |
| `bin/glance` | 可选的图片描述、问答和 OCR CLI |
| `test_image_rewrite_shapes.py` | 图片结构、并发、缓存及失败行为测试 |
| `smoke_test_proxy.py` | 代理透传、鉴权和流式协议测试 |
| `test_vision_client.py` | 视觉客户端重试与 `glance` 测试 |

## 限制

- 当前文档只覆盖 macOS。
- 这是图片转文字代理，不会把视觉 token 直接交给 DeepSeek。
- 图片描述质量取决于所配置的视觉模型。
- 缓存只存在于代理进程内，重启后清空。
