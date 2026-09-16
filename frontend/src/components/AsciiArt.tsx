import React, { useEffect, useState } from 'react';

interface AsciiArtProps {
  className?: string;
  dense?: boolean;
  opacity?: number;
}

export const AsciiArt: React.FC<AsciiArtProps> = ({
  className = "",
  dense = false,
  opacity = 0.15,
}) => {
  const [grid, setGrid] = useState<string[]>([]);

  useEffect(() => {
    const chars = ".:-+*=#%@0123456789ABCDEF/\\_~|";
    const rows = dense ? 24 : 16;
    const cols = dense ? 80 : 64;

    const generateGrid = () => {
      const newRows: string[] = [];
      for (let r = 0; r < rows; r++) {
        let line = "";
        for (let c = 0; c < cols; c++) {
          if (Math.random() < 0.12) {
            line += chars[Math.floor(Math.random() * chars.length)];
          } else {
            line += " ";
          }
        }
        newRows.push(line);
      }
      return newRows;
    };

    setGrid(generateGrid());

    const interval = setInterval(() => {
      setGrid(prev => {
        return prev.map(line => {
          let updated = "";
          for (let i = 0; i < line.length; i++) {
            if (Math.random() < 0.04) {
              updated += chars[Math.floor(Math.random() * chars.length)];
            } else {
              updated += line[i];
            }
          }
          return updated;
        });
      });
    }, 150);

    return () => clearInterval(interval);
  }, [dense]);

  return (
    <pre
      style={{ opacity }}
      className={`font-mono text-[10px] leading-none select-none pointer-events-none text-neutral-400 overflow-hidden whitespace-pre ${className}`}
    >
      {grid.join('\n')}
    </pre>
  );
};
