// addCameraViaRtsp's optional `sub` param, against the same fake-RTSP-server
// harness address.test.js uses. These fake cameras answer DESCRIBE but never
// a real SDP body, so measureStreamProfile can't learn a resolution --
// exactly the case where the role-swap comparison is a no-op and the
// supplied "sub" stays the sub.
import assert from "node:assert/strict";
import { test, after } from "node:test";
import { addCameraViaRtsp } from "./store.js";
import { fakeCamera, portOf, closed, servers } from "./fakeRtspServer.js";

after(() => servers.forEach((s) => s.close()));

test("sub URL reachable -> subStreamUri gets set, shaped like the main URL", async () => {
  const mainServer = await fakeCamera();
  const subServer = await fakeCamera();
  const camera = await addCameraViaRtsp({
    label: "Court A",
    hostname: "127.0.0.1",
    port: portOf(mainServer),
    path: "/stream1",
    username: "u",
    password: "p",
    sub: { hostname: "127.0.0.1", port: portOf(subServer), path: "/stream2", username: "u2", password: "p2" },
  });
  assert.equal(camera.streamUri, `rtsp://u:p@127.0.0.1:${portOf(mainServer)}/stream1`);
  assert.equal(camera.subStreamUri, `rtsp://u2:p2@127.0.0.1:${portOf(subServer)}/stream2`);
});

test("sub URL unreachable -> add still succeeds, subStreamUri stays null", async () => {
  const mainServer = await fakeCamera();
  const deadServer = await fakeCamera();
  const deadPort = portOf(deadServer);
  await closed(deadServer);
  const camera = await addCameraViaRtsp({
    label: "Court B",
    hostname: "127.0.0.1",
    port: portOf(mainServer),
    path: "/stream1",
    username: "u",
    password: "p",
    sub: { hostname: "127.0.0.1", port: deadPort, path: "/stream2", username: "u2", password: "p2" },
  });
  assert.equal(camera.subStreamUri, null);
  assert.equal(camera.subProfile, null);
});

test("sub.hostname different from main's -> sub-stream skipped entirely, add succeeds on main alone", async () => {
  const mainServer = await fakeCamera();
  const camera = await addCameraViaRtsp({
    label: "Court C",
    hostname: "127.0.0.1",
    port: portOf(mainServer),
    path: "/stream1",
    username: "u",
    password: "p",
    sub: { hostname: "10.255.255.1", port: 554, path: "/stream2", username: "u2", password: "p2" },
  });
  assert.equal(camera.streamUri, `rtsp://u:p@127.0.0.1:${portOf(mainServer)}/stream1`);
  assert.equal(camera.subStreamUri, null);
});
