# AGENTS.md — codex-deepseek-vision

项目目标：让 Codex 中的纯文本 DeepSeek 通过内置视觉 API 获得图片文字描述。默认代理只做图片改写；与视觉无关的兼容行为必须显式启用。

- 不得重新加入代理 `--cli-cmd` 或任何本机私有路径。
- `glance` 是可选安装的独立图片问答 CLI，不是代理回退路径；代理和 glance 复用 `vision_client.py`。
- 不记录请求 body、图片、对话、系统提示词或 API key。
- 密钥只保存在本地 env 文件中，权限必须为 `0600`，不得写入 plist、日志或 Git。
- Codex config/catalog 修改前必须备份。
- UA/请求头改写与 reasoning summary 注入必须保持默认关闭。
- 默认逐块转发上游响应；reasoning summary 开启时才允许缓冲 SSE。
- 安装/卸载必须幂等，不覆盖非本项目安装的 `glance`。

修改后至少运行：

```bash
python3 -m py_compile deepseek-vision-proxy.py vision_client.py bin/glance
python3 test_image_rewrite_shapes.py
python3 smoke_test_proxy.py
python3 test_vision_client.py
python3 test_install.py
bash -n install.sh verify.sh uninstall.sh
```
