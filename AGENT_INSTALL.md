# Codex Agent 安装说明

开始前先完整阅读 [README.md](README.md)，理解项目用途、工作原理和限制。本说明用于指导 Codex Agent 根据用户机器上的真实配置完成部署，不是固定路径的一键安装脚本。

代理、Codex 配置修改和验证流程与操作系统无关。平台差异只存在于文件路径、后台常驻方式和可选 CLI wrapper。

## 目标与边界

用户的 DeepSeek 必须已经能在 Codex 中正常对话。部署只补充图片转文字代理，不重建用户现有的 DeepSeek 配置。

- 保留现有模型、slug、`display_name`、provider、鉴权方式和 DeepSeek key。
- 不新增模型，也不主动改写用户的模型配置。代理兼容既有的 `gpt-5.2` 显示别名，并在转发时将其映射为 `deepseek-v4-flash`。
- 不要求 `DEEPSEEK_API_KEY`；Codex 原有的 `Authorization` 由代理原样转发。
- `config.toml` 只把当前 provider 的 `base_url` 指向 `http://127.0.0.1:19100`。
- model catalog 只有在当前条目的 `input_modalities` 明确为 `["text"]` 时才追加 `"image"`。
- 修改配置前必须备份，并使用 TOML/JSON 解析器结构化编辑。
- 不修改 `assets/` 下的效果图。

## 前置条件

- 已经能正常使用 DeepSeek 的 Codex
- Python 3.11+
- 一个支持 `/chat/completions` 和 `image_url` 的 OpenAI-compatible 视觉 API

## 1. 定位并备份现有配置

Codex 配置目录默认位于当前用户主目录下的 `.codex`。如用户设置了 `CODEX_HOME`，以该值为准。

读取其中的 `config.toml`：

1. 读取顶层 `model_provider` 和 `model`。
2. 在对应的 `[model_providers.<name>]` 中读取当前 `base_url`，保存为代理的真实上游地址。
3. 如果配置了 `model_catalog_json`，按该值定位 catalog；相对路径按 Codex 配置目录解析。
4. 为将要修改的 `config.toml` 和 catalog 分别创建带时间戳的备份。

如果当前 `base_url` 已经是 `http://127.0.0.1:19100`，必须从既有部署信息或备份中确认真正的上游地址，不能把代理自身设为上游。

## 2. 准备运行目录与视觉配置

选择当前用户可写的稳定目录。推荐值：

| 系统 | `INSTALL_DIR` | `ENV_FILE` |
|---|---|---|
| macOS / Linux | `~/.local/share/codex-vision-proxy` | `~/.config/codex-vision-proxy/env` |
| Windows | `%LOCALAPPDATA%\codex-vision-proxy` | `%LOCALAPPDATA%\codex-vision-proxy\env` |

将 `codex-vision-proxy.py` 和 `vision_client.py` 复制到 `INSTALL_DIR`，再把 `.env.example` 复制为 `ENV_FILE`。只填写：

```dotenv
VISION_API_KEY=...
VISION_BASE_URL=...
VISION_MODEL=...
LANG=zh  # 可选：视觉模型输出语言（zh/en），不填保持默认中文
```

不要在 env 中写入 `DEEPSEEK_API_KEY`。DeepSeek 鉴权仍由 Codex 发送。

- macOS / Linux：执行 `chmod 600 <ENV_FILE>`。
- Windows：把 env 保留在当前用户的 `%LOCALAPPDATA%` 下，不复制到公共目录。

## 3. 前台启动代理

先解析当前 Python 的绝对路径。`--upstream` 必须使用第 1 步记录的原始 `base_url`。

macOS / Linux：

```bash
python3 <INSTALL_DIR>/codex-vision-proxy.py \
  --port 19100 \
  --upstream "原始 DeepSeek base_url" \
  --env-file <ENV_FILE>
```

Windows PowerShell：

```powershell
py -3 "<INSTALL_DIR>\codex-vision-proxy.py" --port 19100 --upstream "原始 DeepSeek base_url" --env-file "<ENV_FILE>"
```

