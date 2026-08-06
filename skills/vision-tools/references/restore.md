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
- **图标、图片是私有的，能用原图就用原图**：截图里的图标、图片是别人的私有财产，别去网上搜代替图，也别自己做一个代替的——先从原图里想办法截取（见下方「从截图提取图标前景」流程），只有确实截不出来时才谈替代。
- **用 detect 给的坐标组织画布，不要自己重想坐标**：detect 已经给出每个元素和文字的位置，直接按这些 box 换算后组织布局、放置组件；不要无视已有坐标凭感觉重新排。注意按上面的 HiDPI 比例换算，并记住 box 常有偏移/偏小（外扩 8~10px）。

### 从截图提取图标前景（不要直接按 box crop）

直接按 detect/ground 的 box `crop` 会混入相邻内容（文字残影、边框线）。
用 `scripts/extract_fg.py`（Restore 专用脚本）：

```bash
python3 scripts/extract_fg.py shot.png --region X1,Y1,X2,Y2 -o icon.png      # 彩色图标
python3 scripts/extract_fg.py shot.png --region X1,Y1,X2,Y2 --mode dark      # 灰色/黑色线条（logo）
# 自动模式（图标已居中）：crop --scale 放大后只传图，无需 region
crop shot.png --region X1,Y1,X2,Y2 --scale 4 -o icon4x.png
python3 scripts/extract_fg.py icon4x.png                                     # 输出 icon4x.clean.png
```

方法：区域内取彩色像素（或暗色线条），整体 8 邻域连通分量分析，保留所有足够大的
分量（>= 最大分量的 2%，图标由多个分离子形状组成时不会丢件）——背景噪点是散点、
图标线条是连续线，连通性自动分离，无需预先知道主色，抗锯齿全部保留。输出透明
背景 PNG 并打印精确 bbox（可直接喂给下游 crop/glance）。

**抠图是像素级复制，不降质**：还原 UI 时图标一律走抠图，不要手绘 SVG——图标再小
也只是"裁出来贴回去"，与原图 100% 一致；所谓"图标小就模糊、难抠"是手绘派生的
伪命题（放大 4x 后定位/抠图不受尺寸影响）。只有用户明确要求 SVG/矢量交付时才
手绘（那属于 `restore-exact.md` 的精确流程）。

- 干扰为彩色且连片（彩色背景、水印）时：加 `--exclude-color '#背景色'` 排除。
- 取色/搜索区域要**收紧到目标本身**（宽松框住即可），否则可能收进相邻元素。
- 实心图标（含白色镂空细节、浅色渐变底圈）也适用：脚本默认保留被前景包围的
  内部白色（背景填充），`--no-keep-whites` 可关闭；渐变底圈被白色区隔断成的
  碎块分量会按"与主分量 bbox 重叠"规则保留，不会缺角。

备选（脚本不适用时）：ground 定位（放大 4x 再 ground 误差 ±2~4px 原图像素；
4x 是甜区，6x 以上触发 PIL 解压限制且无精度收益；0-1000 网格是浮点、量化非瓶颈，
精度受模型定位噪声限制，同一目标多次调用会差 2~4px），或 dominant_colors 主色
union（排除离白色太近的浅色簇，否则阈值会吞掉白底）。实测三种方法结果等价
（1 连通分量、100% 主形状）；HSV 色相区间法杂散分量多，不推荐。
