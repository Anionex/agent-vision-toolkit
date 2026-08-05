# Operating a GUI from screenshots

**When to use**: the task is to act on a live screen — click, type,
scroll — guided by screenshots: driving an app, automating a workflow,
walking a bug reproduction. The vision layer answers "where is it" and
"what state is it in"; the acting itself goes through whatever automation
channel the task already has.

Tool syntax lives in `SKILL.md`. This file is the sequence and the
pass/fail test.

## Steps

**1. Calibrate coordinates once, before the first click.**

Screenshot pixels and pointer coordinates are often different spaces: on
HiDPI displays a screenshot is 2-3× the logical points the click API
takes. Compare the screenshot's pixel width to the screen's logical width
and divide every box by that ratio. Skipping this puts every click at half
or double distance from the origin — consistently wrong in a way that
looks like bad grounding.

**2. Locate with `ground`, click the box center. Cache fixed targets.**

Centers, not corners — ground boxes are not pixel-exact at the edges. For
tiny targets (checkboxes, close buttons), go coarse-to-fine: ground the
containing block, then `ground --region` inside it.

For elements that stay put across interactions (toolbar buttons, sidebar
links, fixed panels), ground them once and record a coordinate table — an
id/label plus center coordinates. Subsequent clicks reference the table
entry directly instead of re-running ground each time. Invalidate the
table when the layout changes (window resize, navigation to a different
page, scroll).

**3. One screenshot per action — act, re-shoot, verify, then continue.**

Every action invalidates the current screenshot: menus open, focus moves,
content loads; scrolling invalidates every box at once. Chaining several
clicks on one stale screenshot is how you click through where a dialog
used to be.

**4. Verify as a question about the expected state.**

`glance <after.png> -q "is the settings dialog open?"` — ask for the state
the action should have produced, not a general description. If the answer
is no or unexpected, stop and re-inventory (`detect`) instead of pressing
on against an assumed screen. When the change is small (a toggle, one
badge), diff first: `pixel_diff before.png after.png` finds the changed
region, `glance --region` reads it.

**5. After typing, read the field back.**

Focus loss eats keystrokes silently. `glance --region <field box> --ocr`
confirms the text actually landed before you submit.

## Verify

The loop in steps 3-4 *is* the verification: no action counts as done
until a fresh screenshot answers the expected-state question. For a
multi-step flow, the final screenshot must show the end state the task
defines — the confirmation page, the saved indicator. A completed action
list is not evidence; the pixels are.

## Boundaries

- Loading is asynchronous: after an action that triggers it, poll —
  re-screenshot until two consecutive shots stop differing (`pixel_diff`
  near 0) — rather than trusting one fixed sleep.
- Irreversible actions (send, delete, pay) follow the calling agent's own
  confirmation policy. The vision layer reports what is on screen; it
  never makes that call.
- A screen the task didn't predict — an error dialog, a permission
  prompt, a login wall — is a stop-and-surface, not an obstacle to click
  through. Clicking through unknown dialogs is how automations do damage.
