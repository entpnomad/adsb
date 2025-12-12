#!/usr/bin/env python3
"""
Generate a portal page that uses the published API (no direct DB access).

The page is written to output/index.html and served at / by FastAPI or serve_map.py.
"""

from __future__ import annotations

from pathlib import Path

try:
    from . import _bootstrap  # noqa: F401
except ImportError:  # pragma: no cover
    import _bootstrap  # type: ignore  # noqa: F401

from adsb.config import OUTPUT_DIR


def build_link(label: str, href: str, hint: str = "") -> str:
    return (
        '<div class="card">'
        f'<div class="card-title">{label}</div>'
        '<div class="badge" style="background:#10b981;">ready</div>'
        f'<a class="link" href="{href}" target="_blank" rel="noreferrer">Open</a>'
        f'<div class="hint">{hint}</div>'
        "</div>"
    )


def main() -> None:
    OUTPUT_DIR.mkdir(exist_ok=True, parents=True)

    sections = []
    sections.append(
        """
    <section>
      <h2>Maps / API</h2>
      <div class="grid">
        {map_link}
        {docs_link}
      </div>
    </section>
    """.format(
            map_link=build_link("Live map (API)", "/map", "Served by FastAPI /map"),
            docs_link=build_link("API docs", "/docs", "OpenAPI UI"),
        )
    )

    sections.append(
        """
    <section>
      <h2>Database (via API)</h2>
      <div id="stats-grid" class="grid stats-grid"></div>
      <div class="muted" id="stats-hint">Loading stats from /api/stats/overview...</div>
    </section>
    """
    )

    sections.append(
        """
    <section>
      <h2>Current traffic (API)</h2>
      <div class="muted" id="current-meta">Loading /api/aircraft/current...</div>
      <div class="table-wrapper">
        <table class="table">
          <thead>
            <tr>
              <th>ICAO</th><th>Flight</th><th>Lat</th><th>Lon</th><th>Alt (ft)</th><th>Speed (kts)</th><th>Heading</th><th>Timestamp</th>
            </tr>
          </thead>
          <tbody id="current-table-body"></tbody>
        </table>
      </div>
    </section>
    """
    )

    sections.append(
        """
    <section>
      <h2>Recent aircraft in DB (API)</h2>
      <div class="muted" id="recent-meta">Loading /api/aircraft/recent...</div>
      <div class="table-wrapper">
        <table class="table">
          <thead>
            <tr>
              <th>ICAO</th><th>Flight</th><th>Last seen</th><th>First seen</th><th>Positions</th><th>Last lat/lon</th><th>Last alt (ft)</th><th>Actions</th>
            </tr>
          </thead>
          <tbody id="recent-table-body"></tbody>
        </table>
      </div>
    </section>
    """
    )

    sections_html = "".join(sections)
    html = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>ADS-B Portal</title>
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <style>
    body {
      font-family: "Segoe UI", -apple-system, sans-serif;
      background: linear-gradient(120deg, #0f172a, #111827);
      color: #e5e7eb;
      margin: 0;
      padding: 24px;
    }
    .container {
      max-width: 960px;
      margin: 0 auto;
    }
    h1 { margin-bottom: 8px; font-weight: 700; }
    h2 { margin-top: 24px; margin-bottom: 12px; }
    .muted { color: #9ca3af; font-size: 14px; }
    .grid {
      display: grid;
      gap: 12px;
      grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
    }
    .stats-grid {
      grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
    }
    .card {
      background: rgba(255,255,255,0.04);
      border: 1px solid rgba(255,255,255,0.06);
      border-radius: 10px;
      padding: 14px;
      display: flex;
      flex-direction: column;
      gap: 8px;
    }
    .card-title { font-size: 16px; font-weight: 600; }
    .badge {
      display: inline-block;
      padding: 4px 10px;
      border-radius: 12px;
      font-size: 12px;
      color: #0b1224;
      font-weight: 600;
      align-self: flex-start;
    }
    .link {
      color: #60a5fa;
      text-decoration: none;
      font-weight: 600;
    }
    .hint { color: #9ca3af; font-size: 13px; }
    .table-wrapper {
      overflow-x: auto;
      background: rgba(255,255,255,0.02);
      border: 1px solid rgba(255,255,255,0.06);
      border-radius: 10px;
      padding: 8px;
    }
    .table {
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
    }
    .table th {
      text-align: left;
      padding: 6px 8px;
      color: #9ca3af;
      border-bottom: 1px solid rgba(255,255,255,0.06);
    }
    .table td {
      padding: 6px 8px;
      border-bottom: 1px solid rgba(255,255,255,0.04);
      color: #e5e7eb;
      white-space: nowrap;
    }
    .chip {
      display: inline-block;
      padding: 4px 8px;
      border-radius: 8px;
      background: #2563eb;
      color: #fff;
      text-decoration: none;
      font-weight: 600;
      font-size: 12px;
      margin-right: 6px;
    }
    .chip.secondary {
      background: #111827;
      border: 1px solid rgba(255,255,255,0.2);
      color: #e5e7eb;
    }
    .chip.disabled {
      opacity: 0.4;
      cursor: not-allowed;
    }
    .stat-card {
      background: rgba(255,255,255,0.04);
      border: 1px solid rgba(255,255,255,0.08);
      border-left: 4px solid #2563eb;
      border-radius: 10px;
      padding: 12px 14px;
      display: flex;
      flex-direction: column;
      gap: 6px;
    }
    .stat-label {
      font-size: 12px;
      color: #9ca3af;
      text-transform: uppercase;
      letter-spacing: 0.5px;
    }
    .stat-value {
      font-size: 22px;
      font-weight: 700;
      color: #e5e7eb;
    }
    .stat-hint {
      color: #9ca3af;
      font-size: 12px;
    }
  </style>
  <script>
    const fmt = (v) => (v === null || v === undefined || v === '' ? 'n/a' : v);
    const fmtNum = (v) => {
      if (v === null || v === undefined) return 'n/a';
      const n = Number(v);
      return Number.isNaN(n) ? 'n/a' : n.toLocaleString();
    };

    function renderStats(data) {
      const grid = document.getElementById('stats-grid');
      const hint = document.getElementById('stats-hint');
      if (!grid) return;
      grid.innerHTML = [
        '<div class="stat-card" style="border-color:#10b981;">' +
          '<div class="stat-label">Status</div>' +
          '<div class="stat-value">' + fmt(data.status) + '</div>' +
          '<div class="stat-hint">/api/stats/overview</div>' +
        '</div>',
        '<div class="stat-card">' +
          '<div class="stat-label">Aircraft rows</div>' +
          '<div class="stat-value">' + fmtNum(data.aircraft_count) + '</div>' +
          '<div class="stat-hint">aircraft</div>' +
        '</div>',
        '<div class="stat-card">' +
          '<div class="stat-label">Position rows</div>' +
          '<div class="stat-value">' + fmtNum(data.position_count) + '</div>' +
          '<div class="stat-hint">positions</div>' +
        '</div>',
        '<div class="stat-card">' +
          '<div class="stat-label">Latest position</div>' +
          '<div class="stat-value">' + fmt(data.latest_ts) + '</div>' +
          '<div class="stat-hint">MAX(ts)</div>' +
        '</div>',
        '<div class="stat-card">' +
          '<div class="stat-label">Last hour</div>' +
          '<div class="stat-value">' + fmtNum(data.last_hour) + '</div>' +
          '<div class="stat-hint">positions</div>' +
        '</div>',
        '<div class="stat-card">' +
          '<div class="stat-label">Last 24h</div>' +
          '<div class="stat-value">' + fmtNum(data.last_day) + '</div>' +
          '<div class="stat-hint">positions</div>' +
        '</div>',
        '<div class="stat-card">' +
          '<div class="stat-label">Ingest requests (1h)</div>' +
          '<div class="stat-value">' + fmtNum(data.ingests_last_hour) + '</div>' +
          '<div class="stat-hint">/api/ingest calls</div>' +
        '</div>'
      ].join('');
      if (hint) hint.textContent = 'Stats loaded from /api/stats/overview';
    }

    async function loadStats() {
      try {
        const resp = await fetch('/api/stats/overview');
        if (!resp.ok) throw new Error(resp.status);
        const data = await resp.json();
        renderStats(data);
      } catch (err) {
        const hint = document.getElementById('stats-hint');
        if (hint) hint.textContent = 'Unable to load stats: ' + err;
      }
    }

    function renderCurrent(rows) {
      const tbody = document.getElementById('current-table-body');
      const meta = document.getElementById('current-meta');
      if (!tbody) return;
      tbody.innerHTML = '';
      rows.forEach((row) => {
        const tr = document.createElement('tr');
        const cols = [
          row.icao,
          row.flight || '',
          row.lat,
          row.lon,
          row.altitude_ft,
          row.speed_kts,
          row.heading_deg,
          row.timestamp_utc || row.ts || '',
        ];
        cols.forEach((c) => {
          const td = document.createElement('td');
          td.textContent = fmt(c);
          tr.appendChild(td);
        });
        tbody.appendChild(tr);
      });
      if (meta) meta.textContent = 'Showing ' + rows.length + ' rows from /api/aircraft/current';
    }

    async function loadCurrent() {
      try {
        const resp = await fetch('/api/aircraft/current?since_seconds=300');
        if (!resp.ok) throw new Error(resp.status);
        const data = await resp.json();
        renderCurrent(data);
      } catch (err) {
        const meta = document.getElementById('current-meta');
        if (meta) meta.textContent = 'Unable to load current traffic: ' + err;
      }
    }

    function renderRecent(rows) {
      const tbody = document.getElementById('recent-table-body');
      const meta = document.getElementById('recent-meta');
      if (!tbody) return;
      tbody.innerHTML = '';
      const buildLinks = (row) => {
        if (!row.icao) return '';
        const icao = (row.icao || '').toUpperCase();
        const mapLink = `/map?route_icao=${encodeURIComponent(icao)}`;
        const adsbx = `https://globe.adsbexchange.com/?icao=${icao.toLowerCase()}`;
        const registration = (row.registration || '').toLowerCase();
        const flight = (row.flight || '').toLowerCase();
        let fr24Link = '';
        if (registration) {
          fr24Link = `https://www.flightradar24.com/data/aircraft/${encodeURIComponent(registration)}`;
        } else if (flight) {
          fr24Link = `https://www.flightradar24.com/${encodeURIComponent(flight)}`;
        }
        const chips = [
          `<a class="chip" href="${mapLink}" target="_blank" rel="noreferrer noopener">Ver ruta</a>`,
          `<a class="chip secondary" href="${adsbx}" target="_blank" rel="noreferrer noopener">ADSBx</a>`,
        ];
        if (fr24Link) {
          chips.push(`<a class="chip secondary" href="${fr24Link}" target="_blank" rel="noreferrer noopener">FR24</a>`);
        } else {
          chips.push('<span class="chip secondary disabled">FR24 n/a</span>');
        }
        return chips.join(' ');
      };
      rows.forEach((row) => {
        const tr = document.createElement('tr');
        const coords = row.last_lat && row.last_lon ? (row.last_lat + ', ' + row.last_lon) : 'n/a';
        const cols = [
          row.icao,
          row.flight || '',
          row.last_seen_utc || row.last_seen || '',
          row.first_seen_utc || row.first_seen || '',
          fmtNum(row.position_count),
          coords,
          row.last_altitude_ft ?? 'n/a',
        ];
        cols.forEach((c) => {
          const td = document.createElement('td');
          td.textContent = fmt(c);
          tr.appendChild(td);
        });
        const actionTd = document.createElement('td');
        actionTd.innerHTML = buildLinks(row);
        tr.appendChild(actionTd);
        tbody.appendChild(tr);
      });
      if (meta) meta.textContent = 'Most recent ' + rows.length + ' aircraft from /api/aircraft/recent';
    }

    async function loadRecent() {
      try {
        const resp = await fetch('/api/aircraft/recent?limit=15');
        if (!resp.ok) throw new Error(resp.status);
        const data = await resp.json();
        renderRecent(data);
      } catch (err) {
        const meta = document.getElementById('recent-meta');
        if (meta) meta.textContent = 'Unable to load recent aircraft: ' + err;
      }
    }

    function refreshAll() {
      loadStats();
      loadCurrent();
      loadRecent();
    }

    window.addEventListener('load', () => {
      refreshAll();
      setInterval(loadCurrent, 5000);
      setInterval(loadStats, 10000);
      setInterval(loadRecent, 15000);
    });
  </script>
</head>
<body>
  <div class="container">
    <h1>ADS-B Portal</h1>
    <div class="muted">All data below is retrieved through the published API.</div>
    {SECTIONS}
  </div>
</body>
</html>
"""

    html = html.replace("{SECTIONS}", sections_html)
    portal_path = OUTPUT_DIR / "index.html"
    portal_path.write_text(html, encoding="utf-8")
    print(f"Portal generated at {portal_path}")


if __name__ == "__main__":
    main()
