#!/usr/bin/env python3
"""Extract a primary brand color from a logo image."""

from PIL import Image


def extract_primary_color(logo_path: str) -> str:
    """Return the dominant non-grayscale color of a logo as a hex string.

    Falls back to ``#333333`` if the image cannot be read.
    """
    try:
        with Image.open(logo_path) as img:
            img = img.convert("RGB")
            img.thumbnail((100, 100))
            quantized = img.quantize(colors=5, method=Image.Quantize.MEDIANCUT)
            palette = quantized.getpalette()
            colors = quantized.getcolors()
            if not colors or not palette:
                raise ValueError("Could not quantize")

            colors.sort(reverse=True)

            def is_grayscale(r, g, b, tolerance=20):
                return max(abs(r - g), abs(g - b), abs(r - b)) <= tolerance

            def brightness(r, g, b):
                return (r * 299 + g * 587 + b * 114) / 1000

            for count, idx in colors:
                r = palette[idx * 3]
                g = palette[idx * 3 + 1]
                b = palette[idx * 3 + 2]
                if brightness(r, g, b) < 30 or brightness(r, g, b) > 240:
                    continue
                if is_grayscale(r, g, b):
                    continue
                return f"#{r:02X}{g:02X}{b:02X}"

            count, idx = colors[0]
            r = palette[idx * 3]
            g = palette[idx * 3 + 1]
            b = palette[idx * 3 + 2]
            return f"#{r:02X}{g:02X}{b:02X}"
    except Exception:
        return "#333333"
