import { useState } from "react";
import TitleBar from "./components/TitleBar.jsx";
import Sidebar from "./components/Sidebar.jsx";
import CamerasPage from "./pages/CamerasPage.jsx";
import CameraDetailPage from "./pages/CameraDetailPage.jsx";
import AlertsPage from "./pages/AlertsPage.jsx";
import CredentialsPage from "./pages/CredentialsPage.jsx";
import SettingsPage from "./pages/SettingsPage.jsx";

export default function App() {
  const [nav, setNav] = useState("cameras");
  const [selectedCard, setSelectedCard] = useState(null);
  const [cameraCount, setCameraCount] = useState(0);

  const openCamera = (card) => {
    setSelectedCard(card);
    setNav("detail");
  };

  const backToGrid = () => {
    setSelectedCard(null);
    setNav("cameras");
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
        <Sidebar nav={nav === "detail" ? "cameras" : nav} onNavigate={(k) => { setSelectedCard(null); setNav(k); }} deviceCount={cameraCount} />
        <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column" }}>
          {nav === "cameras" && <CamerasPage onOpenCamera={openCamera} onCameraCountChange={setCameraCount} />}
          {nav === "detail" && selectedCard && (
            <CameraDetailPage
              card={selectedCard}
              onBack={backToGrid}
              onCameraSignedIn={(camera) => {
                setSelectedCard({ key: camera.id, kind: "configured", camera });
              }}
            />
          )}
          {nav === "alerts" && <AlertsPage />}
          {nav === "credentials" && <CredentialsPage />}
          {nav === "settings" && <SettingsPage />}
        </div>
      </div>
    </div>
  );
}
