# AGENTS.md — codex-deepseek-vision

面向**已把 DeepSeek 接入 Codex** 的用户，补上"看图能力"的可分发仓库。所有代码已在真实会话验证。

- 用户已有自己的代理/网关时，README 走"情况 B：最小接入"（只并入图像改写三件套），不要全量 install。
- 仓库不捆绑视觉 CLI：`--glance-cmd` 指向任何"图片路径→文本"命令（默认 /usr/local/bin/glance）。
- 仓库不自带任何密钥/凭据：API key 一律来自环境变量或调用方注入。

## 维护约定

- 修改代理脚本后必须跑：`python3 -m py_compile deepseek-ua-rewrite-proxy.py && python3 smoke_test_proxy.py`，有图片时再跑 `./verify.sh <图>`。
- 代理参数化规则：可配置项走 CLI 参数（`--port/--upstream/--glance-cmd/--model-map/--log`），不要硬编码机器特定路径；`install.sh` 负责部署时的路径替换。
- `install.sh` 所有修改前必须备份（`*.bak-<时间戳>`），并且是幂等的。
- 部署版与仓库版同步：`~/.codex/launchers/deepseek-ua-rewrite-proxy.py` 是仓库脚本的实例（加参数部署）；改仓库代码后如需本机生效，重跑 `./install.sh` 或手动同步。

## 关键事实（已验证）

- DeepSeek V4 系列接受 `input_image` 请求但实际看不到图（返回 "I'm unable to see the image"），必须由代理改写为 glance 文本。
- `view_image` 检查通过的前提：catalog 模型 `input_modalities` 含 `image`。
- 内置工具不触发 pre_tool_use hook，无法用 hook 拦截；改请求链路（本仓库方案）是唯一可行路径。
- glance 调用：data URL → 临时文件 → `/usr/local/bin/glance <tmp>` → 文本；sha256(data_url) 缓存。
