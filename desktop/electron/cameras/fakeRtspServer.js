// A real local TCP server on 127.0.0.1 that answers any RTSP DESCRIBE with
// 200 OK and an empty body -- enough for describeRtspStream to succeed, not
// enough for measureStreamProfile to learn a real resolution. No real
// camera, stream or frame is involved (this project's standing rule).
// Shared by address.test.js and subStream.test.js so there's one harness.
import { createServer } from "node:net";

export const servers = [];

export function fakeCamera() {
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

export const portOf = (server) => server.address().port;
export const closed = (server) => new Promise((r) => server.close(r));
