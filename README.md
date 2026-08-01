# codex-deepseek-vision

让 Codex 桌面 app 里的 **DeepSeek** 模型获得看图能力：`view_image` 不再返回失败或不可解析的图像数据，模型拿到的是一段**有效的自然语言图片描述**。

原理一句话：Codex 发给 DeepSeek 的请求先经过本仓库部署的本地代理（127.0.0.1:19100），代理检测到请求里的图片（`input_image` data URL）时，用本地视觉 CLI（`glance`，gemini-3.5-flash）生成描述文本，替换后转发给 DeepSeek。模型"看到"的就是这段文本。

```
Codex 调 view_image → 拿到 data URL → 请求带图 → 本地代理
        → glance 生成文本描述 → 替换 input_image → DeepSeek 正常回答图片内容
```

所有代码均已在真实 Codex + DeepSeek 会话中验证过。

---

## 前置条件

- macOS + Codex 桌面 app（0.146+）
- DeepSeek API key（`api.deepseek.com`）
- Python 3.10+
- 本地视觉 CLI `glance`：`/usr/local/bin/glance <图片>` 能输出图片描述（它调用 gemini-3.5-flash；没有的话用 `--glance-cmd` 指到任何"吃图片路径、输出文本"的命令，比如 OCR 工具）

## 快速开始

```bash
git clone <本仓库> && cd codex-deepseek-vision
./install.sh            # 备份并改写：代理脚本、launchd、模型 catalog、Codex config
```

然后**重启 Codex 桌面 app**（app 在启动时缓存 config，不重启不生效）。

验证：

```bash
./verify.sh <任意图片路径>    # 全链路检查 + 真实图片往返
```

预期输出末尾：

```
deepseek answer: 这张图片展示的是...
PASS: image was described via the glance rewrite chain
ALL CHECKS PASSED
```

之后在 Codex 里发一张图，或让模型调用 `view_image <路径>`，模型就能描述图片内容了。

## 验证命令

| 命令 | 检查内容 |
|---|---|
| `./verify.sh` | 代理存活、catalog 模型含 image 模态、config 指向代理 |
| `./verify.sh <图片>` | 上述 + 真实"带图请求 → glance → DeepSeek"往返（需 API key） |
| `python3 smoke_test_proxy.py` | 本地 echo 冒烟：UA 改写、Codex 头剥离、body 透传（不需要 key，不改任何配置） |
| `tail ~/.codex/launchers/deepseek-ua-rewrite-proxy.err.log` | 代理日志，出现 `image -> glance (desc_len=..., cache=N)` 即改写生效 |

API key 解析顺序：环境变量 `DEEPSEEK_API_KEY` → `--key-cmd`（shell 命令打印 key）。

## 安装脚本做了什么

`install.sh` 是幂等的，每步修改前都会备份（`*.bak-<时间戳>`）：

1. 复制 `deepseek-ua-rewrite-proxy.py` 到 `~/.codex/launchers/`
2. 从 `launchd.plist.template` 生成并加载 launchd 常驻服务（KeepAlive，端口 19100）
3. 把 `catalog-model.template.json` 的模型条目合并进 `~/.codex/cc-switch-model-catalog.json`（slug 已存在则只补齐缺失字段）
4. 把 `~/.codex/config.toml` 指向本地代理（`model_provider="custom"`、`model="gpt-5.2"`、`base_url=http://127.0.0.1:19100`、`wire_api="responses"`）

## 配置参考

### 代理参数

| 参数 | 默认值 | 说明 |
|---|---|---|
| `--port` | `19100` | 监听端口 |
| `--upstream` | `https://api.deepseek.com` | 上游地址 |
| `--glance-cmd` | `/usr/local/bin/glance` | 图片 → 文本描述的本地命令 |
| `--model-map SLUG=UPSTREAM` | `gpt-5.2=deepseek-v4-flash` | 模型名映射，可重复传 |
| `--log PATH` | 空（stderr） | 日志文件 |

### 环境变量

| 变量 | 说明 |
|---|---|
| `CODEX_HOME` | 默认 `~/.codex` |
| `DEEPSEEK_API_KEY` | 验证脚本用；不设则用 `--key-cmd` |

### 关键文件

| 文件 | 作用 |
|---|---|
| `~/.codex/config.toml` | Codex 客户端配置（model / base_url / wire_api） |
| `~/.codex/cc-switch-model-catalog.json` | 模型目录；`input_modalities` 必须含 `image`，`view_image` 检查才通过 |
| `~/.codex/launchers/deepseek-ua-rewrite-proxy.py` | 代理本体 |
| `~/Library/LaunchAgents/com.codex.deepseek-ua-rewrite-proxy.plist` | launchd 常驻配置 |

## 原理

1. catalog 模型声明 `input_modalities: ["text","image"]` → app-server 认为模型支持图像 → `view_image` 检查通过，返回 data URL。
2. 模型把 data URL 作为 `input_image` 放进请求 → 请求经 127.0.0.1:19100。
3. 代理解码图片 → 临时文件 → 调 `glance` 拿文本描述（按 data URL sha256 缓存，同图只调一次）→ 把 `input_image` 替换成 `[local vision model description] <描述>` 的 `input_text`。
4. DeepSeek 收到的是文本，正常回答图片内容。

补充：DeepSeek V4 系列 API 层面接受 `input_image` 但实际看不到图（实测返回 "I'm unable to see the image"），所以必须走上面的改写。代理同时承担了 Codex 链路必需的 UA 改写/头剥离（否则 DeepSeek 强制开启思考）。

## 故障排查

| 现象 | 原因 | 处理 |
|---|---|---|
| `view_image is not allowed because you do not support image inputs` | catalog 模型缺 `image` 模态 | 重跑 `./install.sh` 或手动检查 catalog；`verify.sh` 第 2 步会报 |
| 响应仍是 `I'm unable to see the image` | `input_image` 未被替换 | 看代理日志 `glance failed`；单独跑 `glance <图>` 复现 |
| 代理没起来 | launchd 未加载 / 端口占用 | `launchctl kickstart -k gui/$(id -u)/com.codex.deepseek-ua-rewrite-proxy`；`lsof -nP -iTCP:19100` |
| 模型不调 `view_image` | 工具被过滤（模型无 image 模态） | 同上，先修 catalog |
| 改了配置没效果 | 桌面 app 缓存旧 config | 重启 Codex 桌面 app |
| 缓存不命中 | app-server 对图片重新编码，data URL 每次不同 | 属预期；同 URL 才命中 |

## 卸载

```bash
launchctl bootout gui/$(id -u)/com.codex.deepseek-ua-rewrite-proxy
rm ~/Library/LaunchAgents/com.codex.deepseek-ua-rewrite-proxy.plist
# 恢复 config.toml / catalog 请用 install.sh 生成的 *.bak-<时间戳> 备份
```

## 文件清单

| 文件 | 说明 |
|---|---|
| `deepseek-ua-rewrite-proxy.py` | 代理本体（UA 改写 + 模型映射 + 图像→glance 改写 + 缓存） |
| `install.sh` | 一键安装（备份优先） |
| `verify.sh` | 全链路验证 |
| `test_view_image_chain.py` | 单发"带图请求"验证（`--proxy/--model/--key-cmd` 可配） |
| `smoke_test_proxy.py` | 本地 echo 冒烟（不需要 key） |
| `launchd.plist.template` | launchd 模板（`__PYTHON__`/`__SCRIPT__`/`__PORT__`/`__LOG__` 占位符） |
| `catalog-model.template.json` | catalog 模型条目模板（含 image 模态 + none/high 思考档） |
