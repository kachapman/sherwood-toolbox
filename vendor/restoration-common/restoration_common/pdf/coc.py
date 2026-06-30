#!/usr/bin/env python3
"""Certificate of Completion PDF generator with company branding."""

import os
from datetime import datetime

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from .base import PDFGenerator


class COCPDFGenerator(PDFGenerator):
    """Generates Certificate of Completion PDFs with company branding."""

    COC_PAGE_SIZE = A4

    def __init__(self, output_path, company_config: dict, job_info,
                 logo_path=None, signature_path=None, signature_name=None):
        super().__init__(output_path, company_config, logo_path)
        self.job_info = job_info
        self.signature_path = signature_path
        self.signature_name = signature_name

    def generate(self):
        c = canvas.Canvas(self.output_path, pagesize=self.COC_PAGE_SIZE)
        width, height = self.COC_PAGE_SIZE

        self._draw_header(c, width, height)
        self._draw_title(c, width, height)
        self._draw_fields(c, width, height)

        if self.signature_path and os.path.exists(self.signature_path):
            self._draw_signature(c, width, height)

        c.save()
        return self.output_path

    def _draw_header(self, c, width, height):
        logo_path = self._get_logo_path()
        if logo_path:
            try:
                logo_x = self.company_config.get("coc_logo_x", 78)
                logo_y = self.company_config.get("coc_logo_y", height - 98)
                logo_w = self.company_config.get("coc_logo_width", 205)
                logo_h = self.company_config.get("coc_logo_height", 45)
                c.drawImage(logo_path, logo_x, logo_y, width=logo_w, height=logo_h,
                            preserveAspectRatio=True, mask="auto", anchor="nw")
            except Exception as e:
                print(f"Warning: Could not load logo: {e}")

        c.setFont("Helvetica", 11)
        c.setFillColor(self.secondary_color)

        right_edge = width - 42
        c.drawRightString(right_edge, height - 72, self.company_config.get("address", ""))
        c.drawRightString(right_edge, height - 86, self.company_config.get("city_state_zip", ""))
        c.drawRightString(right_edge, height - 100, self.company_config.get("email", ""))
        c.drawRightString(right_edge, height - 114, self.company_config.get("phone", ""))

    def _draw_title(self, c, width, height):
        coc_title = self.company_config.get("coc_title", "CERTIFICATE OF COMPLETION")
        c.setFont("Helvetica-Bold", 17)
        c.setFillColor(self.secondary_color)

        title_width = c.stringWidth(coc_title, "Helvetica-Bold", 17)
        title_x = (width - title_width) / 2
        title_y = height - 175

        c.drawString(title_x, title_y, coc_title)

        c.setStrokeColor(self.secondary_color)
        c.setLineWidth(1)
        c.line(title_x, title_y - 12, title_x + title_width, title_y - 12)

    def _draw_fields(self, c, width, height):
        c.setFillColor(self.secondary_color)

        label_x = 85
        value_x = 150
        y_start = height - 230
        line_spacing = 25

        street = self.job_info.get("street", "")
        city_state_zip = self.job_info.get("city_state_zip", "")
        address_one_line = f"{street}, {city_state_zip}".strip(", ")

        fields = [
            ("Customer:", self.job_info.get("customer_name", "")),
            ("Address:", address_one_line),
            ("Job #:", self.job_info.get("job_number", "")),
            ("Sales Rep:", self.job_info.get("sales_rep", "")),
            ("Note:", self.job_info.get("note", "")),
        ]

        for i, (label, value) in enumerate(fields):
            y_pos = y_start - (i * line_spacing)

            c.setFont("Helvetica-Bold", 11)
            c.drawString(label_x, y_pos, label)

            c.setFont("Helvetica", 11)
            max_width = width - value_x - 50
            if label == "Note:":
                note_lines = self._wrap_text(value, "Helvetica", 11, max_width, c)
                for j, line in enumerate(note_lines[:3]):
                    c.drawString(value_x, y_pos - (j * 14), line)
            else:
                displayed_value = value
                while c.stringWidth(displayed_value, "Helvetica", 11) > max_width and len(displayed_value) > 0:
                    displayed_value = displayed_value[:-1]
                if len(displayed_value) < len(value):
                    displayed_value = displayed_value[:-3] + "..."
                c.drawString(value_x, y_pos, displayed_value)

    def _draw_signature(self, c, width, height):
        try:
            sig_width = 150
            sig_height = 50
            sig_x = width - 220
            sig_y = 120

            c.drawImage(self.signature_path, sig_x, sig_y, width=sig_width, height=sig_height,
                        preserveAspectRatio=True, mask="auto")

            c.setStrokeColor(self.medium_gray)
            c.line(sig_x, sig_y - 5, sig_x + sig_width, sig_y - 5)

            c.setFont("Helvetica", 8)
            c.setFillColor(self.text_secondary)
            signer = self.signature_name if self.signature_name else self.company_config.get("default_signature_name", "Representative")
            c.drawString(sig_x, sig_y - 18, f"By {signer}")
            c.drawString(sig_x, sig_y - 32, f"Date: {datetime.now().strftime('%m/%d/%Y')}")
        except Exception as e:
            print(f"Warning: Could not add signature: {e}")
