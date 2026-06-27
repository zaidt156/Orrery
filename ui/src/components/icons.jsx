// SVG icons ported from the mockup. Stroke icons inherit `currentColor`.

export function Logo() {
  return (
    <svg className="orrery-mark" viewBox="0 0 64 64" fill="none" aria-hidden="true">
      <defs>
        <radialGradient id="logoSun" cx="42%" cy="36%" r="68%">
          <stop offset="0" stopColor="#FFF3C7" />
          <stop offset="0.45" stopColor="#F2B14E" />
          <stop offset="1" stopColor="#A86B18" />
        </radialGradient>
        <linearGradient id="logoIce" x1="12" y1="11" x2="52" y2="53">
          <stop offset="0" stopColor="#E8F4FF" />
          <stop offset="1" stopColor="#78A9E6" />
        </linearGradient>
      </defs>
      <rect x="4" y="4" width="56" height="56" rx="16" fill="#111831" />
      <rect x="5.2" y="5.2" width="53.6" height="53.6" rx="14.8" stroke="#2B3658" strokeWidth="1.9" />
      <ellipse
        cx="32"
        cy="32"
        rx="25.5"
        ry="9.8"
        transform="rotate(-24 32 32)"
        stroke="url(#logoIce)"
        strokeWidth="2.7"
      />
      <ellipse
        cx="32"
        cy="32"
        rx="19"
        ry="7.2"
        transform="rotate(15 32 32)"
        stroke="#F2B14E"
        strokeWidth="2"
        opacity="0.92"
      />
      <ellipse
        cx="32"
        cy="32"
        rx="14"
        ry="5.1"
        transform="rotate(-58 32 32)"
        stroke="#E8ECF8"
        strokeWidth="1.35"
        opacity="0.5"
      />
      <circle cx="32" cy="32" r="9.3" fill="url(#logoSun)" />
      <circle cx="29.4" cy="28.7" r="2.4" fill="#fff" opacity="0.25" />
      <circle cx="53.3" cy="22.6" r="3.9" fill="#9DB9F0" stroke="#111831" strokeWidth="1.8" />
      <circle cx="13.4" cy="40.5" r="2.8" fill="#E8ECF8" stroke="#111831" strokeWidth="1.3" />
      <circle cx="43.4" cy="46.5" r="2.4" fill="#F2B14E" />
      <path d="M10.5 39.8C20.8 48.4 39.3 50.2 52.7 41.5" stroke="#9DB9F0" strokeWidth="1.5" strokeLinecap="round" opacity="0.35" />
    </svg>
  );
}

const stroke = { fill: "none", stroke: "currentColor", strokeWidth: 1.7 };

export function ChatIcon() {
  return (
    <svg viewBox="0 0 24 24" {...stroke}>
      <path d="M21 12a8 8 0 0 1-8 8H5l-2 2V12a8 8 0 0 1 8-8h2a8 8 0 0 1 8 8z" />
    </svg>
  );
}
export function DataIcon() {
  return (
    <svg viewBox="0 0 24 24" {...stroke}>
      <ellipse cx="12" cy="5.5" rx="8" ry="3" />
      <path d="M4 5.5v13c0 1.7 3.6 3 8 3s8-1.3 8-3v-13" />
      <path d="M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3" />
    </svg>
  );
}
export function DashIcon() {
  return (
    <svg viewBox="0 0 24 24" {...stroke}>
      <rect x="3.5" y="3.5" width="7" height="9" rx="1.5" />
      <rect x="13.5" y="3.5" width="7" height="5" rx="1.5" />
      <rect x="13.5" y="11.5" width="7" height="9" rx="1.5" />
      <rect x="3.5" y="15.5" width="7" height="5" rx="1.5" />
    </svg>
  );
}
export function AutoIcon() {
  return (
    <svg viewBox="0 0 24 24" {...stroke}>
      <path d="M13 2 4 14h6l-1 8 9-12h-6l1-8z" />
    </svg>
  );
}
export function AgentsIcon() {
  return (
    <svg viewBox="0 0 24 24" {...stroke}>
      <circle cx="12" cy="12" r="3.2" />
      <ellipse cx="12" cy="12" rx="9.5" ry="4.2" transform="rotate(-25 12 12)" />
      <circle cx="19.6" cy="7.4" r="1.4" fill="currentColor" stroke="none" />
    </svg>
  );
}
export function MediaIcon() {
  return (
    <svg viewBox="0 0 24 24" {...stroke}>
      <rect x="3" y="4" width="18" height="16" rx="2.5" />
      <circle cx="9" cy="10" r="1.8" />
      <path d="M3 16l5-4 4 3 3-2 6 5" />
    </svg>
  );
}
export function SettingsIcon() {
  return (
    <svg viewBox="0 0 24 24" {...stroke}>
      <circle cx="12" cy="12" r="3" />
      <path d="M19 12a7 7 0 0 0-.1-1.2l2-1.6-2-3.4-2.4 1a7 7 0 0 0-2-1.2L14 3h-4l-.5 2.6a7 7 0 0 0-2 1.2l-2.4-1-2 3.4 2 1.6A7 7 0 0 0 5 12c0 .4 0 .8.1 1.2l-2 1.6 2 3.4 2.4-1a7 7 0 0 0 2 1.2L10 21h4l.5-2.6a7 7 0 0 0 2-1.2l2.4 1 2-3.4-2-1.6c.1-.4.1-.8.1-1.2z" />
    </svg>
  );
}
export function SendIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
      <path d="M5 12h14M13 6l6 6-6 6" />
    </svg>
  );
}
export function AttachIcon() {
  return (
    <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7">
      <path d="M21 12.5l-8.5 8.5a6 6 0 0 1-8.5-8.5l9-9a4 4 0 0 1 5.7 5.7l-9 9a2 2 0 0 1-2.8-2.8l8.3-8.4" />
    </svg>
  );
}
export function PlayIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor">
      <path d="M8 5v14l11-7z" />
    </svg>
  );
}
