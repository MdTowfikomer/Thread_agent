import React from 'react';

interface BorderBeamProps {
  className?: string;
  size?: number;
  duration?: number;
  borderWidth?: number;
  anchor?: number;
  colorFrom?: string;
  colorTo?: string;
  delay?: number;
}

export const BorderBeam: React.FC<BorderBeamProps> = ({
  className = "",
  size = 150,
  duration = 8,
  borderWidth = 1.5,
  anchor = 90,
  colorFrom = "#10b981", // Emerald accent
  colorTo = "#059669",
  delay = 0,
}) => {
  return (
    <div
      style={
        {
          "--size": size,
          "--duration": `${duration}s`,
          "--anchor": `${anchor}%`,
          "--border-width": `${borderWidth}px`,
          "--color-from": colorFrom,
          "--color-to": colorTo,
          "--delay": `-${delay}s`,
        } as React.CSSProperties
      }
      className={`pointer-events-none absolute inset-0 rounded-[inherit] border border-transparent [mask-clip:padding-box,border-box] [mask-composite:intersect] [mask-image:linear-gradient(transparent,transparent),linear-gradient(#000,#000)] before:absolute before:aspect-square before:w-[calc(var(--size)*1px)] before:animate-border-beam before:[animation-delay:var(--delay)] before:[background-image:radial-gradient(var(--color-from)_0%,var(--color-to)_50%,transparent_100%)] before:[offset-anchor:calc(var(--anchor)*1%)_50%] before:[offset-path:rect(0_auto_auto_0_round_calc(var(--size)*1px))] ${className}`}
    />
  );
};
