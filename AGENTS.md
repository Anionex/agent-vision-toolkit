# AGENTS.md — codex-deepseek-vision

## 项目目标

让已经在 Codex 中正常使用 DeepSeek 的用户，通过轻量本地代理使用 Codex 内置 `view_image`。本仓库主要供用户的 Codex Agent 阅读并根据本机真实配置完成部署，不提供通用一键安装器。

执行部署前必须先完整阅读 `README.md`，再按照 `AGENT_INSTALL.md` 操作。

## 不可偏离的范围

- README 包含用户亲自调整的项目介绍和产品文案。除非用户明确指定，不得整体改写、润色或覆盖；修改前先同步远端最新版本，只做请求涉及的最小范围补丁。
- 保留用户现有的模型、slug、`display_name`、provider、鉴权方式和 DeepSeek key。
- 不内置模型别名或模型名映射，不增加专用“视觉模型”。
- Codex 已发送的认证请求头必须原样透传；不得要求或读取 `DEEPSEEK_API_KEY`。
- `config.toml` 只把当前 provider 的 `base_url` 指向 `http://127.0.0.1:19100`，代理上游使用修改前的原地址。
- 对当前 model catalog 条目，只有在 `input_modalities` 字段明确为仅 `text` 时才追加 `image`；字段缺失或已经含 `image` 时不改。
- 不修改 catalog 中的其他字段。配置修改前必须备份，并使用 TOML/JSON 解析器结构化编辑。
- 项目核心与操作系统无关；平台差异只允许出现在路径、后台常驻和 CLI wrapper，不能复制公共安装流程或引入平台安装框架。
- 不得加入一键安装/卸载器、复杂迁移、事务回滚或配置编辑框架。

## 运行与安全边界

- 代理默认只做图片转文字和必要的协议转发；普通文本、模型名和鉴权保持原样。
- 不得重新加入 `--cli-cmd` 或任何本机私有路径。
- 不记录请求 body、图片、对话、系统提示词或 API key。
- env 只保存视觉 API 配置并放在当前用户目录；macOS 权限必须为 `0600`。密钥不得写入 plist、启动项、日志或 Git。
- `glance` 是可选独立 CLI，不是代理回退路径；它与代理复用 `vision_client.py`。
- `ground` 是可选独立 CLI，不是代理链路的一部分；它复用 `VISION_*` 配置，额外依赖必须保持隔离且不得影响代理。
- UA/请求头兼容与 reasoning summary 注入必须默认关闭。
- 默认逐块转发上游 SSE；只有 reasoning summary 兼容确实需要时才允许缓冲对应响应。
- 保留必要的有限重试、多图并行和小型进程内缓存，避免部署系统过度工程化。
- 不得修改 `assets/` 下的效果图。

## 修改后的最低验证

```bash
python3 -m py_compile deepseek-vision-proxy.py vision_client.py bin/glance
python3 test_image_rewrite_shapes.py
python3 smoke_test_proxy.py
python3 test_vision_client.py
git diff --check
```

修改 `ground.py` 或 `bin/ground` 时，另运行 `python3 test_ground.py`（需要 Pillow）。

还需确认：

- 配置和运行代码不要求 `DEEPSEEK_API_KEY`，且没有固定模型名、固定 `display_name`、模型映射或私有绝对路径。
- 普通文本、模型名、认证请求头原样透传。
- 默认 SSE 是逐块输出。
- 效果图没有变化。
