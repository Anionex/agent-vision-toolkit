# Codex Agent 安装说明（macOS）

开始前先完整阅读 [README.md](README.md)，理解项目用途、工作原理和限制。本说明用于指导 Codex Agent 根据用户机器上的真实配置完成部署，不是固定路径的一键安装脚本。

## 目标与边界

用户的 DeepSeek 必须已经能在 Codex 中正常对话。部署只补充图片转文字代理，不重建用户现有的 DeepSeek 配置。

- 保留现有模型、slug、`display_name`、provider、鉴权方式和 DeepSeek key。
- 不新增模型，不使用模型别名或模型名映射。
- 不要求 `DEEPSEEK_API_KEY`；Codex 原有的 `Authorization` 由代理原样转发。
- `config.toml` 只把当前 provider 的 `base_url` 指向 `http://127.0.0.1:19100`。
- model catalog 只有在当前条目的 `input_modalities` 明确为 `["text"]` 时才追加 `"image"`。
- 修改配置前必须备份，并使用 TOML/JSON 解析器结构化编辑。
- 不修改 `assets/` 下的效果图。

## 前置条件

- macOS
- 已经能正常使用 DeepSeek 的 Codex
- Python 3.11+
- 一个支持 `/chat/completions` 和 `image_url` 的 OpenAI-compatible 视觉 API

## 1. 定位并备份现有配置

读取 `~/.codex/config.toml`：

1. 读取顶层 `model_provider` 和 `model`。
2. 在对应的 `[model_providers.<name>]` 中读取当前 `base_url`，保存为代理的真实上游地址。
3. 如果配置了 `model_catalog_json`，按该值定位 catalog；相对路径按 `~/.codex/` 解析。
4. 为将要修改的 `config.toml` 和 catalog 分别创建带时间戳的备份。

如果当前 `base_url` 已经是 `http://127.0.0.1:19100`，必须从既有部署信息或备份中确认真正的上游地址，不能把代理自身设为上游。

## 2. 部署代理与视觉配置

将运行文件复制到稳定的用户目录，例如：

```text
~/.local/share/codex-deepseek-vision/
├── deepseek-vision-proxy.py
└── vision_client.py
```

将 `.env.example` 复制为：

```text
~/.config/codex-deepseek-vision/env
```

只填写以下视觉 API 配置：

```dotenv
VISION_API_KEY=...
VISION_BASE_URL=...
VISION_MODEL=...
```

限制文件权限：

```bash
chmod 600 ~/.config/codex-deepseek-vision/env
```

不要在 env 中写入 `DEEPSEEK_API_KEY`。DeepSeek 鉴权仍由 Codex 发送。

## 3. 前台启动代理

`--upstream` 必须使用第 1 步记录的原始 `base_url`：

```bash
python3 ~/.local/share/codex-deepseek-vision/deepseek-vision-proxy.py \
  --port 19100 \
  --upstream "原始 DeepSeek base_url" \
  --env-file ~/.config/codex-deepseek-vision/env
```

确认代理监听 `127.0.0.1:19100`。如果端口已被占用，先确认占用者是否为用户已有的相关代理，不得直接终止未知进程。

## 4. 修改 Codex 配置

### config.toml

只把当前 provider 的 `base_url` 改为：

```toml
base_url = "http://127.0.0.1:19100"
```

不要修改 provider 名、`model`、`wire_api`、`requires_openai_auth`、认证配置或其他设置。

### model catalog

找到与当前 `model` 对应的条目。只在它明确配置为：

```json
"input_modalities": ["text"]
```

时追加 `image`：

```json
"input_modalities": ["text", "image"]
```

- 字段不存在：不修改。
- 已经包含 `image`：不修改。
- 不修改 slug、模型名、`display_name` 或其他能力字段。

## 5. 配置简单的 launchd 用户服务

前台验证通过后，创建 `~/Library/LaunchAgents/com.codex.deepseek-vision-proxy.plist`。plist 只需包含：

