import React from "react";
import ReactDOM from "react-dom/client";
import { App } from "./App";
import { T } from "./theme";

// Global resets that mirror the prototype's <head> styles.
const style = document.createElement("style");
style.textContent = `
  * { box-sizing: border-box; }
  body { margin: 0; background: ${T.bg}; }
  a { color: ${T.accent}; text-decoration: none; }
  a:hover { color: ${T.accentHover}; }
  button { font-family: inherit; }
  @keyframes pulse {
    0%   { box-shadow: 0 0 0 0 rgba(47,208,127,.55); }
    70%  { box-shadow: 0 0 0 9px rgba(47,208,127,0); }
    100% { box-shadow: 0 0 0 0 rgba(47,208,127,0); }
  }
  @keyframes dashflow { to { stroke-dashoffset: -24; } }
  ::-webkit-scrollbar { height: 8px; width: 8px; }
  ::-webkit-scrollbar-thumb { background: #2a3450; border-radius: 8px; }
  ::-webkit-scrollbar-track { background: transparent; }
`;
document.head.appendChild(style);

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
