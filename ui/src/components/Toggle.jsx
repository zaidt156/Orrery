import { useState } from "react";

// Controlled when `on`/`onClick` are passed (real settings); falls back to local state for
// purely visual uses. Prefer the controlled form — an uncontrolled toggle changes nothing.
export default function Toggle({ on, onClick, defaultOn = false }) {
  const controlled = typeof on === "boolean";
  const [local, setLocal] = useState(defaultOn);
  const value = controlled ? on : local;
  const flip = () => (controlled ? onClick?.() : setLocal((v) => !v));
  return (
    <span
      className={`toggle${value ? " on" : ""}`}
      role="switch"
      aria-checked={value}
      tabIndex={0}
      onClick={flip}
      onKeyDown={(e) => {
        if (e.key === " " || e.key === "Enter") {
          e.preventDefault();
          flip();
        }
      }}
    />
  );
}
