"use client";

import { useMemo, useRef, useState } from "react";
import { MapPin, RotateCcw, ZoomIn, ZoomOut } from "lucide-react";

export type SchoolMapItem = {
  school: string;
  faction: string;
  is985: boolean;
  zone: string;
  unit: string | null;
  location: string | null;
  latitude: number | null;
  longitude: number | null;
  locationMatchedName: string | null;
  locationPrecision: string | null;
  locationSource: string | null;
  locationSourceUrl: string | null;
  locationReviewStatus: string | null;
  officeHub: string | null;
  officeHubLatitude: number | null;
  officeHubLongitude: number | null;
  officeHubDefinition: string | null;
  officeHubReviewStatus: string | null;
  transitMode: string | null;
  transitLines: string | null;
  transitSummary: string | null;
  transitReviewStatus: string | null;
  liveRouteUrl: string | null;
  routeSource: string | null;
  q50: number;
  q90: number;
  confidence: string;
  probability: number;
};

const WIDTH = 1000;
const HEIGHT = 620;
const MIN_LNG = 73;
const MAX_LNG = 135;
const MIN_LAT = 18;
const MAX_LAT = 54;

const factionColors: Record<string, string> = {
  "纯贾": "#7dd3fc",
  "纯茆": "#86efac",
  "贾茆": "#fde68a",
  "茆Pro": "#c4b5fd",
  "贾茆Pro": "#fdba74",
  "待核实": "#94a3b8",
};

const regionLabels = [
  { label: "西北", lng: 88, lat: 42 },
  { label: "华北", lng: 114, lat: 42 },
  { label: "东北", lng: 126, lat: 47 },
  { label: "西南", lng: 101, lat: 29 },
  { label: "华中", lng: 113, lat: 31 },
  { label: "华东", lng: 121, lat: 31 },
  { label: "华南", lng: 113, lat: 23 },
];

function project(longitude: number, latitude: number) {
  return {
    x: 56 + ((longitude - MIN_LNG) / (MAX_LNG - MIN_LNG)) * (WIDTH - 112),
    y: 44 + ((MAX_LAT - latitude) / (MAX_LAT - MIN_LAT)) * (HEIGHT - 88),
  };
}

function precisionLabel(value: string | null) {
  if (value === "campus") return "校区级";
  if (value === "campus_entrance") return "校门级";
  if (value === "campus_area") return "校区片区级";
  return "精度待核实";
}

function factionTone(value: string) {
  return {
    "纯贾": "pure-jia",
    "纯茆": "pure-mao",
    "贾茆": "jia-mao",
    "茆Pro": "mao-pro",
    "贾茆Pro": "jia-mao-pro",
  }[value] ?? "pending";
}

