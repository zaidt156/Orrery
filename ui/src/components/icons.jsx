// SVG icons ported from the mockup. Stroke icons inherit `currentColor`.

export function Logo() {
  // Mirrors ui/public/orrery-mark.svg (the favicon) so the in-app mark and favicon match.
  return (
    <svg className="orrery-mark" viewBox="0 0 64 64" fill="none" aria-hidden="true">
      <defs>
        <linearGradient id="markBg" x1="4" y1="4" x2="60" y2="60" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor="#151F3E" />
          <stop offset="0.58" stopColor="#0B1020" />
          <stop offset="1" stopColor="#070A14" />
        </linearGradient>
        <radialGradient id="markSun" cx="38%" cy="28%" r="72%">
          <stop offset="0" stopColor="#FFF7D7" />
          <stop offset="0.32" stopColor="#FFD783" />
          <stop offset="0.7" stopColor="#F0A638" />
          <stop offset="1" stopColor="#9B5E12" />
        </radialGradient>
        <radialGradient id="markBlue" cx="34%" cy="25%" r="72%">
          <stop offset="0" stopColor="#E1F5FF" />
          <stop offset="0.38" stopColor="#89BDED" />
          <stop offset="1" stopColor="#163C71" />
        </radialGradient>
        <filter id="markShadow" x="-25%" y="-25%" width="150%" height="160%" colorInterpolationFilters="sRGB">
          <feDropShadow dx="0" dy="5" stdDeviation="5" floodColor="#020511" floodOpacity="0.6" />
        </filter>
      </defs>
      <rect x="3.5" y="3.5" width="57" height="57" rx="17" fill="url(#markBg)" />
      <rect x="4.75" y="4.75" width="54.5" height="54.5" rx="15.75" stroke="#2B395E" strokeWidth="1.8" />
      <g filter="url(#markShadow)">
        <path d="M10.6 22.8C20.5 9.8 40 7.6 52.4 17.1" stroke="#E8F4FF" strokeWidth="2.1" strokeLinecap="round" opacity="0.65" />
        <path d="M13.7 48.1C25.5 57.4 47.4 53.6 54.1 38.7" stroke="#78A9E6" strokeWidth="1.8" strokeLinecap="round" opacity="0.55" />
        <ellipse cx="32" cy="34.2" rx="24.6" ry="8.9" transform="rotate(-12 32 34.2)" stroke="#9DB9F0" strokeWidth="2.8" />
        <ellipse cx="32" cy="33.3" rx="18.6" ry="6.2" transform="rotate(9 32 33.3)" stroke="#F2B14E" strokeWidth="2.05" opacity="0.95" />
        <ellipse cx="32" cy="31.2" rx="13.4" ry="4.3" transform="rotate(-39 32 31.2)" stroke="#E8F4FF" strokeWidth="1.25" opacity="0.5" />
        <ellipse cx="32" cy="46" rx="17.8" ry="5.9" fill="#091023" stroke="#6F98C8" strokeWidth="1.6" />
        <ellipse cx="32" cy="48.6" rx="13.4" ry="3.8" fill="#071022" stroke="#233354" strokeWidth="1.2" />
        <path d="M32 29.3v16.5" stroke="#B9D7FF" strokeWidth="1.4" strokeLinecap="round" opacity="0.74" />
        <path d="M32 29.3v16.5" stroke="#071022" strokeWidth="3.8" strokeLinecap="round" opacity="0.48" />
        <circle cx="32" cy="26.6" r="9.6" fill="url(#markSun)" />
        <path d="M27 22.7C29 19.6 32.5 18.5 36.3 19.8" stroke="#FFFFFF" strokeWidth="1.3" strokeLinecap="round" opacity="0.55" />
        <circle cx="40.7" cy="26.1" r="1.2" fill="#FFF1C7" opacity="0.78" />
        <path d="M18.4 31.5v13.2" stroke="#7DA9D8" strokeWidth="1.35" strokeLinecap="round" />
        <circle cx="18.4" cy="28" r="4.7" fill="url(#markBlue)" stroke="#CBE8FF" strokeWidth="1" />
        <path d="M47.5 30v13.8" stroke="#7DA9D8" strokeWidth="1.35" strokeLinecap="round" />
        <circle cx="47.5" cy="26.5" r="5.1" fill="url(#markSun)" stroke="#FFE4A6" strokeWidth="1" />
        <ellipse cx="47.5" cy="26.5" rx="8" ry="2.5" transform="rotate(-24 47.5 26.5)" stroke="#F7C76A" strokeWidth="1.85" />
        <circle cx="11.9" cy="35.4" r="2.6" stroke="#E8F4FF" strokeWidth="1.6" />
        <circle cx="52.7" cy="17.7" r="2.3" stroke="#F2B14E" strokeWidth="1.5" />
      </g>
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
