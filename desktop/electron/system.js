// Real local-network info for the sidebar's "Network" panel -- cheap to get
// honestly (os.networkInterfaces()), so there's no reason to hardcode a
// fake subnet the way the mockup's static prototype data does.
import { dialog } from "electron";
import os from "node:os";

function guessCidr(ip, netmask) {
  // netmask -> prefix length (only handles the common contiguous-mask case,
  // which covers every real home/venue subnet this is meant to show).
  const bits = netmask.split(".").reduce((acc, octet) => acc + Number(octet).toString(2).split("1").length - 1, 0);
  const networkOctets = ip.split(".").map((o, i) => {
    const maskOctet = Number(netmask.split(".")[i]);
    return Number(o) & maskOctet;
  });
  return `${networkOctets.join(".")}/${bits}`;
}

export function getNetworkInfo() {
  const interfaces = os.networkInterfaces();
  for (const [name, addrs] of Object.entries(interfaces)) {
    for (const addr of addrs ?? []) {
      if (addr.family === "IPv4" && !addr.internal) {
        return { cidr: guessCidr(addr.address, addr.netmask), interfaceName: name, address: addr.address };
      }
    }
  }
  return { cidr: null, interfaceName: null, address: null };
}

// Native file picker for a camera's calib.json (PIC-68) -- the secondary
// "import an existing file" path now that CalibrationControl's live
// snapshot-and-click flow (calibration.js) is the primary one. store.js's
// setCalibPath just remembers whatever path comes back; this is the only
// place that actually asks the OS for one.
export async function pickCalibFile() {
  const result = await dialog.showOpenDialog({
    title: "Select calibration file",
    properties: ["openFile"],
    filters: [{ name: "Calibration JSON", extensions: ["json"] }],
  });
  if (result.canceled || result.filePaths.length === 0) return null;
  return result.filePaths[0];
}

// Native file picker for a "sample clip" camera (2026-09-03) -- a local
// video file uploaded to stand in for a live camera, so calibration and
// the cloud pipeline can be tested without one. store.js's
// addCameraFromSampleClip does the actual copy/validation; this only asks
// the OS for a path.
export async function pickVideoFile() {
  const result = await dialog.showOpenDialog({
    title: "Select a sample video clip",
    properties: ["openFile"],
    filters: [{ name: "Video", extensions: ["mp4", "mov", "mkv", "avi"] }],
  });
  if (result.canceled || result.filePaths.length === 0) return null;
  return result.filePaths[0];
}
