// Swipe with Pointer Events + requestAnimationFrame (no animation library).
// The pixel threshold is a UI constant, not a ranking rule.

export type Direction = "left" | "right";

export function swipeThreshold(width: number): number {
  return Math.max(80, width * 0.25);
}

export function decide(dx: number, width: number): Direction | null {
  const t = swipeThreshold(width);
  if (dx >= t) return "right";
  if (dx <= -t) return "left";
  return null;
}

export function reducedMotion(): boolean {
  try {
    return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  } catch {
    return false;
  }
}

/** Attach drag handling to an element. Returns a detach function. */
export function attachSwipe(el: HTMLElement, onSwipe: (d: Direction) => void): () => void {
  let startX = 0;
  let dx = 0;
  let dragging = false;
  let frame = 0;
  const paint = () => {
    frame = 0;
    if (reducedMotion()) return;
    el.style.transform = `translateX(${dx}px) rotate(${dx / 25}deg)`;
    el.dataset.intent = dx > 20 ? "right" : dx < -20 ? "left" : "";
  };
  const schedule = () => {
    if (!frame) frame = requestAnimationFrame(paint);
  };
  const down = (e: PointerEvent) => {
    if ((e.target as HTMLElement).closest("button, a, input, select, textarea, [data-no-swipe]")) return;
    dragging = true;
    startX = e.clientX;
    dx = 0;
    el.setPointerCapture(e.pointerId);
  };
  const move = (e: PointerEvent) => {
    if (!dragging) return;
    dx = e.clientX - startX;
    schedule();
  };
  const up = (e: PointerEvent) => {
    if (!dragging) return;
    dragging = false;
    try {
      el.releasePointerCapture(e.pointerId);
    } catch {
      /* ignore */
    }
    const d = decide(dx, el.offsetWidth || 320);
    dx = 0;
    el.style.transform = "";
    el.dataset.intent = "";
    if (d) onSwipe(d);
  };
  el.addEventListener("pointerdown", down);
  el.addEventListener("pointermove", move);
  el.addEventListener("pointerup", up);
  el.addEventListener("pointercancel", up);
  return () => {
    el.removeEventListener("pointerdown", down);
    el.removeEventListener("pointermove", move);
    el.removeEventListener("pointerup", up);
    el.removeEventListener("pointercancel", up);
    if (frame) cancelAnimationFrame(frame);
  };
}
