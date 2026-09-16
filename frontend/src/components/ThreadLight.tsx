import { useEffect, useRef } from 'react';

interface ThreadLightProps {
  className?: string;
}

const clamp = (value: number) => Math.max(0, Math.min(1, value));

const smoothNoise = (x: number, y: number, time: number) => {
  const a = Math.sin(x * 1.7 + time * 0.75);
  const b = Math.sin(y * 2.1 - time * 0.48);
  const c = Math.sin((x + y) * 1.25 + time * 0.35);
  const d = Math.sin(Math.hypot(x - 0.55, y - 0.48) * 13 - time * 0.62);
  return clamp((a + b + c + d + 4) / 8);
};

const mix = (start: number, end: number, amount: number) => Math.round(start + (end - start) * amount);

const smokeColor = (amount: number) => {
  const shadow = [3, 18, 14];
  const mid = [14, 124, 90];
  const light = [244, 255, 199];
  const pivot = amount < 0.62 ? amount / 0.62 : (amount - 0.62) / 0.38;
  const from = amount < 0.62 ? shadow : mid;
  const to = amount < 0.62 ? mid : light;
  return `rgb(${mix(from[0], to[0], pivot)}, ${mix(from[1], to[1], pivot)}, ${mix(from[2], to[2], pivot)})`;
};

export function ThreadLight({ className }: ThreadLightProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const context = canvas.getContext('2d');
    if (!context) return;

    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const sourceCanvas = document.createElement('canvas');
    const sourceContext = sourceCanvas.getContext('2d', { willReadFrequently: true });
    if (!sourceContext) return;
    let animationFrame = 0;
    let width = 0;
    let height = 0;

    const resize = () => {
      const bounds = canvas.getBoundingClientRect();
      const scale = Math.min(window.devicePixelRatio || 1, 2);
      width = Math.max(1, Math.floor(bounds.width));
      height = Math.max(1, Math.floor(bounds.height));
      canvas.width = Math.floor(width * scale);
      canvas.height = Math.floor(height * scale);
      context.setTransform(scale, 0, 0, scale, 0, 0);
    };

    const draw = (elapsed: number) => {
      const time = reduceMotion ? 0.6 : elapsed / 1000;
      const cellSize = 8;
      const columns = Math.ceil(width / cellSize);
      const rows = Math.ceil(height / cellSize);
      sourceCanvas.width = columns;
      sourceCanvas.height = rows;

      for (let row = 0; row < rows; row += 1) {
        for (let column = 0; column < columns; column += 1) {
          const nx = column / Math.max(columns - 1, 1);
          const ny = row / Math.max(rows - 1, 1);
          const shimmer = Math.sin((nx * 5.5 + ny * 3.6) * Math.PI + time * 1.7) * 0.045;
          const smoke = clamp(smoothNoise(nx * 2.15, ny * 2.15, time) + shimmer);
          sourceContext.fillStyle = smokeColor(smoke);
          sourceContext.fillRect(column, row, 1, 1);
        }
      }

      const sourcePixels = sourceContext.getImageData(0, 0, columns, rows).data;
      context.clearRect(0, 0, width, height);
      context.fillStyle = '#090909';
      context.fillRect(0, 0, width, height);

      context.save();
      context.globalCompositeOperation = 'screen';
      const sourceRadius = Math.max(width, height) * 0.68;
      const sourceGlow = context.createRadialGradient(width * 0.56, height * 0.48, 0, width * 0.56, height * 0.48, sourceRadius);
      sourceGlow.addColorStop(0, 'rgba(244, 255, 199, 0.08)');
      sourceGlow.addColorStop(0.36, 'rgba(124, 229, 119, 0.04)');
      sourceGlow.addColorStop(1, 'rgba(3, 18, 14, 0)');
      context.fillStyle = sourceGlow;
      context.fillRect(0, 0, width, height);
      context.restore();

      for (let row = 0; row < rows; row += 1) {
        for (let column = 0; column < columns; column += 1) {
          const x = column * cellSize;
          const y = row * cellSize;
          const nx = x / Math.max(width, 1);
          const ny = y / Math.max(height, 1);
          const pixel = (row * columns + column) * 4;
          const luminance = (sourcePixels[pixel] * 0.2126 + sourcePixels[pixel + 1] * 0.7152 + sourcePixels[pixel + 2] * 0.0722) / 255;
          const contrast = clamp((luminance - 0.5) * 1.5 + 0.5);
          const alpha = Math.pow(contrast, 2.5) * 0.52;

          if (alpha < 0.055) continue;

          context.save();
          context.translate(x + cellSize / 2, y + cellSize / 2);
          context.rotate(((Math.sin(nx * 11 + ny * 7 + time * 0.5) + 1) / 2 - 0.5) * 0.48);
          context.strokeStyle = `rgba(230, 234, 229, ${alpha})`;
          context.lineWidth = contrast > 0.75 ? 0.95 : 0.65;
          const reach = 2 + contrast * 3.2;
          context.beginPath();
          context.moveTo(-reach, -reach);
          context.lineTo(reach, reach);
          context.stroke();
          if (contrast > 0.46) {
            context.globalAlpha = 0.65;
            context.beginPath();
            context.moveTo(-reach, reach);
            context.lineTo(reach, -reach);
            context.stroke();
          }
          context.restore();
        }
      }

      context.save();
      context.globalAlpha = 0.18;
      context.fillStyle = '#dbe7dc';
      for (let y = 4; y < height; y += 9) {
        for (let x = 4; x < width; x += 9) {
          const strength = smoothNoise(x / width * 3.4, y / height * 3.4, time);
          if (strength > 0.64) context.fillRect(x, y, 1, 1);
        }
      }
      context.restore();

      const vignette = context.createRadialGradient(width * 0.5, height * 0.5, Math.min(width, height) * 0.1, width * 0.5, height * 0.5, Math.max(width, height) * 0.76);
      vignette.addColorStop(0, 'rgba(10, 10, 10, 0)');
      vignette.addColorStop(1, 'rgba(10, 10, 10, 0.78)');
      context.fillStyle = vignette;
      context.fillRect(0, 0, width, height);

      if (!reduceMotion) animationFrame = window.requestAnimationFrame(draw);
    };

    resize();
    const observer = new ResizeObserver(resize);
    observer.observe(canvas);
    animationFrame = window.requestAnimationFrame(draw);

    return () => {
      observer.disconnect();
      window.cancelAnimationFrame(animationFrame);
    };
  }, []);

  return <canvas ref={canvasRef} className={className} aria-hidden="true" />;
}
