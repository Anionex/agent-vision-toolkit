# codex-deepseek-vision

让 Codex 中的纯文本 DeepSeek 模型可靠处理粘贴图片和内置 `view_image`：本地代理先调用一个 OpenAI-compatible 视觉 API 获取文字描述，再把图片替换为文字后转发给 DeepSeek。

默认只执行图片改写。UA/请求头兼容和 reasoning summary 修复均为显式可选功能，不会悄悄改变请求行为。

## 实际效果

<p align="center">
  <img src="assets/effect-1.jpg" alt="Codex 里的 DeepSeek 看 UI 图回答风格问题" width="49%">
  <img src="assets/effect-2.jpg" alt="Codex 里的 DeepSeek 看图排查界面字段不一致 bug" width="49%">
</p>

<p align="center">真实 Codex 会话截图（模型：DeepSeek V4 Flash Max）：左图是让模型对着 UI 截图回答"这是什么风格"，右图是让模型对着界面截图排查字段 bug。</p>

## 特性

- 粘贴图片与 `view_image` 两种 Codex 请求结构都支持。
- 同一请求的多张图片并发描述。
- 进程内最多缓存 128 张图片描述。
- 视觉失败时明确返回错误，绝不把 429/错误文本伪装成图片描述。
- 默认逐块转发 DeepSeek SSE 响应。
- 不记录完整请求体、图片、对话或 API key。
- `.env` 安装到用户配置目录并设为 `0600`；launchd plist 不包含密钥。
- 可选安装独立 `glance` CLI，直接进行图片描述、图片问答和 OCR。

## 前置条件

- macOS + Codex 桌面 app
- Python 3.11+
- DeepSeek API key
- 一个支持 `/chat/completions` 和 `image_url` 的 OpenAI-compatible 视觉 API key

代理仅使用 Python 标准库。安装和验证使用 macOS 自带的 shell、launchctl 及 Python。

## 快速开始

```bash
git clone https://github.com/Anionex/codex-deepseek-vision.git
cd codex-deepseek-vision
cp .env.example .env
# 编辑 .env，至少填写 DEEPSEEK_API_KEY 和 VISION_API_KEY
./install.sh
```

重启 Codex 桌面 app，然后验证：

```bash
./verify.sh
./verify.sh /path/to/image.png  # 可选：真实 API 全链路
```

安装器会：

1. 将运行文件安装到 `~/.local/share/codex-deepseek-vision/`。
2. 将 `.env` 复制到 `~/.config/codex-deepseek-vision/env` 并设置权限 `0600`。
3. 生成不含密钥的 launchd 服务。
4. 备份后更新 Codex config 和 model catalog。
5. 添加模型 slug `deepseek-v4-flash-vision`，显示名保持 `DeepSeek V4 Flash`。

## 可选：安装 glance

`glance` 是独立命令，不参与代理的图片改写，也不是代理回退路径。它用于 Codex 之外的直接图片问答：

```bash
./install.sh --with-glance

glance screenshot.png
glance screenshot.png -q "这个报错应该怎么修？"
glance screenshot.png --ocr
glance screenshot.png --ocr "排除日期"
```

默认安装到 `~/.local/bin/glance`；如有需要，把 `~/.local/bin` 加入 `PATH`。

## 配置

`.env` 中的重要变量：

| 变量 | 必需 | 默认示例 | 说明 |
|---|---:|---|---|
| `DEEPSEEK_API_KEY` | 是 | 空 | 代理注入到 DeepSeek 上游请求 |
| `DEEPSEEK_BASE_URL` | 否 | `https://api.deepseek.com` | DeepSeek Responses API 根地址 |
| `UPSTREAM_MODEL` | 否 | `deepseek-v4-flash` | 实际上游模型 |
| `VISION_API_KEY` | 是 | 空 | 视觉 API key |
| `VISION_BASE_URL` | 是 | 示例为 Inferera | OpenAI-compatible API 根地址 |
| `VISION_MODEL` | 是 | 示例为 `gemini-3.6-flash` | 视觉模型名 |
| `MODEL_SLUG` | 否 | `deepseek-v4-flash-vision` | Codex catalog 内部标识 |
| `PORT` | 否 | `19100` | 本地监听端口 |

