# Rebuilding UI or graphics from an image

**When to use**: the task is reproducing what an image shows — a page as
HTML, an icon or diagram as SVG, a visual component lifted out for reuse,
or a sketch/diagram/whiteboard turned into structured code (Mermaid,
Graphviz, JSON outline). Checking an existing implementation against its
design image is the same job entered at the Verify step: render, diff,
zoom. Not for answering questions about an image; that is `glance` alone.

Tool syntax lives in `SKILL.md`. This file is the sequence and the
pass/fail test.

## 两种模式：先确认用户要求，再决定深度

重建任务默认走**非精确模式**。只有当用户明确要求“像素级还原 /
像素级一致 / 精确还原（pixel-perfect）”时，才走**精确模式**（本文档
“精确模式步骤”起的完整流程）。不要因为追求“还原度”就把非精确任务
升级成精确流程——那不是认真，是浪费。

| 模式 | 触发信号 | 工作流 | 交付标准 |
|---|---|---|---|
| 非精确（默认） | 未提及“像素级/精确”；只要求“布局、配色、图标一致”“大致还原”“复原UI” | 一轮 detect/ground → 一轮 glance → 一轮 dominant_colors 批量采样 → 直接写 HTML/SVG | 渲染后与原图做一次视觉对比，无一眼可见的差异即可 |
| 精确 | 明确说“像素级还原”“精确还原”“pixel-perfect” | “精确模式步骤”起的完整流程（区域 refine、trace、像素测量、pixel_diff 迭代） | pixel_diff 逐轮下降直至收敛 |

### 通用经验（两种模式都适用）

- **detect/ground 的 box 常有偏移或偏小**（实测偏 5~10px 很常见，个别元素会被裁掉一半）。凡是拿 box 做裁剪或定位：先每边**外扩 8~10px**（2x 原图）再按 ink 边界收紧；同一批裁剪完拼成一张 contact sheet 目检，确认没有元素被切边。精确模式做像素测量同样以实测为准，不信 box。
- **一切对比都对照原图**：非精确模式是渲染后与原图做一次整体视觉对比；精确模式是 render vs 原图的 pixel_diff 逐轮收敛。拿自己渲染的两版互相对比不算数。
- **字体渲染差异是固有噪声**（渲染器 Helvetica/Arial vs 系统 SF Pro 等）：非精确模式直接接受；精确模式做 pixel_diff 时把它当已知噪声，收敛标准按非字体区域衡量。

### 非精确模式步骤

1. **一轮 inventory**：`detect` 全屏一次，拿全部元素、文字和坐标；需要定位单个元素时用 `ground`。
2. **一轮 glance**：整体结构、图标形状、元素类型；个别看不清的小元素再 `glance --region` 一次。
3. **一轮颜色采样**：`dominant_colors.py` 对主要区域批量取色（背景、文字、图标主色），每个区域只取主色值，不纠结次色、渐变和 1px 细节。
4. **直接写 HTML/SVG**：坐标用 detect/ground 给的盒子直接换算近似；圆角用常见值（8/12/14px）；文字用系统字体近似。
5. **图标/logo 优先裁原图**：需要图标时，用 detect/ground 给出的 box 直接 `crop` 裁剪成 PNG（浅色背景元素裁出来放在同色底上无缝），HTML 里 `<img>` 引用——图标与原图 100% 一致且零手绘成本。只有用户明确要求 SVG/矢量交付，或裁出的素材带明显背景色时才手绘 SVG（裁剪外扩、目检等坑见上方“通用经验”）。

非精确模式明确禁止：
- 反复扫描同一区域的色值变化或位置细节（1px 边框色、圆角精确半径、阴影透明度都不是目标）。
- 用 `trace` 抠图标或轮廓（精确模式才需要；非精确模式直接裁剪原图即可）。
- 用 pixel_diff 逐轮迭代——最多渲染后与原图做一次整体视觉对比。
- 因为字体渲染差异等已知噪声（见“通用经验”）而升级精确模式。

### 精确模式

仅当用户明确要求“像素级 / 精确还原”时，才执行下面的完整流程。

## 精确模式步骤

**1. Inventory in one pass, then refine by region.**

One full-screen `detect` call gives the element list. Do not build that
list element by element with single-target calls — that spends one vision
call per element for what one call returns. A full-screen pass
under-reports on dense screens, so treat it as the scaffold:
`detect --region` each layout block for a complete local list, then zoom
with `glance --region` and sample colors with `scripts/dominant_colors.py`.

**2. Take every number from pixels, never from prose.**

Exact colors, offsets, and sizes are where vision models are confidently
wrong. Get them from `scripts/dominant_colors.py` or a `trace` — their
values come from the actual pixels.

**3. For each shape, decide: ship the trace, or measure from it.**

