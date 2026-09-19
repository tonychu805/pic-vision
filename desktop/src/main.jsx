import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import ErrorBoundary from "./ErrorBoundary.jsx";
import { installRendererErrorReporting } from "./lib/rendererErrors.js";
import "./index.css";

// Before the app renders, so a failure during that first render is
// reported rather than silent. See rendererErrors.js: this window is
// transparent, so an unmounted React tree is an invisible window, not a
// blank one -- which is how a real crash got described as the app
// "just disappearing" (2026-09-20).
installRendererErrorReporting({
  target: window,
  report: ({ message, stack }) => window.appAPI?.reportError?.(message, stack),
});

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </React.StrictMode>
);
