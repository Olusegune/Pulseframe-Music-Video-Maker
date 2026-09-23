import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";

async function boot() {
  if (import.meta.env.DEV && new URLSearchParams(location.search).has("mock")) {
    await (await import("./devmock")).installMock();
  }
  ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
    <React.StrictMode>
      <App />
    </React.StrictMode>,
  );
}
boot();
