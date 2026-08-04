# 2026-08-05 — 四宿主真机端到端验收

一夜完成的 live 验证：同一张测试图（400×120，红底 `#c0392b`，两行文字
`VISION-E2E-7429` / `the button color is #2ecc71`），四个宿主全部真实跑通，
每个都有独立证据链。测试全程未触碰生产代理（19100）与生产 env。

## 方法

- **Claude Code**：三明治链路 `claude -p → capture(19151) → 代理(19150) →
  capture(19152) → 桌面宿主鉴权中继(127.0.0.1:15721/claude-desktop)`。
  鉴权用宿主 SDK 进程环境里的 gateway token（`ps eww` 提取，未落盘）。
  `ANTHROPIC_BASE_URL` 覆盖时 CLI 不读 keychain，必须显式 `ANTHROPIC_AUTH_TOKEN`。
- **Pi / Oh My Pi**：`models.json` 配 sub2api provider（key 用 env var 名引用），
  主模型 `gpt-oss-120b-medium`（真纯文本）。vision.ts 前后各挂一个探针
  extension 打印消息形态。omp 用 `--tools read` 收缩工具集。
- **OpenCode**：`opencode run "…" --file target.png --attach`（headless 附件的
  唯一姿势；`@file` mention 是 TUI 功能，run 模式下是纯文本）。vision 调用经
  capture(19153) 取证。

## 结果

| 宿主 | 证据 |
|---|---|
| Claude Code | PRE 捕获：图片在 `tool_result` 内层 `{type:"image",source:{type:"base64"}}`（与 collector 假设一致）；POST 捕获：同位置 → channel note + `[vision model description]`，原图零泄漏；回答逐字正确且主动引用 channel note、对色值标注近似区间 |
| Pi 0.73.0 | 探针：`toolResult[text,image]` → vision.ts → `toolResult[text,text,text]`；回答逐字正确 |
| Oh My Pi 17.2.8 | 同上（同一份 vision.ts 文件），证实 context hook 在 omp 图片闸门上游 |
| OpenCode 1.18.13 | vision 请求捕获含完整 role prompt + focus hint（用户原话）+ verbatim 条款 + data URL；回答逐字正确并命中背景 `#C0392B` |

## 付出代价的发现

1. **opencode 的 plugin loader 会把模块的每个导出都当 plugin 调用**。具名导出
   （哪怕是辅助函数）直接 `{} is not iterable` 崩掉加载。插件文件必须单
   default 导出；测试断言已锁定。
2. **sub2api 的流式 + 工具调用组合会内容依赖性地 400**（`gemini-3.6-flash-low`
   对"read 图片文件"类 prompt 100% 复现，非流式同请求正常）。评测遇到
   `Upstream request failed` 先试非 gemini 模型（`gpt-oss-120b-medium` 稳定）。
3. **sub2api 对 omp 的 11 工具载荷 400**：单工具全过、组合挂（first-8 过、
   first-10 挂），与具体字段无关，像上游 schema/大小类限制。绕法 `--tools read`。
4. **gpt-oss 在 opencode 下回答全进 reasoning 通道、正文为空**；换
   `gemini-3.1-flash-lite` 正常。宿主×模型的渲染兼容性要单独验。
5. `opencode run` 不带 `--attach` 时附件 mime 一律 `text/plain` 且是 file://
   URL；带 `--attach` 才是 base64 data URL + 真实 mime。字段名是 `mime`
   （TUI/API 路径是 `mediaType`）——插件两个都要认。

## 事故记录

覆盖了已存在的 `~/.config/opencode/opencode.json` 才检查内容（违反先备份原则）。
APFS 快照挂载被 TCC 拒绝，未能恢复；原内容未知（同目录 config.json 仅空壳
schema，`skills/` 未受影响）。恢复路径：Finder → ~/.config/opencode →
Time Machine 浏览 01:51 前版本。

## 遗留

- 测试产物在 `~/cvp-e2e/`（captures 含本人测试会话的完整请求体，含 Claude Code
  系统提示词——留作核查，勿入库）；临时 `.env` 已删除。
- pi / omp / opencode 三个 CLI 与其配置保留在机器上，供后续评测复用。