尖括号是占位符，执行前必须替换成真实绝对路径。确认代理监听 `127.0.0.1:19100`。如果端口已被占用，先确认占用者是否为用户已有的相关代理，不得直接终止未知进程。

## 4. 修改 Codex 配置

### config.toml

只把当前 provider 的 `base_url` 改为：

```toml
base_url = "http://127.0.0.1:19100"
```

不要修改 provider 名、`model`、`wire_api`、`requires_openai_auth`、认证配置或其他设置。

如果用户原有配置使用 `gpt-5.2` 作为显示别名，继续保留该配置；代理会在请求转发时兼容映射为 `deepseek-v4-flash`。其他模型名仍原样透传。

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

## 5. 设置后台常驻

这一步只负责在用户登录后运行第 3 步已经验证过的命令。启动配置中只能保存脚本路径、参数和 env 文件路径，不能包含 API key。

### macOS

创建 `~/Library/LaunchAgents/com.codex.vision-proxy.plist`，使用当前 Python、`INSTALL_DIR`、`ENV_FILE` 和原始上游地址的绝对路径，并设置 `RunAtLoad`、`KeepAlive` 和日志路径。加载：

```bash
launchctl bootout "gui/$(id -u)/com.codex.vision-proxy" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" ~/Library/LaunchAgents/com.codex.vision-proxy.plist
launchctl kickstart -k "gui/$(id -u)/com.codex.vision-proxy"
```

### Windows

在当前用户的 Startup 目录创建一个 `.cmd` 启动项，内容只调用已验证的代理命令。例如：

```cmd
@echo off
start "Codex Vision Proxy" /min py -3 "%LOCALAPPDATA%\codex-vision-proxy\codex-vision-proxy.py" --port 19100 --upstream "原始 DeepSeek base_url" --env-file "%LOCALAPPDATA%\codex-vision-proxy\env" --log "%LOCALAPPDATA%\codex-vision-proxy\proxy.log"
```

Startup 目录由 PowerShell 的 `[Environment]::GetFolderPath("Startup")` 获取。创建后运行一次该 `.cmd`，确认代理启动。不要把 key 写进 `.cmd`。

### 其他系统

使用系统已有的用户级进程管理器运行相同命令即可，例如 Linux 的 `systemd --user`。不要为此引入新的安装框架。

不需要迁移旧服务、事务式安装或复杂自动回滚。失败时保留备份并修正明确的问题。

### 更新代码或 env 之后

macOS / Linux 上 `kill -HUP <pid>`：代理停止接受新连接，等手上的请求跑完，再原地 exec 自己。pid 不变，进程管理器不会察觉，正在进行的那一轮 Codex 也不会被掐断。先跑第 6 步的测试再发信号——代理带着语法错误 exec 就直接退出了。Windows 没有 SIGHUP，重新运行 `.cmd` 启动项即可。

## 6. 验证

用当前系统的 Python 命令运行仓库内核心测试：

```text
python -m py_compile codex-vision-proxy.py vision_client.py bin/glance bin/trace ground.py detect.py
python tests/test_image_rewrite_shapes.py
python tests/smoke_test_proxy.py
python tests/test_vision_client.py
```

检查端口：

- macOS / Linux：`nc -z 127.0.0.1 19100`
- Windows PowerShell：`Test-NetConnection 127.0.0.1 -Port 19100`

完全重启 Codex，然后要求当前 DeepSeek 对一张本地图片实际调用 `view_image`，确认：

1. `view_image` 成功返回，而不是 modality 拒绝错误。
2. 代理调用视觉 API，并把图片描述交给 DeepSeek。
3. DeepSeek 能基于图片内容回答。
4. 普通文本、原有模型名、鉴权和流式输出仍正常。

完成后向用户报告：备份路径、实际修改的字段、服务状态和真实 `view_image` 验证结果。不得输出任何 API key。

