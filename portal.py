#!/usr/bin/env python3
"""
Generate a simple portal page with links to maps and data files.

The page is written to output/index.html and served by serve_map.py.
"""

from __future__ import annotations

import os
import csv
from datetime import datetime
from pathlib import Path
from typing import List, Tuple

from src.lib.config import (
    DEFAULT_CURRENT_MAP_HTML,
    DEFAULT_MAP_HTML,
    OUTPUT_DIR,
    get_current_csv_path,
    get_history_csv_path,
)


def file_info(path: Path) -> Tuple[bool, str, str]:
    if path.exists():
        mtime = datetime.fromtimestamp(path.stat().st_mtime).isoformat(sep=" ", timespec="seconds")
        size_kb = f"{path.stat().st_size / 1024:.1f} KB"
        return True, mtime, size_kb
    return False, "n/a", "0 KB"


def build_link(label: str, href: str, exists: bool, hint: str = "") -> str:
    state = "online" if exists else "no generado"
    color = "#10b981" if exists else "#f59e0b"
    action = f'<a class="link" href="{href}" target="_blank" rel="noreferrer">Abrir</a>' if exists else f'<div class="hint">{hint or "Genera el mapa para habilitar el enlace"}</div>'
    return f"""
    <div class="card">
      <div class="card-title">{label}</div>
      <div class="badge" style="background:{color};">{state}</div>
      {action}
    </div>
    """


def build_file(label: str, path: Path) -> str:
    exists, mtime, size = file_info(path)
    return f"""
    <div class="file-row">
      <div class="file-name">{label}</div>
      <div class="file-meta">{'disponible' if exists else 'no encontrado'} · {mtime} · {size}</div>
    </div>
    """


def load_current_rows(path: Path, limit: int = 20) -> List[dict]:
    if not path.exists():
        return []
    rows: List[dict] = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append(row)
                if len(rows) >= limit:
                    break
    except Exception:
        return []
    return rows


def build_table(rows: List[dict]) -> str:
    if not rows:
        return '<div class="muted">Sin datos actuales.</div>'

    headers = ["icao", "flight", "altitude_ft", "speed_kts", "heading_deg", "lat", "lon", "timestamp_utc"]
    header_html = "".join(f"<th>{h}</th>" for h in headers)
    body_html = ""
    for row in rows:
        body_html += "<tr>" + "".join(f"<td>{row.get(h, '')}</td>" for h in headers) + "</tr>"
    return f"""
    <div class="table-wrapper">
      <table class="table">
        <thead><tr>{header_html}</tr></thead>
        <tbody>{body_html}</tbody>
      </table>
    </div>
    """


def db_stats() -> Tuple[str, str]:
    db_url = os.getenv("ADSB_DB_URL")
    if not db_url:
        return ("demo (sin URL)", "#f59e0b")
    try:
        import psycopg2  # type: ignore

        with psycopg2.connect(db_url) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM positions;")
                count = cur.fetchone()[0]
                cur.execute("SELECT MAX(ts) FROM positions;")
                latest = cur.fetchone()[0]
                latest_txt = latest.isoformat() if latest else "n/a"
                return (f"configurado · {count} posiciones · última {latest_txt}", "#10b981")
    except Exception:
        return ("no accesible", "#ef4444")


