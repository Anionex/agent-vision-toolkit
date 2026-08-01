# codex-deepseek-vision

如果你的 Codex 已经接入 DeepSeek ，却烦恼于模型没有多模态，不能看图、每次调用看图都会被系统拦下，本仓库提供了一种方式，可以在不引入额外mcp、skills、cli、其他工具的情况下，让纯文本模型调用codex内置view image的时候不报错，而是给出图片的详细描述，尽量让纯文本模型的交互体验和多模态模型的交互体验保持一致，免去反复配置的风险。同时也提供可选的视觉工具包，利用第多模态模型的能力完成图片问答、ocr、视觉定位等操作。

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
- **可选 `glance`**：简洁的独立cli工具，用于image qa 或 OCR，以提供更加灵活的图片理解能力。

## 使用方式

本仓库不提供通用一键安装器。推荐把仓库链接交给当前 macOS 上的 Codex Agent：

> 我已经在 Codex 中接入并可正常使用 DeepSeek。请先阅读这个仓库的 README，再按照 AGENT_INSTALL.md 在 macOS 上部署并验证 `view_image`。

详细执行步骤见 **[Codex Agent 安装说明](AGENT_INSTALL.md)**。安装完成并重启 Codex 后，直接粘贴图片或让 DeepSeek 调用内置 `view_image` 即可。

## 前置条件

- macOS 和已可正常使用 DeepSeek 的 Codex
- Python 3.11+
- 一个支持 `/chat/completions` 与 `image_url` 的 OpenAI-compatible 视觉 API

## 配置

env 只需配置：

| 变量 | 必需 | 说明 |
|---|---:|---|
| `VISION_API_KEY` | 是 | 多模态模型的 API key |
| `VISION_BASE_URL` | 是 | OpenAI-compatible API 地址 |
| `VISION_MODEL` | 是 | 多模态模型名 |

DeepSeek 的认证继续由 Codex 发送并由代理透传，不需要在 env 中重复保存。

## 可选工具：glance Cli

`glance` 是独立cli工具。配置好proxy后不需要独立再配置凭证。

需要全局命令时，可让 Codex Agent 按照安装说明创建 wrapper。得到更简洁的调用形式如下：

```bash
glance screenshot.png
glance screenshot.png -q "这个报错应该怎么修？"
glance screenshot.png --ocr
```


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
| `AGENT_INSTALL.md` | Codex Agent 的 macOS 安装与验证步骤 |
| `test_image_rewrite_shapes.py` | 图片结构、并发、缓存及失败行为测试 |
| `smoke_test_proxy.py` | 代理透传、鉴权和流式协议测试 |
| `test_vision_client.py` | 视觉客户端重试与 `glance` 测试 |

## 限制

- 当前文档只覆盖 macOS。
- 这是图片转文字代理，不会把视觉 token 直接交给 DeepSeek。
- 图片描述质量取决于所配置的视觉模型。
- 缓存只存在于代理进程内，重启后清空。
