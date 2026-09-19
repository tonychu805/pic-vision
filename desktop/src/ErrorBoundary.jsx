import React from "react";
import { formatRendererError } from "./lib/rendererErrors.js";

// The difference between a broken app and a missing one.
//
// Without this, an error anywhere in the tree unmounts the entire root
// (React 18's behaviour for an uncaught render error) and the window --
// transparent by design, so App.jsx can draw its own rounded corners --
// has nothing left to paint. The operator sees the desktop through it and
// reports, accurately, that the app disappeared. Nothing is logged, in
// either process, because nothing crashed.
//
// A class component because that is still the only way to catch a render
// error in React; there is no hook equivalent.
export default class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { error: null, stack: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    const { message, stack } = formatRendererError(error, info?.componentStack);
    this.setState({ stack });
    // Into the Log tab and crash.log, alongside the main process's own
    // failures -- so "what happened?" has one answer in one place
    // regardless of which half of the app broke.
    try {
      window.appAPI?.reportError?.(message, stack);
    } catch { /* already broken */ }
  }

  render() {
    if (!this.state.error) return this.props.children;
    const { message, stack } = formatRendererError(this.state.error, null);
    return (
      // An OPAQUE background is the point, not decoration: the window
      // itself is transparent, so a fallback that didn't paint one would
      // be exactly as invisible as the unmounted tree it replaces.
      <div style={{
        position: "fixed", inset: 0, background: "#16161a", color: "#eaeaf0",
        padding: "48px 40px", overflow: "auto",
        font: "13px/1.6 ui-monospace, SFMono-Regular, Menlo, monospace",
        WebkitAppRegion: "drag",
      }}>
        <div style={{ maxWidth: 780, margin: "0 auto", WebkitAppRegion: "no-drag" }}>
          <div style={{ fontSize: 20, fontFamily: "system-ui, sans-serif", marginBottom: 10 }}>
            Something in the app broke
          </div>
          <p style={{ fontFamily: "system-ui, sans-serif", color: "#a8a8b8", marginTop: 0 }}>
            The app is still running and nothing you recorded has been lost. This has been
            written to the Log tab. Reloading usually gets you back to where you were.
          </p>
          <button
            onClick={() => window.location.reload()}
            style={{
              font: "500 13px system-ui, sans-serif", color: "#16161a", background: "#eaeaf0",
              border: 0, borderRadius: 7, padding: "8px 16px", cursor: "pointer", margin: "6px 0 22px",
            }}
          >
            Reload the app
          </button>
          <div style={{ color: "#ff9d9d", marginBottom: 12, whiteSpace: "pre-wrap" }}>{message}</div>
          {/* Shown, not hidden behind a disclosure: the whole reason this
              screen exists is that the last two crashes cost a round trip
              for exactly this text. */}
          {stack && (
            <pre style={{ color: "#8a8a9a", whiteSpace: "pre-wrap", margin: 0, fontSize: 12 }}>{stack}</pre>
          )}
        </div>
      </div>
    );
  }
}
