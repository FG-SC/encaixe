import * as Plot from "@observablehq/plot";
import { useEffect, useRef } from "react";

/** Observable Plot rendered imperatively into a ref (removed on cleanup). */
export function PlotChart({ options, label }: { options: Plot.PlotOptions; label: string }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!ref.current) return;
    const el = Plot.plot({ style: { fontFamily: "Inter, sans-serif", background: "transparent" }, ...options });
    el.setAttribute("role", "img");
    el.setAttribute("aria-label", label);
    ref.current.replaceChildren(el);
    return () => el.remove();
  }, [options, label]);
  return <div className="plot" ref={ref} />;
}
