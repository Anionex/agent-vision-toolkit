# hint 改变的是侧重点和回答质量

2026-08-03 · 同图 A/B，2 次 vision 调用 · 上游 `https://api.vectorengine.ai/v1` / `gemini-3.5-flash`（与运行中的 proxy 一致）

> **n=1。** 本文记录的是一次调用里发生了什么，不是「无 hint 必然出幻觉」。
> 可复用的结论只有一条：hint 决定模型去回答哪个问题。下面那两处虚构是这一次的现象，
> 没有复跑次数支撑它是常态——引用本文时不要把它写成幻觉率。

## 实验

同一张图跑两次 `describe_image`，除 hint 块外 prompt 完全相同。

图：`research/_work/hint-ab/comparison.png`，一张 8 行的图标对照表——每行最多 3 组，
每组左边是原图标、右边是 `trace` 输出，其中若干 trace 是坏的（只剩碎线段），
还有一格的 trace **完全空缺**。

hint 取自真实生产数据，是那次 `view_image` 调用时 assistant 的收尾段落：

> You know what? Let me look at what these traces look like as images.
> The comparison sheet was saved. Let me view it — it will show exactly which icons are broken.

复现脚本 `research/_work/hint-ab/run.py`，输出 `no_hint.txt` / `with_hint.txt`。
注意脚本用 `load_env_file()` 直接加载 `~/.config/codex-vision-proxy/env`——
`load_default_env()` 的叠加顺序会让仓库 `.env` 覆盖它，导致打到另一个上游。

## 结果：无 hint 那份有两处虚构

逐格与原图核对：

| 项 | with_hint | no_hint | 原图 |
|---|---|---|---|
| 上传圆箭头那格的 trace | 只报原图标，未报 trace | "faint grey dashed lines forming the partial outline of a box" | **该格右侧纯白，没有 trace**（已放大核对） |
| 左上角小灰块 | 未提（并入云那一组） | 独立元素，"grey user profile silhouette with sound waves" | **是巨型灰云那一组的 reference**：同为云形轮廓、内含同一个 `)`，放大后母题仍在 |
| 行数 | 8 | 7 | 两者都成立，见下 |

行数不构成谁对谁错。按像素扫连续墨迹带只有 7 带
（`0–406 · 504–620 · 726–838 · 942–1059 · 1162–1281 · 1390–1493 · 1608–1714`）——
第一带里那朵云的 trace 纵向鼓出，压进了下一行的高度，所以像素上就是连着的。
"7 行"是墨迹的事实，"8 行"是配对逻辑的事实。**这一项不算差异，别拿它当证据。**

开场句同样有别：

- no_hint：`comparing small/draft versions ... to larger, **clearer** versions on the right`
  —— 右列有 6 个是碎片，不是更清晰。这句话本身是错的。
- with_hint：`comparing small reference icons with their larger traced/rendered versions.
  **Several of the traced icons are severely broken**`

with_hint 对 6 个图标打了 `Traced (Broken)`，长度反而更短（3611 vs 4761 字符）。

## 结论：hint 提供的是任务框架，不是强调顺序

配对核验（"这格的另一半在哪、两半一不一致"）会把空格子暴露成空格子。
自由描述遇到空白则用邻近视觉记忆补全——于是给不存在的 trace 编了内容，
给模糊小块编了语义。

因此**无 hint 不是中性的安全默认**：它把模型放进自由联想模式。
这补充（不推翻）「emphasis 路由错误 ≠ 误导」——那条讲的是 hint *指错方向*的后果，
本条讲的是 hint *缺席*的后果，两者不同。

再强调一次：上一段是对这一次结果的机制解释，不是频率断言。
真正稳的差别是**回答质量**——no_hint 那份开场就把描摹结果说成"更清晰的版本"，
逐格孤立描述，答的不是当下在问的问题；with_hint 成对核对，更短且直接可用。

## 代价：verbatim 转写段被挤掉

no_hint 末尾有独立的 `### Verbatim Text Transcription` 段（Fu / Fu / c / C）；
with_hint 把这些只散在正文里，没有独立段落。两次 prompt 里
`transcribe all visible text verbatim` 一字未改，是模型自己重新分配了输出结构。

本例中文字量很小、内容没丢，代价划算。但静默遗漏是重查救不回来的唯一损失类型，
**这一条需要在文字密集的图上再跑一轮 A/B 才能确认它不是常态**。在那之前不要据此改
`_DESCRIBE_PROMPT`——加强 verbatim 措辞是每请求每图的全局成本。
