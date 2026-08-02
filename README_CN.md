<div align="center">

# codex-deepseek-vision

🌐 **语言 / Language**：**中文** ｜ [**English**](README.md)

</div>

如果你的 Codex 已经接入 DeepSeek ，却烦恼于模型没有多模态，不能看图、每次调用看图都会被系统拦下，本仓库提供了一种方式，可以在不引入额外mcp、skills、cli的情况下，让纯文本模型调用codex内置view image的时候不报错，而是给出图片的详细描述，尽量让纯文本模型的交互体验和多模态模型的交互体验保持一致，免去反复配置的风险。同时也提供可选的视觉工具包，利用多模态模型的能力完成图片问答、ocr、视觉定位等操作。

所有代码均已在真实 Codex + DeepSeek 会话中验证过。可用场景包括但不限于：图片问答，截图分析，Computer Use GUI界面操作，多步图像推理

> 如果项目对你有用，欢迎 star🌟 & follow～，我会分享更多的实用工具和技巧
> 
## 实际效果

<p align="center">
  <img src="assets/effect-1.jpg" alt="Codex 里的 DeepSeek 看 UI 图回答风格问题" width="49%">
  <img src="assets/effect-2.jpg" alt="Codex 里的 DeepSeek 看图排查界面字段不一致 bug" width="49%">
</p>

*左：DeepSeek V4 回答 UI 背景风格问题并对比相近风格；右：DeepSeek V4 根据截图排查字段名称不符预期的 bug。*

<p align="center">
  <img src="assets/effect-3.jpg" alt="安装 glance 后的多轮图片问答" width="49%">
  <img src="assets/effect-4.jpg" alt="DeepSeek V4 用 glance/ground 定位屏幕元素自主游玩国际象棋" width="49%">
</p>

*左：安装可选 `glance` 后的多轮图片问答；右：安装 `ground` 后，DeepSeek V4 定位屏幕视觉元素，自主游玩国际象棋。*

## 亮点

- **贴图和 `view_image` 都支持**：直接粘贴图片（`message.content`）和模型调用 `view_image`（`function_call_output.output`）两种结构都能看图
- **多图并行看图**：一次请求里的多张图并发调用视觉模型，N 张图约等于 1 张图的延迟，不必逐张等待。
- **同图只调一次**：按图片 sha256 缓存描述，同一张图反复出现不重复调用视觉 API，缓存命中近乎零延迟。
- **可选 `glance`**：简洁的独立cli工具，用于image qa 或 OCR，以提供更加灵活的图片理解能力。
- **可选 `ground`**：用自然语言定位图片中的目标，输出原图像素坐标下的边界框。
- **后续可能加入的更多视觉工具** 

## 使用方式

本仓库不提供通用一键安装器。推荐把仓库链接交给 Codex Agent：

> 我已经在 Codex 中接入并可正常使用 DeepSeek。请先阅读这个仓库的 README，再按照 AGENT_INSTALL.md 根据当前系统部署并验证 `view_image`。

详细执行步骤见 **[Codex Agent 安装说明](AGENT_INSTALL.md)**。安装完成并重启 Codex 后，直接粘贴图片或让 DeepSeek 调用内置 `view_image` 即可。

## 前置条件

- 已可正常使用 DeepSeek 的 Codex
- Python 3.11+
- 一个支持 `/chat/completions` 与 `image_url` 的 OpenAI-compatible 视觉 API

## 配置

env 只需配置：

| 变量 | 必需 | 说明 |
|---|---:|---|
| `VISION_API_KEY` | 是 | 多模态模型的 API key |
| `VISION_BASE_URL` | 是 | OpenAI-compatible API 地址 |
| `VISION_MODEL` | 是 | 多模态模型名 |
| `LANG` | 否 | 视觉模型输出语言：`zh`=中文，`en`=English（默认 `zh`） |

DeepSeek 的认证继续由 Codex 发送并由代理透传，不需要在 env 中重复保存。

## 可选工具：glance 

`glance` 是独立cli工具。它用于直接对图片发起提问，补充特定细节。

需要全局命令时，可让 Codex 按照安装说明创建 wrapper。得到更简洁的调用形式如下：

```bash
glance screenshot.png -q "这张图片的主色调是什么？"
glance screenshot.png --ocr 
```

回答：
```
这张图片的主色调为**白色和浅灰色，局部带淡蓝色。**
```

```
用户名
密码
登录
```

## 可选工具：ground

`ground` 是独立cli工具，用于定位图片中的对象或区域：

```bash
ground screenshot.png "发送按钮"
```

```
x1: 1067, y1: 841, x2: 1108, y2: 881
```

每次只分析一张完整图片，并输出目标在原图中的像素坐标。

## 安装 Codex skill（可选）

安装额外视觉工具包的方式之一，是安装仓库内附带的 `vision-tools` skill：它告诉 Codex `glance`/`ground` 是什么以及怎么用。使用官方 skills CLI 安装：

```bash
npx skills add Anionex/codex-deepseek-vision --skill vision-tools -a codex -g --copy -y
```

也可以手动复制：

```bash
cp -r skills/vision-tools ~/.codex/skills/
```

之后重启 Codex 生效。

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
| `ground.py` / `bin/ground` | 可选的图片目标定位 CLI |
| `AGENT_INSTALL.md` | Codex Agent 的安装与验证步骤 |
| `tests/test_image_rewrite_shapes.py` | 图片结构、并发、缓存及失败行为测试 |
| `tests/smoke_test_proxy.py` | 代理透传、鉴权和流式协议测试 |
| `tests/test_vision_client.py` | 视觉客户端重试与 `glance` 测试 |
| `tests/test_ground.py` | `ground` 坐标解析和共享配置测试 |

## 限制

- 这是图片转文字代理，不会把视觉 token 直接交给 DeepSeek。
- 图片描述质量取决于所配置的视觉模型。
- 缓存只存在于代理进程内，重启后清空。

---
Made by [Anionex](https://github.com/Anionex) with codex
