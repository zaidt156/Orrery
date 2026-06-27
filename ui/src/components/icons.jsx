// SVG icons ported from the mockup. Stroke icons inherit `currentColor`.

export function Logo() {
  // Mirrors ui/public/orrery-mark.svg (the favicon) so the in-app mark and favicon match.
  return (
    <svg className="orrery-mark" viewBox="0 0 64 64" fill="none" aria-hidden="true">
      <defs>
        <radialGradient id="markSun" cx="34%" cy="30%" r="72%">
          <stop offset="0" stopColor="#FFF2BF" />
          <stop offset="0.48" stopColor="#F2B14E" />
          <stop offset="1" stopColor="#A96A18" />
        </radialGradient>
        <linearGradient id="markTile" x1="6" y1="5" x2="58" y2="60" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor="#152349" />
          <stop offset="1" stopColor="#071022" />
        </linearGradient>
        <linearGradient id="markIce" x1="13" y1="17" x2="52" y2="47" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor="#EAF5FF" />
          <stop offset="1" stopColor="#82ADE8" />
        </linearGradient>
      </defs>
      <rect x="4" y="4" width="56" height="56" rx="15" fill="url(#markTile)" />
      <rect x="5.25" y="5.25" width="53.5" height="53.5" rx="13.75" stroke="#2B395E" strokeWidth="1.5" />
      <circle cx="32" cy="32" r="19.5" stroke="#E8ECF8" strokeWidth="5.5" opacity="0.96" />
      <path d="M13.7 40.6C25.3 51.8 47 49.4 55.3 35.3" stroke="url(#markIce)" strokeWidth="4.2" strokeLinecap="round" />
      <path d="M13.1 31.8C13.1 20.9 21.1 12.4 31.4 12.4" stroke="#071022" strokeWidth="7.2" strokeLinecap="round" />
      <circle cx="32" cy="32" r="8.1" fill="url(#markSun)" />
      <circle cx="50.2" cy="19.8" r="4.3" fill="#F2B14E" stroke="#071022" strokeWidth="2" />
      <circle cx="15.6" cy="43.5" r="3.4" fill="#9DB9F0" stroke="#071022" strokeWidth="1.7" />
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