> **对 Agent 的要求**：作为 agent，如果用户没有明确表明需要额外的工具（`glance`、`ground`、`detect`、`trace`），请在回答的最后询问用户是否安装这些额外工具，不要擅自安装。

## 可选：glance

`glance` 是独立附加功能，不是代理回退路径。需要时把 `bin/glance` 复制到 `INSTALL_DIR/bin`，它会复用同目录中的 `vision_client.py` 并自动读取同一份 `VISION_*` 配置。

- macOS / Linux：创建 shell wrapper。
- Windows：创建转发全部参数的 `.cmd` wrapper。

wrapper 必须使用当前系统的绝对 Python 和脚本路径，并放入用户 PATH 中的可写目录（如 macOS / Linux 的 `~/.local/bin`，Windows 的 `%LOCALAPPDATA%\Microsoft\WindowsApps`；若目录不在 PATH，将其加入用户级 PATH），不得覆盖用户已有的同名命令。完成后新开终端即可直接运行 `glance <图片> [选项]`，无需激活任何虚拟环境。

## 可选：ground

`ground` 用自然语言定位图片中的对象或区域，并输出原图像素坐标下的边界框。它不是代理链路的一部分，复用同一份 `VISION_*` 配置，不需要新的凭证。

用户需要时：

1. 将 `ground.py` 和 `bin/ground` 复制到 `INSTALL_DIR` 对应位置。
2. 用 `uv` 在 `INSTALL_DIR/.venv-ground` 创建隔离环境，只安装额外依赖 `pillow`。
3. 创建调用该环境 Python 和 `bin/ground` 的 shell 或 `.cmd` wrapper，放入用户 PATH 中的可写目录（同 glance，如 `~/.local/bin`；若不在 PATH，将其加入用户级 PATH）；不得覆盖用户已有的同名命令。完成后新开终端即可直接运行 `ground <图片> "<目标描述>"`。
4. 验证：`ground /path/to/image.png "目标描述"`。

## 可选：detect

`detect` 盘点图片（或指定区域）中的元素并输出编号清单和原图像素坐标。它与 `ground` 共用实现和 `.venv-ground` 环境。

用户需要时：

1. 将 `detect.py` 和 `bin/detect` 复制到 `INSTALL_DIR` 对应位置（依赖已随 ground 安装的 `ground.py` 与 `pillow`）。
2. 按 ground 相同方式创建 wrapper 放入 PATH；不得覆盖用户已有的同名命令。
3. 验证：`detect /path/to/screenshot.png` 应输出编号元素清单。

## 可选：trace

`trace` 在本地把图片确定性地矢量化为 SVG（精确形状几何），完全不经过视觉 API，也不需要任何 key。

用户需要时：

1. 将 `bin/trace` 复制到 `INSTALL_DIR/bin`。
2. 在 `INSTALL_DIR/.venv-ground`（没有则用 `uv` 创建）中追加安装依赖 `vtracer`（`--region` 功能还需 `pillow`）。
3. 按 glance/ground 相同方式创建 wrapper 放入 PATH；不得覆盖用户已有的同名命令。
4. 验证：`trace /path/to/diagram.png --polygon` 应输出 SVG。

## 可选兼容功能

以下功能默认关闭，只有确认上游确实需要时才启用：

- `--codex-header-compat`：调整部分 Codex 身份请求头。
- `--inject-reasoning-summary`：注入兼容的 reasoning summary；该模式可能缓冲对应响应。

## 故障排查

| 现象 | 检查 |
|---|---|
| `view_image is not allowed because you do not support image inputs` | 检查当前 catalog 条目是否明确为仅 `text`；若是，只追加 `image` 后重启 Codex |
| 视觉 API 返回 429/5xx | 查看代理错误日志；代理只做有限重试，最终失败应明确返回错误 |
| 端口未监听 | 检查 Python、脚本、env、上游地址、后台启动项和端口占用 |
| 改配置后未生效 | 完全退出并重启 Codex |
| DeepSeek 返回鉴权错误 | 确认 Codex 仍发送原有 `Authorization`，且代理没有删除或替换该请求头 |
