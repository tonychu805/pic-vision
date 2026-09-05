// On-demand live view (PIC-?? , operator's own proposal, 2026-09-05):
// a "Live view" button on the camera detail page pops up a modal showing
// the actual RTSP stream, started only while that popup is open --
// deliberately not a continuous per-card preview (that was considered and
// rejected for bandwidth/CPU cost -- see the day's conversation). One
// live view at a time (a single popup), matching capture.js's own
// module-level "one thing running per concern" convention.
//
// Browsers can't play RTSP directly, so this transcodes to MJPEG
// (ffmpeg -f mjpeg to stdout) and re-wraps that as a proper
// multipart/x-mixed-replace HTTP response a plain <img> tag can render
// natively -- no WebRTC/HLS signaling or extra native deps, and low
// enough latency for "check the camera's actually pointed at the court"
// use. ffmpeg's own mjpeg muxer doesn't do HTTP multipart framing itself,
// so frames are split by hand on JPEG SOI/EOI markers (0xFFD8/0xFFD9).
import { spawn } from "node:child_process";
import http from "node:http";
import { authenticatedStreamUri } from "./capture.js";

const BOUNDARY = "picvisionlive";
const SOI = Buffer.from([0xff, 0xd8]);
const EOI = Buffer.from([0xff, 0xd9]);

let current = null; // { proc, server, clients: Set<res> }

function broadcastFrame(clients, frame) {
  const head = `--${BOUNDARY}\r\nContent-Type: image/jpeg\r\nContent-Length: ${frame.length}\r\n\r\n`;
  for (const res of clients) {
    res.write(head);
    res.write(frame);
    res.write("\r\n");
  }
}

export async function startLiveView(camera) {
  await stopLiveView(); // only one at a time

  const url = authenticatedStreamUri(camera);
  const proc = spawn("ffmpeg", [
    "-rtsp_transport", "tcp",
    "-i", url,
    "-f", "mjpeg",
    "-q:v", "5",
    "-r", "10",
    "-",
  ], { stdio: ["ignore", "pipe", "pipe"] });

  const clients = new Set();
  let buffer = Buffer.alloc(0);
  let stderrTail = "";
  proc.stderr.on("data", (chunk) => {
    stderrTail = (stderrTail + chunk.toString()).slice(-4000);
  });
  proc.stdout.on("data", (chunk) => {
    buffer = Buffer.concat([buffer, chunk]);
    for (;;) {
      const start = buffer.indexOf(SOI);
      if (start === -1) {
        buffer = Buffer.alloc(0);
        break;
      }
      const end = buffer.indexOf(EOI, start + 2);
      if (end === -1) {
        if (start > 0) buffer = buffer.subarray(start); // drop garbage before the next frame's start
        break; // wait for more data to complete this frame
      }
      broadcastFrame(clients, buffer.subarray(start, end + 2));
      buffer = buffer.subarray(end + 2);
    }
  });

  const server = http.createServer((req, res) => {
    res.writeHead(200, {
      "Content-Type": `multipart/x-mixed-replace; boundary=${BOUNDARY}`,
      "Cache-Control": "no-store",
      Connection: "close",
    });
    clients.add(res);
    req.on("close", () => clients.delete(res));
  });

  current = { proc, server, clients };

  return new Promise((resolve, reject) => {
    const onExit = (code) => {
      if (current?.proc === proc) current = null;
      reject(new Error(stderrTail.trim().split("\n").pop() || `ffmpeg exited (code ${code})`));
    };
    proc.once("exit", onExit);
    server.listen(0, "127.0.0.1", () => {
      proc.off("exit", onExit); // past the startup race -- a later exit is reported to the <img>'s own onerror, not this promise
      resolve({ url: `http://127.0.0.1:${server.address().port}/` });
    });
  });
}

export async function stopLiveView() {
  if (!current) return;
  const { proc, server, clients } = current;
  current = null;
  for (const res of clients) res.end();
  await new Promise((resolve) => server.close(resolve));
  proc.kill("SIGKILL"); // discard-only stream, no output file to corrupt (unlike capture.js's recordings)
}
