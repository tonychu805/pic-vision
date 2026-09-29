// updateCameraAddress, against fake RTSP "cameras": local servers that
// answer DESCRIBE with 200 the way a camera accepting its credentials does.
// No real camera, stream or frame is involved (this project's standing rule).
import assert from "node:assert/strict";
import { test, after } from "node:test";
import { createServer } from "node:net";
import { addCameraViaRtsp, updateCameraAddress, listCameras, isDifferentCamera, ADDRESS_ERRORS } from "./store.js";

const servers = [];
function fakeCamera() {
  const server = createServer((socket) => {
    socket.on("error", () => {});
    socket.on("data", (chunk) => {
      const cseq = /CSeq:\s*(\d+)/i.exec(chunk.toString())?.[1] ?? "1";
      socket.write(`RTSP/1.0 200 OK\r\nCSeq: ${cseq}\r\nContent-Length: 0\r\n\r\n`);
    });
  });
  servers.push(server);
  return new Promise((resolve) => server.listen(0, "127.0.0.1", () => resolve(server)));
}
const portOf = (server) => server.address().port;
const closed = (server) => new Promise((r) => server.close(r));
after(() => servers.forEach((s) => s.close()));

async function cameraAt(server, label) {
  return addCameraViaRtsp({ label, hostname: "127.0.0.1", port: portOf(server), path: "/stream1", username: "u", password: "p" });
}

test("a camera that moved to a new address keeps its identity, name and stream path", async () => {
  const oldHome = await fakeCamera();
  const newHome = await fakeCamera();
  const camera = await cameraAt(oldHome, "Court 1");
  await closed(oldHome); // stops answering there

  const updated = await updateCameraAddress(camera.id, "127.0.0.1", portOf(newHome));
  assert.equal(updated.id, camera.id); // same id: the console keeps its calibration
  assert.equal(updated.label, "Court 1");
  assert.equal(updated.port, portOf(newHome));
  const stored = listCameras().find((c) => c.id === camera.id);
  assert.equal(stored.streamUri, `rtsp://u:p@127.0.0.1:${portOf(newHome)}/stream1`);
});

// Paired: an address where nothing answers must change nothing.
test("an address where nothing answers is refused, and the camera is left as it was", async () => {
  const home = await fakeCamera();
  const camera = await cameraAt(home, "Court 2");
  const nowhere = await fakeCamera();
  const deadPort = portOf(nowhere);
  await closed(nowhere);
  await assert.rejects(updateCameraAddress(camera.id, "127.0.0.1", deadPort));
  const stored = listCameras().find((c) => c.id === camera.id);
  assert.equal(stored.port, portOf(home));
  assert.equal(stored.streamUri, `rtsp://u:p@127.0.0.1:${portOf(home)}/stream1`);
});

test("an address another camera already uses is refused, naming that camera", async () => {
  const a = await fakeCamera();
  const b = await fakeCamera();
  const first = await cameraAt(a, "Court 3");
  await cameraAt(b, "Court 4");
  await assert.rejects(updateCameraAddress(first.id, "127.0.0.1", portOf(b)), { message: ADDRESS_ERRORS.taken("Court 4") });
});

test("a different serial number means a different camera", () => {
  assert.equal(isDifferentCamera({ serialNumber: "SN-1" }, { serialNumber: "SN-2" }), true);
});

// Paired: the same serial, or no serial to compare (RTSP cameras report
// none), must not block the change.
test("the same serial, or no serial to compare, is not a different camera", () => {
  assert.equal(isDifferentCamera({ serialNumber: "SN-1" }, { serialNumber: " SN-1 " }), false);
  assert.equal(isDifferentCamera({ serialNumber: null }, { serialNumber: "SN-2" }), false);
  assert.equal(isDifferentCamera({ serialNumber: "SN-1" }, {}), false);
});
