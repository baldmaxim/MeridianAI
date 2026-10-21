import type { FC } from 'react';

/* Inline SVG compass mark from branding/meridian-logos.html */
export const LogoMark: FC = () => (
  <svg width="28" height="28" viewBox="0 0 28 28" fill="none">
    <circle cx="14" cy="14" r="12" stroke="var(--accent)" strokeWidth="1" opacity="0.25"/>
    <circle cx="14" cy="14" r="7" stroke="var(--accent)" strokeWidth="1.5" opacity="0.6"/>
    <circle cx="14" cy="14" r="2.5" fill="var(--accent)"/>
    <line x1="14" y1="2" x2="14" y2="6" stroke="var(--accent)" strokeWidth="1.5" strokeLinecap="round"/>
    <line x1="14" y1="22" x2="14" y2="26" stroke="var(--accent)" strokeWidth="1.5" strokeLinecap="round"/>
    <line x1="2" y1="14" x2="6" y2="14" stroke="var(--accent)" strokeWidth="1.5" strokeLinecap="round"/>
    <line x1="22" y1="14" x2="26" y2="14" stroke="var(--accent)" strokeWidth="1.5" strokeLinecap="round"/>
  </svg>
);
