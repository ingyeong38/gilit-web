const PATHS = {
  toll: '<path d="M3 21V9h8v12M2 9l5-6 5 6M5 21v-7h4v7M11 14l10-5v4l-10 5M15 12v4M18 10v4" />',
  fuel: '<rect x="3" y="3" width="11" height="18" rx="2"/><path d="M3 10h11M6 6h5M14 12h2a2 2 0 0 1 2 2v4a2 2 0 0 0 4 0V9l-4-4M19 6v4h3" />',
  flag: '<path d="M4 22V3m0 1c5-4 10 4 16 0v11c-6 4-11-4-16 0M9 3v11M15 5v11M4 9c5-4 10 4 16 0" />',
  arrow: '<path d="m9 18 6-6-6-6" />',
  bars: '<path d="M4 19V9M10 19V5M16 19v-7M22 19V3" />',
  calendar: '<rect x="3" y="5" width="18" height="16" rx="2" /><path d="M16 3v4M8 3v4M3 10h18" />',
  car: '<path d="m5 17-1 2v2h2l1-2h10l1 2h2v-2l-1-2-2-7H7l-2 7Z" /><path d="M7 14h10M7.5 17h.01M16.5 17h.01" />',
  chart: '<path d="M4 19V5M4 19h16" /><path d="m7 15 4-4 3 2 5-7" />',
  check: '<path d="m5 12 4 4L19 6" />',
  chevron: '<path d="m8 10 4 4 4-4" />',
  clock: '<circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" />',
  close: '<path d="m6 6 12 12M18 6 6 18" />',
  eye: '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z" /><circle cx="12" cy="12" r="3" />',
  eyeOff: '<path d="M10.6 5.1A10 10 0 0 1 12 5c6.5 0 10 7 10 7a17 17 0 0 1-3.2 4.2M6.6 6.6C3.7 8.4 2 12 2 12s3.5 7 10 7a9.7 9.7 0 0 0 5.4-1.6" /><path d="M9.9 9.9a3 3 0 0 0 4.2 4.2M3 3l18 18" />',
  home: '<path d="m3 11 9-8 9 8" /><path d="M5 10v10h14V10M9 20v-6h6v6" />',
  link: '<path d="M10 14a4 4 0 0 0 6 .4l3-3a4 4 0 0 0-5.7-5.7l-1.3 1.3" /><path d="M14 10a4 4 0 0 0-6-.4l-3 3a4 4 0 0 0 5.7 5.7l1.3-1.3" />',
  lock: '<rect x="4" y="11" width="16" height="10" rx="2" /><path d="M8 11V7a4 4 0 0 1 8 0v4" />',
  location: '<path d="M20 10c0 5-8 11-8 11S4 15 4 10a8 8 0 1 1 16 0Z" /><circle cx="12" cy="10" r="2.5" />',
  logout: '<path d="M10 17l5-5-5-5M15 12H3M21 19V5a2 2 0 0 0-2-2h-6" />',
  mail: '<rect x="3" y="5" width="18" height="14" rx="2" /><path d="m3 7 9 6 9-6" />',
  menu: '<path d="M4 7h16M4 12h16M4 17h16" />',
  route: '<circle cx="6" cy="18" r="2" /><circle cx="18" cy="6" r="2" /><path d="M8 18h3a3 3 0 0 0 3-3V9a3 3 0 0 1 3-3h1" />',
  search: '<circle cx="11" cy="11" r="7" /><path d="m20 20-4-4" />',
  spark: '<path d="m12 3 1.2 4.2L17 9l-3.8 1.8L12 15l-1.2-4.2L7 9l3.8-1.8L12 3Z" /><path d="m19 15 .6 2.2L22 18l-2.4.8L19 21l-.6-2.2L16 18l2.4-.8L19 15ZM5 3l.6 2.2L8 6l-2.4.8L5 9l-.6-2.2L2 6l2.4-.8L5 3Z" />',
  star: '<path d="m12 3 2.8 5.7 6.2.9-4.5 4.4 1.1 6.2-5.6-2.9-5.6 2.9 1.1-6.2L3 9.6l6.2-.9L12 3Z" />',
  swap: '<path d="M7 7h11l-3-3M17 17H6l3 3" />',
  user: '<circle cx="12" cy="8" r="4" /><path d="M4 21a8 8 0 0 1 16 0" />',
  wallet: '<path d="M4 6h14a2 2 0 0 1 2 2v11H4a2 2 0 0 1-2-2V6a3 3 0 0 1 3-3h12v3" /><path d="M16 11h4v4h-4a2 2 0 0 1 0-4Z" />',
};

export function icon(name, { size = 20, filled = false } = {}) {
  return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="${filled ? "currentColor" : "none"}" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${PATHS[name]}</svg>`;
}

// HTML에 적어 둔 <i data-icon="name" data-size="20"></i> 자리를 SVG로 바꾼다.
export function renderIcons(root = document) {
  root.querySelectorAll("[data-icon]").forEach((el) => {
    el.outerHTML = icon(el.dataset.icon, {
      size: Number(el.dataset.size) || 20,
      filled: "filled" in el.dataset,
    });
  });
}
