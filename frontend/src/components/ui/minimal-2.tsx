"use client";

export function AsciiArt({ className }: { className?: string }) {
  return (
    <video
      className={className}
      src="https://assets.21st.dev/ascii-recipes/videos/user_3GdLUDAN6ieID1Fu8OTL6zl5Al1/d75636de-972c-4d6c-8781-0594203f1996.mp4"
      poster="https://assets.21st.dev/ascii-recipes/thumbnails/user_3GdLUDAN6ieID1Fu8OTL6zl5Al1/9e491c00-28aa-41a0-a325-2c7f061a44a0.webp"
      autoPlay
      loop
      muted
      playsInline
      aria-label="Animated ASCII art"
      style={{ display: "block", width: "100%", height: "100%", objectFit: "cover" }}
    />
  );
}
