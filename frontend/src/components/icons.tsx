/**
 * Inline SVG icon set (stroke style, lucide-inspired).
 *
 * Emoji were replaced for three reasons: they render differently on every
 * OS (and can be missing entirely on stripped-down devices our users hold),
 * they cannot inherit the theme's colors, and a maritime instrument panel
 * reads as more trustworthy with drawn glyphs than with pictographs.
 *
 * All icons: 24×24 viewBox, stroke = currentColor, no fills except where a
 * solid dot is the glyph. Size via the `size` prop (default 16).
 */

interface IconProps {
  size?: number;
  className?: string;
}

function Svg({ size = 16, className, children }: IconProps & { children: React.ReactNode }) {
  return (
    <svg
      aria-hidden="true"
      focusable="false"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
    >
      {children}
    </svg>
  );
}

export function MicIcon(p: IconProps) {
  return (
    <Svg {...p}>
      <rect x="9" y="2.5" width="6" height="11" rx="3" />
      <path d="M5 11a7 7 0 0 0 14 0" />
      <path d="M12 18v3.5" />
    </Svg>
  );
}

export function StopIcon(p: IconProps) {
  return (
    <Svg {...p}>
      <rect x="6.5" y="6.5" width="11" height="11" rx="1.5" fill="currentColor" stroke="none" />
    </Svg>
  );
}

export function SpeakerIcon(p: IconProps) {
  return (
    <Svg {...p}>
      <path d="M11 5 6.5 9H3v6h3.5L11 19V5z" />
      <path d="M15.5 8.5a5 5 0 0 1 0 7" />
      <path d="M18.5 6a9 9 0 0 1 0 12" />
    </Svg>
  );
}

export function StopSoundIcon(p: IconProps) {
  return (
    <Svg {...p}>
      <path d="M11 5 6.5 9H3v6h3.5L11 19V5z" />
      <path d="m16 9.5 5 5" />
      <path d="m21 9.5-5 5" />
    </Svg>
  );
}

export function TempIcon(p: IconProps) {
  return (
    <Svg {...p}>
      <path d="M10 4a2 2 0 1 1 4 0v9.3a4.5 4.5 0 1 1-4 0V4z" />
      <circle cx="12" cy="17" r="1.6" fill="currentColor" stroke="none" />
      <path d="M12 15.5V9" />
    </Svg>
  );
}

export function LeafIcon(p: IconProps) {
  return (
    <Svg {...p}>
      <path d="M4 20c8 0 15-4 16-16C10 4 4 8 4 15c0 2 .8 3.8 2 5z" />
      <path d="M4 20c3-6 7-9 11-11" />
    </Svg>
  );
}

export function WaveIcon(p: IconProps) {
  return (
    <Svg {...p}>
      <path d="M2 8.5c2.5 0 2.5 2 5 2s2.5-2 5-2 2.5 2 5 2 2.5-2 5-2" />
      <path d="M2 13c2.5 0 2.5 2 5 2s2.5-2 5-2 2.5 2 5 2 2.5-2 5-2" />
      <path d="M2 17.5c2.5 0 2.5 2 5 2s2.5-2 5-2 2.5 2 5 2 2.5-2 5-2" />
    </Svg>
  );
}

export function WindIcon(p: IconProps) {
  return (
    <Svg {...p}>
      <path d="M3 8h10a3 3 0 1 0-3-3" />
      <path d="M3 12.5h15a3 3 0 1 1-3 3" />
      <path d="M3 17h7a2.5 2.5 0 1 1-2.5 2.5" />
    </Svg>
  );
}

export function CurrentIcon(p: IconProps) {
  return (
    <Svg {...p}>
      <path d="M20 12a8 8 0 1 1-2.34-5.66" />
      <path d="M20 3v4h-4" />
      <path d="M9.5 12a2.5 2.5 0 1 0 2.5-2.5" />
    </Svg>
  );
}

export function PinIcon(p: IconProps) {
  return (
    <Svg {...p}>
      <path d="M12 21s-7-6.1-7-11a7 7 0 0 1 14 0c0 4.9-7 11-7 11z" />
      <circle cx="12" cy="10" r="2.5" />
    </Svg>
  );
}

export function CompassIcon(p: IconProps) {
  return (
    <Svg {...p}>
      <circle cx="12" cy="12" r="9" />
      <path d="m15.5 8.5-2 5-5 2 2-5 5-2z" />
    </Svg>
  );
}

export function ClockIcon(p: IconProps) {
  return (
    <Svg {...p}>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5l3.5 2" />
    </Svg>
  );
}

export function CheckCircleIcon(p: IconProps) {
  return (
    <Svg {...p}>
      <circle cx="12" cy="12" r="9" />
      <path d="m8.5 12.5 2.5 2.5 5-5.5" />
    </Svg>
  );
}

export function AlertTriangleIcon(p: IconProps) {
  return (
    <Svg {...p}>
      <path d="M10.3 4.2 2.9 17.5A1.9 1.9 0 0 0 4.6 20.4h14.8a1.9 1.9 0 0 0 1.7-2.9L13.7 4.2a1.9 1.9 0 0 0-3.4 0z" />
      <path d="M12 9v4.5" />
      <circle cx="12" cy="17" r="0.9" fill="currentColor" stroke="none" />
    </Svg>
  );
}

export function BanIcon(p: IconProps) {
  return (
    <Svg {...p}>
      <circle cx="12" cy="12" r="9" />
      <path d="m5.7 5.7 12.6 12.6" />
    </Svg>
  );
}
