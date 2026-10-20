import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { useEffect, useRef } from "react";

export interface GeoPoint {
  lat: number;
  lon: number;
  label: string;
  value: number; // drives the radius
  color?: string;
}

// OSM tile policy: correct URL (no subdomains), visible attribution linked to /copyright, a Referer
// (strict-origin-when-cross-origin), no prefetch. Offline: points without a background.
const TILES = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
const ATTRIBUTION = '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';

export function GeoMap({ points, label, center = [-27.6, -48.6], zoom = 6 }: {
  points: GeoPoint[];
  label: string;
  center?: [number, number];
  zoom?: number;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!ref.current) return;
    const map = L.map(ref.current, { center, zoom, scrollWheelZoom: false, attributionControl: true });
    const tiles = L.tileLayer(TILES, {
      attribution: ATTRIBUTION, maxZoom: 18, referrerPolicy: "strict-origin-when-cross-origin",
    } as L.TileLayerOptions);
    let failed = 0;
    tiles.on("tileerror", () => {
      failed += 1;
      if (failed > 4) map.removeLayer(tiles); // offline: keep the points, drop the background
    });
    if (navigator.onLine) tiles.addTo(map);
    const max = Math.max(1, ...points.map((p) => p.value));
    for (const p of points) {
      L.circleMarker([p.lat, p.lon], {
        radius: 4 + 14 * Math.sqrt(p.value / max), color: p.color ?? "#0E7C66", weight: 1, fillOpacity: 0.55,
      }).bindTooltip(p.label).addTo(map);
    }
    return () => { map.remove(); };
  }, [points, center[0], center[1], zoom]); // eslint-disable-line react-hooks/exhaustive-deps
  return <div className="map" ref={ref} role="region" aria-label={label} />;
}
