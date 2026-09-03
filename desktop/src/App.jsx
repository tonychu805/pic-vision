import { useState } from "react";
import TitleBar from "./components/TitleBar.jsx";
import Sidebar from "./components/Sidebar.jsx";
import CamerasPage from "./pages/CamerasPage.jsx";
import CameraDetailPage from "./pages/CameraDetailPage.jsx";
import { configuredCard } from "./lib/cameraView.js";
import ScheduleOverviewPage from "./pages/ScheduleOverviewPage.jsx";
import ScheduleEditorPage from "./pages/ScheduleEditorPage.jsx";
import AlertsPage from "./pages/AlertsPage.jsx";
import CredentialsPage from "./pages/CredentialsPage.jsx";
import SettingsPage from "./pages/SettingsPage.jsx";
import CloudPage from "./pages/CloudPage.jsx";

export default function App() {
  const [nav, setNav] = useState("cameras");
  const [selectedCard, setSelectedCard] = useState(null);
  const [scheduleCamera, setScheduleCamera] = useState(null);
  const [cameraCount, setCameraCount] = useState(0);

  const openCamera = (card) => {
    setSelectedCard(card);
    setNav("detail");
  };

  const backToGrid = () => {
    setSelectedCard(null);
    setNav("cameras");
  };

  const editSchedule = (camera) => {
    setScheduleCamera(camera);
    setNav("scheduleDetail");
  };

  const backToScheduleOverview = () => {
    setScheduleCamera(null);
    setNav("schedule");
  };

  return (
    <div
      style={{
        width: "100vw",
        height: "100vh",
        display: "flex",
        flexDirection: "column",
        borderRadius: 12,
        overflow: "hidden",
        background: "var(--color-bg)",
      }}
    >
      <TitleBar />
      <div style={{ flex: 1, minHeight: 0, display: "flex" }}>
        <Sidebar
          nav={nav === "detail" ? "cameras" : nav === "scheduleDetail" ? "schedule" : nav}
          onNavigate={(k) => { setSelectedCard(null); setScheduleCamera(null); setNav(k); }}
          deviceCount={cameraCount}
        />
        <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column" }}>
          {/* Stays mounted (just hidden) even while another page is showing,
              instead of unmounting -- discovery/sweep scan results used to
              reset to nothing on every visit because unmounting wiped them
              (operator report, 2026-09-01: "the scanning screen seems
              stateless"). `active` still drives a cheap refresh of the
              *configured* camera list on return, since that can genuinely
              change elsewhere (a rename/removal on the detail page) while
              this tab was hidden -- only the real network scan is skipped. */}
          <div style={{ display: nav === "cameras" ? "flex" : "none", flex: 1, minWidth: 0, flexDirection: "column" }}>
            <CamerasPage onOpenCamera={openCamera} onCameraCountChange={setCameraCount} active={nav === "cameras"} />
          </div>
          {nav === "detail" && selectedCard && (
            <CameraDetailPage
              card={selectedCard}
              onBack={backToGrid}
              onCameraRemoved={backToGrid}
              onCameraRenamed={(camera) => {
                // Keep the card's existing connection state -- a rename
                // doesn't change whether the camera is actually reachable,
                // so resetting to "checking" here would be a lie.
                setSelectedCard((prev) => configuredCard(camera, prev.state));
              }}
            />
          )}
          {nav === "schedule" && <ScheduleOverviewPage onEditCamera={editSchedule} />}
          {nav === "scheduleDetail" && scheduleCamera && (
            <ScheduleEditorPage camera={scheduleCamera} onBack={backToScheduleOverview} />
          )}
          {nav === "alerts" && <AlertsPage />}
          {nav === "credentials" && <CredentialsPage />}
          {nav === "settings" && <SettingsPage />}
          {nav === "cloud" && <CloudPage />}
        </div>
      </div>
    </div>
  );
}
