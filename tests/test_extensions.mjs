#!/usr/bin/env node
// Unit tests for the Pi/Oh My Pi extension and the OpenCode plugin.
//
// Run with either runtime (both strip the erasable-only TypeScript syntax):
//   node tests/test_extensions.mjs     (Node >= 24)
//   bun  tests/test_extensions.mjs
//
// Network is stubbed: every test injects its own fetch and vision config, so
// no VISION_API_KEY is needed and the machine's real env chain is never read.

import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const pi = await import("../extensions/pi/vision.ts");
const oc = await import("../extensions/opencode/vision.ts");

const CONFIG = { apiKey: "test-key", baseUrl: "http://vision.test", model: "test-vision" };

let failures = 0;

function check(name, condition, detail) {
  if (condition) {
    console.log("PASS: " + name);
  } else {
    failures += 1;
    console.error("FAIL: " + name + (detail === undefined ? "" : " — " + JSON.stringify(detail)));
  }
}

function fakeFetch(capture, description = "DESC") {
  return async (_url, init) => {
    const body = JSON.parse(init.body);
    capture.push(body.messages[0].content.find((part) => part.type === "text").text);
    return new Response(
      JSON.stringify({ choices: [{ message: { content: description } }] }),
      { status: 200 },
    );
  };
}

const IMG = { type: "image", data: "AAAA", mimeType: "image/png" };

// ---------------------------------------------------------------------------
// Pi / Oh My Pi extension

{
  const prompts = [];
  const messages = [
    {
      role: "user",
      content: [{ type: "text", text: "why does the login page look broken" }, { ...IMG }],
      timestamp: 1,
    },
  ];
  const result = await pi.handleContext(
    { type: "context", messages },
    { model: { input: ["text"] } },
    CONFIG,
    fakeFetch(prompts),
  );
  const content = result?.messages?.[0]?.content ?? [];
  check("pi: pasted image is rewritten with its own message's text as hint",
    content[2]?.text === "[vision model description] DESC"
      && prompts[0]?.includes("login page look broken")
      && prompts[0]?.includes("Do not answer the user's request yourself"),
    { content, prompts });
  check("pi: channel note lands once before the first image",
    content[1]?.text?.startsWith("[vision proxy]")
      && content.filter((b) => b.text?.startsWith("[vision proxy]")).length === 1,
    content);
}

{
  const prompts = [];
  const messages = [
    { role: "user", content: "修复登录页样式", timestamp: 1 },
    {
      role: "assistant",
      content: [
        { type: "thinking", thinking: "翻了一遍日志没有线索。\n\n先看失败截图确认按钮颜色。" },
        { type: "toolCall", id: "t1", name: "read", arguments: {} },
      ],
      timestamp: 2,
    },
    { role: "toolResult", toolCallId: "t1", toolName: "read", content: [{ ...IMG }], isError: false, timestamp: 3 },
  ];
  await pi.handleContext({ type: "context", messages }, { model: { input: ["text"] } }, CONFIG, fakeFetch(prompts));
  check("pi: tool-result image rides the assistant's closing thinking paragraph",
    prompts[0]?.includes("确认按钮颜色")
      && !prompts[0]?.includes("翻了一遍日志")
      && prompts[0]?.includes("decided to view")
      && !prompts[0]?.includes("修复登录页样式"),
    prompts);
}

{
  const prompts = [];
  const messages = [
    { role: "assistant", content: [{ type: "text", text: "上一轮的旧意图" }], timestamp: 1 },
    { role: "user", content: "看看这个图表的趋势", timestamp: 2 },
    { role: "toolResult", toolCallId: "t1", toolName: "read", content: [{ ...IMG, data: "BBBB" }], isError: false, timestamp: 3 },
  ];
  await pi.handleContext({ type: "context", messages }, { model: { input: ["text"] } }, CONFIG, fakeFetch(prompts));
  check("pi: a new user turn invalidates earlier assistant intent",
    prompts[0]?.includes("图表的趋势") && !prompts[0]?.includes("旧意图"), prompts);
}

{
  const messages = [{ role: "user", content: [{ ...IMG }], timestamp: 1 }];
  const result = await pi.handleContext(
    { type: "context", messages },
    { model: { input: ["text", "image"] } },
    CONFIG,
    async () => { throw new Error("must not be called"); },
  );
  check("pi: a natively multimodal model keeps its images untouched",
    result === undefined && messages[0].content[0].type === "image", messages);
}

{
  const messages = [{ role: "user", content: [{ ...IMG, data: "CCCC" }], timestamp: 1 }];
  await pi.handleContext(
    { type: "context", messages },
    { model: { input: ["text"] } },
    CONFIG,
    async () => { throw new Error("HTTP 500 test-key"); },
  );
  const text = messages[0].content.at(-1)?.text ?? "";
  check("pi: a failed description is replaced with an honest failure, never the raw image",
    text.includes("image description failed") && text.includes("NOT delivered")
      && !messages[0].content.some((b) => b.type === "image"),
    messages);
}

