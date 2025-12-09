#!/usr/bin/env python3
"""
Generate a simple portal page with links to maps and data files.

The page is written to output/index.html and served by serve_map.py.
"""

from __future__ import annotations

import os
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

    # DB status (optional for demo)
    db_url = os.getenv("ADSB_DB_URL")
    if db_url:
        db_status = "configurado"
        db_color = "#10b981"
    else:
        db_status = "demo (sin URL)"
        db_color = "#f59e0b"
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
  </style>
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
