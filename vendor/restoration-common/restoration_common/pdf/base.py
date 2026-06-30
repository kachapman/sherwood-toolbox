#!/usr/bin/env python3
"""Base PDF generator with shared logo resolution and text wrapping."""

import os

from reportlab.lib.colors import HexColor

from ..paths import LOGO_DIR


class PDFGenerator:
    """Base class for PDF generation with common utilities."""

    def __init__(self, output_path, company_config: dict, logo_path=None):
        self.output_path = output_path
        self.company_config = company_config
        self.logo_path = logo_path

        self.primary_color = HexColor(company_config.get("primary_color", "#333333"))
        self.secondary_color = HexColor("#333333")
        self.light_gray = HexColor("#F5F5F5")
        self.medium_gray = HexColor("#E0E0E0")
        self.text_secondary = HexColor("#6E6E73")

    def _get_logo_path(self):
        if self.logo_path and os.path.exists(self.logo_path):
            return self.logo_path
        logo_file = self.company_config.get("logo_file", "logo.png")
        possible_paths = [
            LOGO_DIR / logo_file,
            LOGO_DIR / "logo.png",
            LOGO_DIR / "logo.jpg",
        ]
        for path in possible_paths:
            if path.exists():
                return str(path)
        return None

    def _wrap_text(self, text, font_name, font_size, max_width, canvas_obj):
        words = text.split()
        lines = []
        current_line = []
        for word in words:
            test_line = " ".join(current_line + [word])
            if canvas_obj.stringWidth(test_line, font_name, font_size) <= max_width:
                current_line.append(word)
            else:
                if current_line:
                    lines.append(" ".join(current_line))
                current_line = [word]
        if current_line:
            lines.append(" ".join(current_line))
        return lines