{
  const messages = [{ role: "user", content: [{ ...IMG, data: "DDDD" }], timestamp: 1 }];
  await pi.handleContext(
    { type: "context", messages },
    { model: { input: ["text"] } },
    { error: "VISION_API_KEY is not set. …" },
    async () => { throw new Error("must not be called"); },
  );
  check("pi: missing vision config is reported in the image's place",
    messages[0].content.at(-1)?.text?.includes("VISION_API_KEY is not set"), messages);
}

{
  const prompts = [];
  const fetchImpl = fakeFetch(prompts);
  const make = () => [{ role: "user", content: [{ type: "text", text: "cache me" }, { ...IMG, data: "EEEE" }], timestamp: 1 }];
  await pi.handleContext({ type: "context", messages: make() }, { model: { input: ["text"] } }, CONFIG, fetchImpl);
  const second = make();
  await pi.handleContext({ type: "context", messages: second }, { model: { input: ["text"] } }, CONFIG, fetchImpl);
  check("pi: identical (image, prompt) pairs hit the cache across calls",
    prompts.length === 1 && second[0].content.at(-1)?.text === "[vision model description] DESC",
    { calls: prompts.length });
}

// ---------------------------------------------------------------------------
// OpenCode plugin

const ocMessages = (parts) => [{ info: { role: "user" }, parts }];

{
  const prompts = [];
  const parts = [
    { id: "p1", type: "text", text: "why does the login page look broken" },
    { id: "p2", type: "file", mediaType: "image/png", filename: "shot.png", url: "data:image/png;base64,AAAA" },
  ];
  const changed = await oc.rewriteMessages(ocMessages(parts), CONFIG, fakeFetch(prompts));
  check("opencode: image file part is rewritten with its own message's text as hint",
    changed
      && parts[2]?.type === "text" && parts[2]?.text === "[vision model description] DESC"
      && prompts[0]?.includes("login page look broken"),
    { parts, prompts });
  check("opencode: channel note lands once, without duplicating the part id",
    parts[1]?.text?.startsWith("[vision proxy]") && parts[1]?.id === undefined && parts[2]?.id === "p2",
    parts);
}

{
  const dir = mkdtempSync(join(tmpdir(), "cvp-oc-test-"));
  const file = join(dir, "shot.png");
  writeFileSync(file, Buffer.from([0x89, 0x50, 0x4e, 0x47]));
  const urls = [];
  const fetchImpl = async (_url, init) => {
    urls.push(JSON.parse(init.body).messages[0].content.find((p) => p.type === "image_url").image_url.url);
    return new Response(JSON.stringify({ choices: [{ message: { content: "DESC" } }] }), { status: 200 });
  };
  const parts = [{ type: "file", mediaType: "image/png", url: file }];
  await oc.rewriteMessages(ocMessages(parts), CONFIG, fetchImpl);
  check("opencode: a local file path is inlined as a data URL for the vision API",
    urls[0] === "data:image/png;base64," + Buffer.from([0x89, 0x50, 0x4e, 0x47]).toString("base64"),
    urls);
}

{
  const parts = [{ type: "file", mediaType: "image/png", url: "/nonexistent/cvp-gone.png" }];
  await oc.rewriteMessages(ocMessages(parts), CONFIG,
    async () => { throw new Error("must not be called"); });
  check("opencode: a vanished image file is reported honestly, never guessed",
    parts.at(-1)?.text?.includes("could not be read"), parts);
}

{
  const parts = [{ type: "file", mediaType: "image/png", url: "data:image/png;base64,BBBB" }];
  await oc.rewriteMessages(ocMessages(parts), { error: "VISION_API_KEY is not set. …" },
    async () => { throw new Error("must not be called"); });
  check("opencode: missing vision config is reported in the image's place",
    parts.at(-1)?.text?.includes("VISION_API_KEY is not set"), parts);
}

{
  const parts = [
    { type: "text", text: "no images here" },
    { type: "file", mediaType: "text/plain", url: "data:text/plain;base64,AAAA" },
  ];
  const changed = await oc.rewriteMessages(ocMessages(parts), CONFIG,
    async () => { throw new Error("must not be called"); });
  check("opencode: messages without image parts pass through unchanged",
    changed === false && parts.length === 2 && parts[1].type === "file", parts);
}

{
  process.env.VISION_REWRITE = "off";
  try {
    const hooks = await oc.VisionBridge({});
    const parts = [{ type: "file", mediaType: "image/png", url: "data:image/png;base64,CCCC" }];
    await hooks["experimental.chat.messages.transform"]({}, { messages: ocMessages(parts) });
    check("opencode: VISION_REWRITE=off disables rewriting for multimodal primaries",
      parts[0].type === "file", parts);
  } finally {
    delete process.env.VISION_REWRITE;
  }
}

if (failures) {
  console.error(`${failures} test(s) failed`);
  process.exit(1);
}
console.log("EXTENSION TESTS PASS");