修改已安装配置后，重新运行 `./install.sh` 使 launchd 重启并生效。

## 可选兼容功能

这些功能与视觉无关，因此默认关闭：

```bash
# 去掉 Codex 身份请求头，用通用 UA 转发；仅在上游强制思考时开启
./install.sh --codex-header-compat

# 将 DeepSeek reasoning text 写入 Codex summary；开启后该响应会被缓冲
./install.sh --inject-reasoning-summary

# 两者同时开启
./install.sh --codex-header-compat --inject-reasoning-summary
```

模型映射由安装器显式传给代理，不再使用隐藏的 `gpt-5.2` 默认映射。

## 工作原理

1. catalog 把代理模型声明为支持 `text` 和 `image`，Codex 因而允许 `view_image`。
2. Codex 将图片作为 `input_image` 发送到 `127.0.0.1:19100`。
3. 代理并发调用视觉 API，并将图片替换为 `[local vision model description] ...`。
4. 代理把 catalog slug 映射为真正的 DeepSeek 模型名并转发。
5. 默认逐块转发 DeepSeek SSE 响应；只有 reasoning summary 开关需要缓冲响应。

DeepSeek 本身仍然只接收文本；回答质量取决于视觉模型生成的描述。

## 验证与开发

```bash
python3 -m py_compile deepseek-vision-proxy.py vision_client.py bin/glance
python3 test_image_rewrite_shapes.py
python3 smoke_test_proxy.py
python3 test_vision_client.py
python3 test_install.py
./verify.sh
```

`verify.sh` 检查代理端口、Codex TOML、catalog 图像模态和密钥文件权限。传入图片后才会产生真实 API 调用。

## 故障排查

| 现象 | 处理 |
|---|---|
| `view_image is not allowed...` | 运行 `./verify.sh` 检查 catalog 的 `image` 模态，然后重启 Codex |
| 视觉 API 429/5xx | 查看 `~/.codex/log/deepseek-vision-proxy.log`；代理会有限重试并返回明确错误 |
| 端口未监听 | `launchctl print gui/$(id -u)/com.codex.deepseek-vision-proxy` |
| 改配置后没生效 | 重跑 `./install.sh` 并重启 Codex |
| `glance` 找不到 | 把 `~/.local/bin` 加入 `PATH` |

## 卸载

```bash
./uninstall.sh
```

卸载器只移除代理服务、运行文件及由本项目安装的 glance wrapper，不猜测应该恢复哪一份 Codex 配置。运行后请恢复安装时生成的 `~/.codex/config.toml.bak-<时间戳>` 和对应 catalog 备份，再重启 Codex。

## 文件清单

| 文件 | 作用 |
|---|---|
| `deepseek-vision-proxy.py` | 默认只做图片改写并逐块转发响应的本地代理 |
| `vision_client.py` | 代理与 glance 共用的视觉 API 客户端 |
| `bin/glance` | 可选安装的独立图片描述/问答/OCR CLI |
| `install.sh` / `uninstall.sh` | 幂等安装与安全卸载 |
| `verify.sh` | 本机状态和可选真实图片验证 |
| `catalog-model.template.json` | Codex 模型模板；显示名为 `DeepSeek V4 Flash` |

## 限制

- 这是图片转文字代理，不是真正把视觉 token 交给 DeepSeek。
- 缓存仅在代理进程内有效；重启后清空。
- 当前安装流程针对 macOS Codex 桌面 app。
- 开启 reasoning summary 兼容时需要缓冲对应 SSE 响应；默认关闭时保持逐块转发。
