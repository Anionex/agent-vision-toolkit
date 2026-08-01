# AGENTS.md — codex-deepseek-vision

让 Codex 桌面 app 里的 DeepSeek 获得看图能力的可分发仓库。所有代码已在真实会话验证。

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
