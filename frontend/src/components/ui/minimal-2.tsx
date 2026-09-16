"use client"

// AsciiArt — "Minimal", made with the 21st.dev ASCII editor and baked
// to its exact rendered output (looping video + poster). Zero dependencies:
// one <video> that fills its parent. Drop it behind or inside your content:
// <div className="relative h-96"><AsciiArt className="absolute inset-0" /></div>
// Remix the source recipe (styles, animation, palette) in the editor:
// https://21st.dev/community/ascii/editor?from=488f05af-0110-4873-87e7-5afea99778ac
export function AsciiArt({ className }: { className?: string }) {
  return (
    <video
      className={className}
      src={"https://assets.21st.dev/ascii-recipes/videos/user_3GdLUDAN6ieID1Fu8OTL6zl5Al1/d75636de-972c-4d6c-8781-0594203f1996.mp4"}
      poster={"https://assets.21st.dev/ascii-recipes/thumbnails/user_3GdLUDAN6ieID1Fu8OTL6zl5Al1/9e491c00-28aa-41a0-a325-2c7f061a44a0.webp"}
      autoPlay
      loop
      muted
      playsInline
      aria-label={"Minimal — animated ASCII art"}
      style={{
        display: "block",
        width: "100%",
        height: "100%",
        objectFit: "cover",
      }}
    />
  )
}
