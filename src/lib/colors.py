"""
Altitude-based color utilities for ADS-B tracker.

Provides consistent color mapping for aircraft visualization
based on altitude, used in both Python (folium) and JavaScript.
"""

from typing import Optional, Tuple


# Color stops: (altitude_ft, hex_color, folium_color_name)
# These define a smooth gradient from ground level to cruise altitude
ALTITUDE_COLOR_STOPS = [
    (0, "#FF8C00", "orange"),        # 0ft - orange (ground level)
    (4000, "#FFD700", "lightred"),   # 4000ft - gold/yellow
    (8000, "#32CD32", "green"),      # 8000ft - lime green
    (20000, "#00CED1", "lightblue"), # 20000ft - dark turquoise
    (30000, "#1E90FF", "blue"),      # 30000ft - dodger blue
    (40000, "#9932CC", "purple"),    # 40000ft - dark orchid/purple
]


def get_altitude_color(altitude_ft: Optional[int]) -> str:
    """
    Get folium color name based on altitude.

    Uses step interpolation between color stops.

    Args:
        altitude_ft: Altitude in feet, or None for unknown

    Returns:
        Folium color name (e.g., "orange", "green", "blue")
    """
    if altitude_ft is None:
        return "gray"

    # Find the segment
    if altitude_ft <= ALTITUDE_COLOR_STOPS[0][0]:
        return ALTITUDE_COLOR_STOPS[0][2]
    if altitude_ft >= ALTITUDE_COLOR_STOPS[-1][0]:
        return ALTITUDE_COLOR_STOPS[-1][2]

    # Interpolate between stops (using midpoint)
    for i in range(len(ALTITUDE_COLOR_STOPS) - 1):
        if ALTITUDE_COLOR_STOPS[i][0] <= altitude_ft <= ALTITUDE_COLOR_STOPS[i + 1][0]:
            alt1 = ALTITUDE_COLOR_STOPS[i][0]
            alt2 = ALTITUDE_COLOR_STOPS[i + 1][0]
            ratio = (altitude_ft - alt1) / (alt2 - alt1)
            if ratio < 0.5:
                return ALTITUDE_COLOR_STOPS[i][2]
            else:
                return ALTITUDE_COLOR_STOPS[i + 1][2]

    return "gray"


def get_altitude_hex_color(altitude_ft: Optional[int]) -> str:
    """
    Get hex color based on altitude with smooth gradient interpolation.

    This is used for SVG icon coloring in JavaScript.

    Args:
        altitude_ft: Altitude in feet, or None for unknown

    Returns:
        Hex color string (e.g., "#FF8C00")
    """
    if altitude_ft is None:
        return "#808080"  # gray

    if altitude_ft <= ALTITUDE_COLOR_STOPS[0][0]:
        return ALTITUDE_COLOR_STOPS[0][1]
    if altitude_ft >= ALTITUDE_COLOR_STOPS[-1][0]:
        return ALTITUDE_COLOR_STOPS[-1][1]

    # Find the segment and interpolate
    for i in range(len(ALTITUDE_COLOR_STOPS) - 1):
        alt1, hex1, _ = ALTITUDE_COLOR_STOPS[i]
        alt2, hex2, _ = ALTITUDE_COLOR_STOPS[i + 1]

        if alt1 <= altitude_ft <= alt2:
            ratio = (altitude_ft - alt1) / (alt2 - alt1)
            return _interpolate_hex_colors(hex1, hex2, ratio)

    return "#808080"


def _hex_to_rgb(hex_color: str) -> Tuple[int, int, int]:
    """Convert hex color to RGB tuple."""
    hex_color = hex_color.lstrip('#')
    return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))


def _rgb_to_hex(r: int, g: int, b: int) -> str:
    """Convert RGB values to hex color string."""
    return f"#{r:02x}{g:02x}{b:02x}"


def _interpolate_hex_colors(color1: str, color2: str, ratio: float) -> str:
    """
    Interpolate between two hex colors.

    Args:
        color1: Starting hex color
        color2: Ending hex color
        ratio: Interpolation ratio (0.0 = color1, 1.0 = color2)

    Returns:
        Interpolated hex color
    """
    r1, g1, b1 = _hex_to_rgb(color1)
    r2, g2, b2 = _hex_to_rgb(color2)

    r = int(r1 + (r2 - r1) * ratio)
    g = int(g1 + (g2 - g1) * ratio)
    b = int(b1 + (b2 - b1) * ratio)

    return _rgb_to_hex(r, g, b)


def get_altitude_color_js() -> str:
    """
    Generate JavaScript function for altitude color mapping.

    Returns the JavaScript code as a string to be embedded in HTML.
    This ensures Python and JavaScript use the same color logic.
    """
    # Build color stops array for JavaScript
    stops_js = ",\n            ".join(
        f"[{alt}, '{hex_color}']"
        for alt, hex_color, _ in ALTITUDE_COLOR_STOPS
    )

    return f'''
    function getAltitudeColor(altitude_ft) {{
        if (altitude_ft === null || altitude_ft === undefined) return '#808080';

        const colorStops = [
            {stops_js}
        ];

        function hexToRgb(hex) {{
            const result = /^#?([a-f\\d]{{2}})([a-f\\d]{{2}})([a-f\\d]{{2}})$/i.exec(hex);
            return result ? {{
                r: parseInt(result[1], 16),
                g: parseInt(result[2], 16),
                b: parseInt(result[3], 16)
            }} : null;
        }}

        function rgbToHex(r, g, b) {{
            return '#' + [r, g, b].map(x => {{
                const hex = Math.round(x).toString(16);
                return hex.length === 1 ? '0' + hex : hex;
            }}).join('');
        }}

        function interpolateColor(color1, color2, ratio) {{
            const rgb1 = hexToRgb(color1);
            const rgb2 = hexToRgb(color2);
            if (!rgb1 || !rgb2) return color1;

            const r = rgb1.r + (rgb2.r - rgb1.r) * ratio;
            const g = rgb1.g + (rgb2.g - rgb1.g) * ratio;
            const b = rgb1.b + (rgb2.b - rgb1.b) * ratio;
            return rgbToHex(r, g, b);
        }}

        if (altitude_ft <= colorStops[0][0]) return colorStops[0][1];
        if (altitude_ft >= colorStops[colorStops.length - 1][0]) return colorStops[colorStops.length - 1][1];

        for (let i = 0; i < colorStops.length - 1; i++) {{
            if (altitude_ft >= colorStops[i][0] && altitude_ft <= colorStops[i + 1][0]) {{
                const ratio = (altitude_ft - colorStops[i][0]) / (colorStops[i + 1][0] - colorStops[i][0]);
                return interpolateColor(colorStops[i][1], colorStops[i + 1][1], ratio);
            }}
        }}
        return '#808080';
    }}
    '''
