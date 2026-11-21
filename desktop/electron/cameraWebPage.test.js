import assert from "node:assert/strict";
import { test } from "node:test";
import { cameraWebPageUrl } from "./cameraWebPage.js";

test("a camera on the local network opens at its own address", () => {
  assert.equal(cameraWebPageUrl("192.168.2.3"), "http://192.168.2.3/");
  assert.equal(cameraWebPageUrl(" 10.0.0.45 "), "http://10.0.0.45/");
  assert.equal(cameraWebPageUrl("172.20.1.9"), "http://172.20.1.9/");
  assert.equal(cameraWebPageUrl("169.254.10.2"), "http://169.254.10.2/");
  assert.equal(cameraWebPageUrl("Tapo-C200.local"), "http://tapo-c200.local/");
});

test("anything that is not a local camera address is refused", () => {
  for (const host of ["8.8.8.8", "172.32.0.1", "example.com", "http://192.168.1.2", "192.168.1.2/../evil", "javascript:alert(1)",
    "192.168.1.256", "user:pass@192.168.1.2", "", null, undefined, 42]) {
    assert.equal(cameraWebPageUrl(host), null, String(host));
  }
});
