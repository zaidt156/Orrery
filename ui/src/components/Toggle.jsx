import { useState } from "react";

export default function Toggle({ defaultOn = false }) {
  const [on, setOn] = useState(defaultOn);
  const flip = () => setOn((v) => !v);
  return (
    <span
      className={`toggle${on ? " on" : ""}`}
      role="switch"
      aria-checked={on}
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