- 当前 Python 3 的绝对路径
- 代理脚本绝对路径
- `--port 19100`
- `--upstream` 与修改前记录的原始上游地址
- `--env-file` 的绝对路径
- `RunAtLoad` 和 `KeepAlive`
- 标准输出和错误日志路径

不要把任何 API key 写进 plist。加载服务：

```bash
launchctl bootout "gui/$(id -u)/com.codex.deepseek-vision-proxy" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" ~/Library/LaunchAgents/com.codex.deepseek-vision-proxy.plist
launchctl kickstart -k "gui/$(id -u)/com.codex.deepseek-vision-proxy"
```

不需要迁移旧服务、事务式安装或复杂自动回滚。失败时保留备份并修正明确的问题。

## 6. 验证

运行仓库内的核心测试：

```bash
python3 -m py_compile deepseek-vision-proxy.py vision_client.py bin/glance
python3 test_image_rewrite_shapes.py
python3 smoke_test_proxy.py
python3 test_vision_client.py
git diff --check
```

检查服务：

```bash
nc -z 127.0.0.1 19100
launchctl print "gui/$(id -u)/com.codex.deepseek-vision-proxy"
```

完全重启 Codex，然后要求当前 DeepSeek 对一张本地图片实际调用 `view_image`，确认：

1. `view_image` 成功返回，而不是 modality 拒绝错误。
2. 代理调用视觉 API，并把图片描述交给 DeepSeek。
3. DeepSeek 能基于图片内容回答。
4. 普通文本、原有模型名、鉴权和流式输出仍正常。

完成后向用户报告：备份路径、实际修改的字段、服务状态和真实 `view_image` 验证结果。不得输出任何 API key。

## 可选：glance

`glance` 是独立附加功能，不是代理回退路径。用户需要时，可以为其创建一个调用仓库内 `bin/glance` 的简单 wrapper，并复用同一份视觉 env。不得覆盖用户已有的同名命令。

## 可选：ground

`ground` 用自然语言定位图片中的对象或区域，并输出原图像素坐标下的边界框。它不是代理链路的一部分，复用 `~/.config/codex-deepseek-vision/env` 中的 `VISION_*` 配置，不需要新的凭证。

用户需要时：

1. 将 `ground.py` 和 `bin/ground` 一并复制到 `~/.local/share/codex-deepseek-vision/` 对应位置。
2. 用 `uv` 创建只供 `ground` 使用的隔离环境并安装唯一的额外依赖：

   ```bash
   uv venv ~/.local/share/codex-deepseek-vision/.venv-ground
   uv pip install --python ~/.local/share/codex-deepseek-vision/.venv-ground/bin/python pillow
   ```

3. 确认用户没有同名命令后，在 `~/.local/bin/ground` 创建简单 wrapper：

   ```sh
   #!/bin/sh
   exec "$HOME/.local/share/codex-deepseek-vision/.venv-ground/bin/python" \
     "$HOME/.local/share/codex-deepseek-vision/bin/ground" "$@"
   ```

   设置可执行权限，并确保 `~/.local/bin` 在 `PATH` 中。不得覆盖用户已有的同名命令。
4. 验证：

   ```bash
   ground --help
   ground /path/to/image.png "目标描述"
   ```

## 可选兼容功能

以下功能默认关闭，只有确认上游确实需要时才启用：

- `--codex-header-compat`：调整部分 Codex 身份请求头。
- `--inject-reasoning-summary`：注入兼容的 reasoning summary；该模式可能缓冲对应响应。

## 故障排查

| 现象 | 检查 |
|---|---|
| `view_image is not allowed because you do not support image inputs` | 检查当前 catalog 条目是否明确为仅 `text`；若是，只追加 `image` 后重启 Codex |
| 视觉 API 返回 429/5xx | 查看代理错误日志；代理只做有限重试，最终失败应明确返回错误 |
| 端口未监听 | 检查 `launchctl print`、Python 路径、脚本路径、env 路径和端口占用 |
| 改配置后未生效 | 完全退出并重启 Codex 桌面 app |
| DeepSeek 返回鉴权错误 | 确认 Codex 仍发送原有 `Authorization`，且代理没有删除或替换该请求头 |