export function SchoolCoordinateMap({
  items,
  selectedSchool,
  onSelect,
}: {
  items: SchoolMapItem[];
  selectedSchool: string;
  onSelect: (school: string) => void;
}) {
  const [hoveredSchool, setHoveredSchool] = useState<string | null>(null);
  const [view, setView] = useState({ zoom: 1, x: 0, y: 0 });
  const drag = useRef<{ x: number; y: number; startX: number; startY: number } | null>(null);

  const plotted = useMemo(
    () => items.filter((item) => item.latitude !== null && item.longitude !== null),
    [items],
  );
  const officeHubs = useMemo(() => {
    const unique = new Map<string, { name: string; latitude: number; longitude: number }>();
    for (const item of plotted) {
      if (item.officeHub && item.officeHubLatitude !== null && item.officeHubLongitude !== null) {
        unique.set(item.officeHub, { name: item.officeHub, latitude: item.officeHubLatitude, longitude: item.officeHubLongitude });
      }
    }
    return [...unique.values()];
  }, [plotted]);
  const active =
    plotted.find((item) => item.school === hoveredSchool)
    ?? plotted.find((item) => item.school === selectedSchool)
    ?? plotted[0];

  const clampView = (zoom: number, x: number, y: number) => ({
    zoom,
    x: Math.min(0, Math.max(WIDTH - WIDTH * zoom, x)),
    y: Math.min(0, Math.max(HEIGHT - HEIGHT * zoom, y)),
  });

  const changeZoom = (nextZoom: number, focusX = WIDTH / 2, focusY = HEIGHT / 2) => {
    setView((current) => {
      const zoom = Math.min(5, Math.max(1, nextZoom));
      const ratio = zoom / current.zoom;
      return clampView(
        zoom,
        focusX - (focusX - current.x) * ratio,
        focusY - (focusY - current.y) * ratio,
      );
    });
  };

  return (
    <div className="coordinate-map-layout">
      <div className="coordinate-map-card">
        <div className="map-toolbar">
          <div>
            <span className="eyebrow">CAMPUS COORDINATES</span>
            <strong>院校经纬度分布图</strong>
            <small>拖拽平移，滚轮或按钮缩放；点位按培养单位所在校区</small>
          </div>
          <div className="map-buttons" aria-label="地图缩放控件">
            <button type="button" onClick={() => changeZoom(view.zoom + 0.45)} aria-label="放大地图"><ZoomIn size={16} /></button>
            <button type="button" onClick={() => changeZoom(view.zoom - 0.45)} aria-label="缩小地图"><ZoomOut size={16} /></button>
            <button type="button" onClick={() => setView({ zoom: 1, x: 0, y: 0 })} aria-label="重置地图"><RotateCcw size={15} /></button>
          </div>
        </div>

        <div className="coordinate-map-stage">
          <svg
            viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
            role="img"
            aria-label={`可交互院校坐标图，当前显示 ${plotted.length} 所学校`}
            onWheel={(event) => {
              event.preventDefault();
              const box = event.currentTarget.getBoundingClientRect();
              const x = ((event.clientX - box.left) / box.width) * WIDTH;
              const y = ((event.clientY - box.top) / box.height) * HEIGHT;
              changeZoom(view.zoom + (event.deltaY < 0 ? 0.35 : -0.35), x, y);
            }}
            onPointerDown={(event) => {
              event.currentTarget.setPointerCapture(event.pointerId);
              drag.current = { x: event.clientX, y: event.clientY, startX: view.x, startY: view.y };
            }}
            onPointerMove={(event) => {
              if (!drag.current) return;
              const box = event.currentTarget.getBoundingClientRect();
              const dx = ((event.clientX - drag.current.x) / box.width) * WIDTH;
              const dy = ((event.clientY - drag.current.y) / box.height) * HEIGHT;
              setView((current) => clampView(current.zoom, drag.current!.startX + dx, drag.current!.startY + dy));
            }}
            onPointerUp={() => { drag.current = null; }}
            onPointerCancel={() => { drag.current = null; }}
          >
            <defs>
              <radialGradient id="mapGlow" cx="55%" cy="45%" r="70%">
                <stop offset="0" stopColor="#12324a" stopOpacity="0.86" />
                <stop offset="1" stopColor="#071321" stopOpacity="0.96" />
              </radialGradient>
              <filter id="markerGlow" x="-120%" y="-120%" width="340%" height="340%">
                <feGaussianBlur stdDeviation="3" result="blur" />
                <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
              </filter>
            </defs>
            <rect width={WIDTH} height={HEIGHT} rx="18" fill="url(#mapGlow)" />
            <g transform={`translate(${view.x} ${view.y}) scale(${view.zoom})`}>
              {[80, 90, 100, 110, 120, 130].map((lng) => {
                const point = project(lng, MIN_LAT);
                return <g key={`lng-${lng}`}><line x1={point.x} x2={point.x} y1={34} y2={HEIGHT - 34} className="map-grid-line" /><text x={point.x + 5} y={HEIGHT - 42} className="map-grid-label">{lng}°E</text></g>;
              })}
              {[20, 25, 30, 35, 40, 45, 50].map((lat) => {
                const point = project(MIN_LNG, lat);
                return <g key={`lat-${lat}`}><line x1={44} x2={WIDTH - 44} y1={point.y} y2={point.y} className="map-grid-line" /><text x={50} y={point.y - 6} className="map-grid-label">{lat}°N</text></g>;
              })}
              {regionLabels.map((region) => {
                const point = project(region.lng, region.lat);
                return <text key={region.label} x={point.x} y={point.y} className="map-region-label">{region.label}</text>;
              })}
              {plotted.map((item) => {
                if (item.officeHubLatitude === null || item.officeHubLongitude === null) return null;
                const schoolPoint = project(item.longitude!, item.latitude!);
                const hubPoint = project(item.officeHubLongitude, item.officeHubLatitude);
                const activeLine = item.school === selectedSchool || item.school === hoveredSchool;
                return <line key={`commute-${item.school}`} x1={schoolPoint.x} y1={schoolPoint.y} x2={hubPoint.x} y2={hubPoint.y} className={activeLine ? "commute-line active" : "commute-line"} strokeWidth={(activeLine ? 2.4 : 0.8) / view.zoom} />;
              })}
              {officeHubs.map((hub) => {
                const point = project(hub.longitude, hub.latitude);
                const activeHub = active?.officeHub === hub.name;
                return (
                  <g key={hub.name} transform={`translate(${point.x} ${point.y})`} className="office-hub-marker">
                    <rect x={-5 / view.zoom} y={-5 / view.zoom} width={10 / view.zoom} height={10 / view.zoom} rx={1 / view.zoom} transform="rotate(45)" />
                    {activeHub ? <text x={10 / view.zoom} y={-9 / view.zoom} style={{ fontSize: `${11 / view.zoom}px` }}>{hub.name}</text> : null}
                  </g>
                );
              })}
              {plotted.map((item) => {
                const point = project(item.longitude!, item.latitude!);
                const selected = item.school === selectedSchool;
                const hovered = item.school === hoveredSchool;
                const radius = (selected || hovered ? 8 : 5.2) / view.zoom;
                return (
                  <g
                    key={item.school}
                    transform={`translate(${point.x} ${point.y})`}
                    className="school-map-marker"
                    role="button"
                    tabIndex={0}
                    aria-label={`${item.school}，${item.faction}，90%稳妥线${Math.round(item.q90)}分`}
                    onPointerDown={(event) => event.stopPropagation()}
                    onMouseEnter={() => setHoveredSchool(item.school)}
                    onMouseLeave={() => setHoveredSchool(null)}
                    onClick={() => onSelect(item.school)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" || event.key === " ") onSelect(item.school);
                    }}
                  >
                    <circle r={15 / view.zoom} fill="transparent" />
                    {(selected || hovered) && <circle r={12 / view.zoom} fill="none" stroke={factionColors[item.faction] ?? factionColors["待核实"]} strokeOpacity="0.34" strokeWidth={2 / view.zoom} />}
                    <circle
                      r={radius}
                      fill={factionColors[item.faction] ?? factionColors["待核实"]}
                      stroke="#071321"
                      strokeWidth={2 / view.zoom}
                      filter={selected || hovered ? "url(#markerGlow)" : undefined}
                    />
                  </g>
                );
              })}
            </g>
          </svg>
          <div className="map-scale">{view.zoom.toFixed(1)}×</div>
        </div>

        <div className="map-legend">
          {Object.entries(factionColors).map(([label, color]) => <span key={label}><i style={{ background: color }} />{label}</span>)}
          <span><i className="office-hub-symbol" />办公集聚区</span>
          <small>底图仅为经纬度坐标网，不绘制行政区划或国界。</small>
        </div>
      </div>

      <aside className="map-school-card">
        {active ? (
          <>
            <div className="map-school-title"><MapPin size={19} /><div><span className="eyebrow">{hoveredSchool ? "HOVER" : "SELECTED"}</span><h2>{active.school}</h2></div></div>
            <div className="map-school-tags"><span className={`faction-badge ${factionTone(active.faction)}`}>{active.faction}</span><span>{active.is985 ? "985" : "211"}</span><span>{active.zone}区</span></div>
            <p className="map-school-location">{active.locationMatchedName ?? active.location ?? "校区位置待核实"}</p>
            <dl className="map-school-metrics">
              <div><dt>经纬度</dt><dd>{active.latitude?.toFixed(5)}, {active.longitude?.toFixed(5)}</dd></div>
              <div><dt>定位精度</dt><dd>{precisionLabel(active.locationPrecision)}</dd></div>
              <div><dt>预测中位数</dt><dd>{Math.round(active.q50)} 分</dd></div>
              <div><dt>90% 稳妥线</dt><dd>{Math.round(active.q90)} 分</dd></div>
              <div><dt>当前把握</dt><dd>{Math.round(active.probability * 100)}%</dd></div>
              <div><dt>数据可信度</dt><dd>{active.confidence}</dd></div>
            </dl>
            <div className="map-source-note">
              <strong>坐标状态</strong>
              <p>{active.locationReviewStatus ?? "待人工复核"}</p>
              {active.locationSourceUrl ? <a href={active.locationSourceUrl} target="_blank" rel="noreferrer">查看坐标来源</a> : null}
            </div>
            <div className="commute-card">
              <span className="eyebrow">OFFICE COMMUTE</span>
              <h3>{active.officeHub ?? "办公集聚区待核实"}</h3>
              <p>{active.officeHubDefinition}</p>
              <dl>
                <div><dt>优先方式</dt><dd>{active.transitMode ?? "待核实"}</dd></div>
                <div><dt>候选线路</dt><dd>{active.transitLines ?? "待核实"}</dd></div>
              </dl>
              <p>{active.transitSummary}</p>
              <small>{active.transitReviewStatus}</small>
              {active.liveRouteUrl ? <a href={active.liveRouteUrl} target="_blank" rel="noreferrer">用高德查看实时公交方案</a> : null}
            </div>
            <p className="map-card-footnote">多培养单位或多校区院校暂展示原表首列主要培养校区。最终报名前请以当年招生简章公布地点为准。</p>
          </>
        ) : <div className="empty-state">当前筛选没有可显示的院校</div>}
      </aside>
    </div>
  );
}
