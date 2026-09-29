import assert from "node:assert/strict";
import { test } from "node:test";
import { rememberedResult, rememberResult, keepNewest, REMEMBERED_COMMANDS } from "./commandMemory.js";

test("a command carried out once is remembered with what came of it", () => {
  rememberResult("cmd-1", "done", { outDir: "/r/1" }, 1000);
  assert.deepEqual(rememberedResult("cmd-1"), { status: "done", result: { outDir: "/r/1" }, at: 1000 });
  rememberResult("cmd-2", "error", { error: "camera not found" }, 1001);
  assert.equal(rememberedResult("cmd-2").status, "error");
});

// Paired: a command never seen must not look remembered, or nothing would run.
test("a new command is not remembered, so it runs", () => {
  assert.equal(rememberedResult("never-seen"), null);
});

test("only the newest are kept", () => {
  const many = Object.fromEntries(Array.from({ length: 60 }, (_, i) => [`c${i}`, { status: "done", result: null, at: i }]));
  const kept = keepNewest(many, REMEMBERED_COMMANDS);
  assert.equal(Object.keys(kept).length, REMEMBERED_COMMANDS);
  assert.ok("c59" in kept && !("c0" in kept) && !("c9" in kept) && "c10" in kept);
});
