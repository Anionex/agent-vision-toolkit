# Reading numbers off charts

**When to use**: values, trends, or comparisons must come out of a chart
image — line, bar, scatter, pie — and the underlying data is not
available. If it is (a CSV, the code or query that drew the chart), read
that instead: a chart is a lossy render of its data, never the better
source.

Tool syntax lives in `SKILL.md`. This file is the sequence and the
pass/fail test.

## Steps

**1. Structure first; accept no numbers from the opening pass.**

`glance <chart>` for the qualitative frame: chart type, what each axis
measures, the series and their legend mapping, the visible trend.

**2. Read the scales verbatim, and ask the two trap questions.**

`glance --region <axis box> --ocr` on each axis for tick labels and
units. Then ask explicitly: `-q "does the value axis start at zero?"` and
`-q "is either axis logarithmic?"` — a truncated or log axis silently
invalidates every visually-derived comparison ("twice as tall" is not
"twice as much").

**3. Grade every number you are about to report.**

Three grades, and each reported value carries its grade:

- **Read** — printed on the chart (a data label, a tick value): OCR it
  verbatim. Exact.
- **Measured** — derived from geometry: locate the mark (`ground` the bar
  top, the point), take two ticks with known values from the same axis,
  and interpolate the mark's pixel position between them. The two ticks
  define the pixels→units mapping; the arithmetic is yours, not the
  model's.
- **Estimated** — anything the vision model eyeballed. Report it labeled
  "estimated", or not at all when the task needs precision.

A vision model asked for a value will always produce one, at any level of
support — the grading is what keeps chart numbers honest.

**4. Calibrate against a printed anchor before trusting measurements.**

If any value is printed on the chart, measure that mark first: a bar
labeled 42 must measure ≈42, or the mapping is broken (wrong ticks,
truncated axis, wrong baseline) and every other measurement inherits the
error.

## Verify

- Cross-foot: pie shares sum to ~100%; stacked segments sum to their
  printed total; a "total" series matches the sum of its parts.
- Order check: values measured along an axis must order the same way the
  marks do visually.
- Re-derive one measured value from a different tick pair — the two
  results should agree within about a tick's width.

## Boundaries

- Dense scatter or overlapping lines: point counts and exact crossings
  are not recoverable — say so rather than shipping an estimated count as
  data.
- 3D, perspective, or stylized charts distort geometry. The interpolation
  in step 3 assumes flat axes; on these charts everything downgrades to
  "estimated".
- Stacked areas and bars: measure the cumulative boundaries and subtract —
  reading a middle band's thickness directly doubles the error.
- Dashboard screenshots can hide series behind legend toggles and
  filters — report what is visible as what is visible, not as the whole
  dataset.