Ship the traced SVG as-is for organic or irregular shapes — hand-written
approximations of organic curves lose fidelity. For simple geometry
(rects, circles, pills) or SVG that will be edited later, use the trace as
a measurement reference instead: read exact positions, sizes, and radii
from its paths, then hand-write clean primitives from them.

- **Icon / logo / line-art to SVG**: `trace --region <ground box> -o icon.svg`.
- **Diagram / flowchart / wireframe structure**: `--polygon` yields each box
  and arrow as a compact path with exact position and size — layout
  relations become readable text.
- **Measuring elements**: parse the traced paths (or skip SVG and compute
  on pixels directly) rather than asking `glance` for numbers.

A small icon is a hand-write case, not a no-trace case. A 15-30px stroke
icon is too coarse to ship as a traced outline — the trace returns the
ribbon around the stroke, not its centerline — so the deliverable is a
hand-written `<path stroke=... fill=none>`. Draw it from the trace anyway:
`trace <icon> --polygon` upscales the image for you and returns a handful
of polygon paths whose vertices give every endpoint, corner and stroke
width in pixels. Reading structure off a printed pixel grid instead is
guessing dressed as data — you are eyeballing the same shape with less
precision and no coordinates.

Two traps when reusing traced paths:

- The SVG has a **transparent background** — composite on white before any
  pixel diff or visual check (`rsvg-convert -b white`); transparency reads
  as black in many viewers and gets misdiagnosed as a broken trace.
- Every `<path>` carries a `transform` attribute. When lifting a path into
  another SVG, **copy the transform together with `d`** — holes are
  opposite-winding subpaths and survive standalone extraction, but a
  dropped transform displaces the shape.

**4. Pick every colour from pixels; the model only names it.**

`glance` can tell you a region reads as "light gray", but not whether that is
`#F9FAFA`, `#F5F5F5`, or `#EDEDED` — and a rebuilt page that uses the wrong
gray is visibly off even though both are "light gray". Work colour in three
moves:

1. `glance <image> --region <box> -q "name the colours in this region"` —
   prose labels only. This step names the clusters; it does not measure them.
2. `python3 scripts/dominant_colors.py <image> --region <box>` — downsample,
   quantize, merge near-duplicates, and print the top colour clusters with the
   share each owns. The histogram is the role map: the biggest share is
   usually the background, smaller shares the accents.
3. Map each label to the candidate palette it implies, then let the pixels
   choose:
   `python3 scripts/dominant_colors.py <image> --region <box> --candidates '#F9FAFA,#F5F5F5,#F3F3F3,#EDEDED'`
   — each candidate is scored by a distance filter over the region's pixels
   and the best one wins. Use that hex in the rebuild.

The rule from step 2 still holds: the label comes from the model, the value
from the pixels.

## Verify

Render what you built (Playwright for HTML, rsvg-convert for SVG), then:

```bash
python3 scripts/pixel_diff.py <original.png> <rendered.png>
```

It prints an overall difference percentage and the worst regions as
`x1: .., y1: ..` boxes — the same form `glance --region` and
`detect --region` take, so the top offender goes straight back into a zoom
call. Fix the largest diff, re-render, re-run; the number should drop each
round.

**When the output is structural code** (Mermaid, Graphviz, JSON layout) —
pixel-diffing is meaningless because the render and the original differ
everywhere by design. Verify structure instead: render the artifact to an
image, rebuild an inventory from it (`detect` + OCR), and compare node
count, label set, edge list with directions against the original. A
missing node or reversed arrow shows up as a list diff even when both
images "look right". Labels must match verbatim — do not tidy spelling or
expand abbreviations; a label you cannot read is `[unreadable]`, never a
guess.

Two rules about reading that output, both about not stopping early:

- **A low percentage does not mean a single defect.** The ranking is where
  to start looking, not the list of what is wrong. One cell can hold two
  faults at once — a wrong fill colour is loud enough to hide a position
  shift underneath it. Having explained the top region, check whether it
  also moved, resized, or changed shape, and keep working down the
  remaining ranked regions until they come back clean.
- **Never conclude from a description comparison.** Your prose description
  of the original against your prose description of the rebuild tells you
  nothing — both came from the same model, so its blind spots cancel out
  instead of showing up.

The script composites transparency on white for you — but if you diff by
hand for any reason, do it yourself.

## Boundaries

Whole screenshots and photos do not trace usefully. Low-contrast art
(watermarks, faint patterns) binarizes away and the trace picks up the
high-contrast content around it instead.

A "0 paths" result means the region binarized to nothing, and it is
recoverable — in order: raise `--scale`, tighten `--region` around the
shape, or pre-invert a light-on-dark image. Reach for `--color` last and
only for genuinely multi-colour art: on anti-aliased input it gives every
grey level its own cluster, so a single icon comes back as dozens of
fragment paths. That output looks like proof the tool cannot handle the
shape, and it is really just the wrong flag.
