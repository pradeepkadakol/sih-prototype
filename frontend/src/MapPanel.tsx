import { useEffect, useRef } from 'react'
import L from 'leaflet'
import type { Site } from './types'
import { title } from './api'

export default function MapPanel({ sites }: { sites: Site[] }) {
  const container = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!container.current || !sites.length) return
    const map = L.map(container.current, { zoomControl: false, scrollWheelZoom: false }).setView([12.997, 77.594], 11)
    L.control.zoom({ position: 'bottomright' }).addTo(map)
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { attribution: '© OpenStreetMap contributors', maxZoom: 18 }).addTo(map)
    sites.forEach(site => {
      const icon = L.divIcon({ className: `map-pin map-pin-${site.status || 'none'}`, html: '<span></span>', iconSize: [22, 22] })
      L.marker([site.latitude, site.longitude], { icon }).addTo(map).bindPopup(`<strong>${site.name}</strong><br>${site.code} · ${title(site.status || 'none')}`)
    })
    return () => { map.remove() }
  }, [sites])
  return <div className="map-wrap">
    <div className="map-canvas" ref={container} role="img" aria-label="Map of fictional Nila District inspection sites" />
    <div className="map-caption">Site positions are fictional demo coordinates. Tiles need internet access; the location list below remains available offline.</div>
    <div className="site-strip">{sites.map(site => <div key={site.id} className="site-chip"><span className={`status-dot ${site.status}`} /><span><strong>{site.name}</strong><small>{site.region} · {title(site.status || 'none')}</small></span></div>)}</div>
  </div>
}
