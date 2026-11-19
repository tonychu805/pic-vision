import { test } from "node:test";
import assert from "node:assert/strict";
import { BUILT_IN_DATABASE, chooseDatabase, parseDatabase } from "./database.js";

const TOKYO = { url: "https://boorzbxduhsgbkilovyq.supabase.co", key: "sb_publishable_nP9xYoiNF2V8gWx_PN6-6w_IYt5PPee" };

test("a project the console names is accepted only as a Supabase project URL plus a key", () => {
  assert.deepEqual(parseDatabase({ ...TOKYO, url: `${TOKYO.url}/` }), TOKYO);
  assert.equal(parseDatabase({ url: "https://evil.example.com", key: TOKYO.key }), null);
  assert.equal(parseDatabase({ url: "http://boorzbxduhsgbkilovyq.supabase.co", key: TOKYO.key }), null);
  assert.equal(parseDatabase({ url: TOKYO.url, key: "" }), null);
  assert.equal(parseDatabase(undefined), null);
  assert.equal(parseDatabase("https://boorzbxduhsgbkilovyq.supabase.co"), null);
});

test("what the console last said wins over the built-in project; a local override wins over both", () => {
  assert.deepEqual(chooseDatabase({}, undefined), BUILT_IN_DATABASE);
  assert.deepEqual(chooseDatabase({}, TOKYO), TOKYO);
  assert.deepEqual(chooseDatabase({}, { url: "garbage", key: "x" }), BUILT_IN_DATABASE);
  assert.deepEqual(chooseDatabase({ PIC_VISION_SUPABASE_URL: "http://127.0.0.1:5" }, TOKYO), { url: "http://127.0.0.1:5", key: BUILT_IN_DATABASE.key });
});

test("asking the console at launch never throws and only reports a change it could read", async () => {
  const failing = async () => { throw new Error("offline"); };
  assert.equal(await (await import("./database.js")).askConsoleForDatabase("https://console.example", failing), false);
  const notOk = async () => ({ ok: false, json: async () => ({}) });
  assert.equal(await (await import("./database.js")).askConsoleForDatabase("https://console.example", notOk), false);
  const garbage = async () => ({ ok: true, json: async () => ({ url: "https://evil.example", key: "k".repeat(30) }) });
  assert.equal(await (await import("./database.js")).askConsoleForDatabase("https://console.example", garbage), false);
});
