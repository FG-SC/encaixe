import { type ReactNode, useEffect, useRef } from "react";
import { attachSwipe, type Direction } from "../lib/swipe";

/** A card you can swipe (pointer), or judge with ←/→ and the two buttons. */
export function SwipeCard({ children, onSwipe, label }: {
  children: ReactNode;
  onSwipe: (d: Direction) => void;
  label: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const cb = useRef(onSwipe);
  cb.current = onSwipe;
  useEffect(() => {
    if (!ref.current) return;
    return attachSwipe(ref.current, (d) => cb.current(d));
  }, []);
  return (
    <div
      ref={ref}
      className="card"
      tabIndex={0}
      aria-label={label}
      onKeyDown={(e) => {
        if (e.key === "ArrowRight") onSwipe("right");
        if (e.key === "ArrowLeft") onSwipe("left");
      }}
    >
      {children}
      <div className="actions">
        <button type="button" className="swipe-btn no" aria-label="Não tenho interesse (seta para a esquerda)"
          onClick={() => onSwipe("left")}>✕</button>
        <button type="button" className="swipe-btn yes" aria-label="Tenho interesse (seta para a direita)"
          onClick={() => onSwipe("right")}>✓</button>
      </div>
    </div>
  );
}