def main() -> None:
    OUTPUT_DIR.mkdir(exist_ok=True, parents=True)
    current_map = Path(DEFAULT_CURRENT_MAP_HTML)
    historical_map = Path(DEFAULT_MAP_HTML)
    current_csv = get_current_csv_path()
    history_csv = get_history_csv_path()

    sections: List[str] = []
    # Maps
    sections.append(f"""
    <section>
      <h2>Mapas</h2>
      <div class="grid">
        {build_link("Mapa actual (auto)", current_map.name, current_map.exists())}
        {build_link("Mapa histórico", historical_map.name, historical_map.exists())}
      </div>
    </section>
    """)

    # Data files
    sections.append(f"""
    <section>
      <h2>Datos</h2>
      {build_file("CSV actual", current_csv)}
      {build_file("CSV histórico", history_csv)}
    </section>
    """)

    # Current traffic table
    rows = load_current_rows(current_csv, limit=20)
    sections.append(f"""
    <section>
      <h2>Tráfico actual (CSV)</h2>
      <div class="muted">Muestra los primeros {min(20, len(rows)) if rows else 0} registros de {current_csv.name}.</div>
      {build_table(rows)}
    </section>
    """)

    # DB status (optional for demo)
    db_status, db_color = db_stats()
    sections.append(f"""
    <section>
      <h2>Base de datos</h2>
      <div class="file-row">
        <div class="file-name">ADSB_DB_URL</div>
        <div class="file-meta" style="color:{db_color};">{db_status}</div>
      </div>
    </section>
    """)

    html = f"""
<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8" />
  <title>ADS-B Portal</title>
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <style>
    body {{
      font-family: "Segoe UI", -apple-system, sans-serif;
      background: linear-gradient(120deg, #0f172a, #111827);
      color: #e5e7eb;
      margin: 0;
      padding: 24px;
    }}
    .container {{
      max-width: 960px;
      margin: 0 auto;
    }}
    h1 {{ margin-bottom: 8px; font-weight: 700; }}
    h2 {{ margin-top: 24px; margin-bottom: 12px; }}
    .muted {{ color: #9ca3af; font-size: 14px; }}
    .grid {{
      display: grid;
      gap: 12px;
      grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
    }}
    .card {{
      background: rgba(255,255,255,0.04);
      border: 1px solid rgba(255,255,255,0.06);
      border-radius: 10px;
      padding: 14px;
      display: flex;
      flex-direction: column;
      gap: 8px;
    }}
    .card-title {{ font-size: 16px; font-weight: 600; }}
    .badge {{
      display: inline-block;
      padding: 4px 10px;
      border-radius: 12px;
      font-size: 12px;
      color: #0b1224;
      font-weight: 600;
      align-self: flex-start;
    }}
    .link {{
      color: #60a5fa;
      text-decoration: none;
      font-weight: 600;
    }}
    .file-row {{
      padding: 10px 12px;
      background: rgba(255,255,255,0.04);
      border: 1px solid rgba(255,255,255,0.06);
      border-radius: 10px;
      margin-bottom: 8px;
      display: flex;
      justify-content: space-between;
      gap: 12px;
      flex-wrap: wrap;
    }}
    .file-name {{ font-weight: 600; }}
    .file-meta {{ color: #9ca3af; font-size: 13px; }}
    .hint {{ color: #9ca3af; font-size: 13px; }}
    .table-wrapper {{
      overflow-x: auto;
      background: rgba(255,255,255,0.02);
      border: 1px solid rgba(255,255,255,0.06);
      border-radius: 10px;
      padding: 8px;
    }}
    .table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
    }}
    .table th {{
      text-align: left;
      padding: 6px 8px;
      color: #9ca3af;
      border-bottom: 1px solid rgba(255,255,255,0.06);
    }}
    .table td {{
      padding: 6px 8px;
      border-bottom: 1px solid rgba(255,255,255,0.04);
      color: #e5e7eb;
      white-space: nowrap;
    }}
  </style>
  <script>
    async function refreshTable() {{
      try {{
        const resp = await fetch('adsb_current.csv?_=' + Date.now());
        if (!resp.ok) return;
        const text = await resp.text();
        const rows = text.trim().split('\\n').slice(1); // skip header
        const tbody = document.getElementById('live-table-body');
        if (!tbody) return;
        tbody.innerHTML = '';
        const maxRows = 20;
        for (let i = 0; i < Math.min(rows.length, maxRows); i++) {{
          const cols = rows[i].split(',');
          const tr = document.createElement('tr');
          const headers = ["timestamp_utc","icao","flight","lat","lon","altitude_ft","speed_kts","heading_deg","squawk"];
          headers.forEach((_, idx) => {{
            const td = document.createElement('td');
            td.textContent = cols[idx] || '';
            tr.appendChild(td);
          }});
          tbody.appendChild(tr);
        }}
        const countEl = document.getElementById('live-count');
        if (countEl) countEl.textContent = 'Mostrando ' + Math.min(rows.length, maxRows) + ' de ' + rows.length + ' registros';
      }} catch (e) {{
        console.log('Refresh failed', e);
      }}
    }}
    setInterval(refreshTable, 5000);
    window.addEventListener('load', refreshTable);
  </script>
</head>
<body>
  <div class="container">
    <h1>ADS-B Portal</h1>
    <div class="muted">Selecciona la vista o comprueba el estado de los datos.</div>
    {''.join(sections)}
  </div>
</body>
</html>
"""

    portal_path = OUTPUT_DIR / "index.html"
    portal_path.write_text(html, encoding="utf-8")
    print(f"Portal generado en {portal_path}")


if __name__ == "__main__":
    main()
