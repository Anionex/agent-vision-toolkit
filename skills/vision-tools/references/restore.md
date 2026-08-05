# Rebuilding UI or graphics from an image

**When to use**: the task is reproducing what an image shows — a page as
HTML, an icon or diagram as SVG, a visual component lifted out for reuse,
or a sketch/diagram/whiteboard turned into structured code (Mermaid,
Graphviz, JSON outline). Checking an existing implementation against its
design image is the same job entered at the Verify step: render, diff,
zoom. Not for answering questions about an image; that is `glance` alone.

Tool syntax lives in `SKILL.md`. This file only routes you to the right
workflow — the workflows themselves live in the two files below. Read the
matched one before starting; do not read both unless you are switching.

## 先选模式，再开干

| 模式 | 触发信号 | 工作流文档 |
|---|---|---|
| 非精确（默认） | 未提及“像素级/精确”；只要求“布局、配色、图标一致”“大致还原”“复原 UI” | `references/restore-quick.md` |
| 精确 | 明确要求“像素级还原”“像素级一致”“精确还原”“pixel-perfect” | `references/restore-exact.md` |

不要因为追求“还原度”就把非精确任务升级成精确流程——那不是认真，是浪费。
拿不准时：先按非精确做，完成后用户要求更精确再升级；升级只需换读
`restore-exact.md`，已做过的 detect/glance/颜色采样结果不用重做。

## 通用经验（两个工作流都适用，先读这里）

- **detect/ground 的 box 常有偏移或偏小**（实测偏 5~10px 很常见，个别元素会被裁掉一半）。凡是拿 box 做裁剪或定位：先每边**外扩 8~10px**（2x 原图）再按 ink 边界收紧；同一批裁剪完拼成一张 contact sheet 目检，确认没有元素被切边。
- **一切对比都对照原图**：拿自己渲染的两版互相对比不算数。
- **字体渲染差异是固有噪声**（渲染器 Helvetica/Arial vs 系统 SF Pro 等）：非精确直接接受；精确做 pixel_diff 时把它当已知噪声，收敛标准按非字体区域衡量。
- **截图可能是 HiDPI（常见 2x）**：detect/ground/crop 返回的是原图像素。把坐标换算成 HTML 的逻辑尺寸前，先确认原图尺寸与页面逻辑尺寸的比值，否则整体布局会偏移一个量级——例如原图 2704x1556、页面逻辑 1352x778 时，一切坐标除以 2。
