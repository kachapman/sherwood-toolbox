#!/usr/bin/env python3
"""Invoice PDF generator with company branding and multi-page pagination."""

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

from .base import PDFGenerator


class InvoicePDFGenerator(PDFGenerator):
    """Generates Invoice PDFs with company branding."""

    INVOICE_PAGE_SIZE = letter

    def __init__(self, output_path, company_config: dict, job_info, line_items,
                 logo_path=None, signature_path=None, signature_name=None):
        super().__init__(output_path, company_config, logo_path)
        self.job_info = job_info
        self.line_items = line_items
        self.signature_path = signature_path
        self.signature_name = signature_name

    def generate(self):
        c = canvas.Canvas(self.output_path, pagesize=self.INVOICE_PAGE_SIZE)
        width, height = self.INVOICE_PAGE_SIZE

        base_amount = self.job_info.get("base_charge", {}).get("amount", 0)
        grand_total = base_amount if base_amount > 0 else 0
        active_line_items = [(d, a) for d, a in self.line_items if a != 0]
        for desc, amount in active_line_items:
            grand_total += amount

        page_num = 1
        y_pos = 0
        MIN_Y = 140

        def start_new_page():
            nonlocal page_num, y_pos
            if page_num > 1:
                c.showPage()
            self._draw_header(c, width, height)
            if page_num == 1:
                self._draw_job_info(c, width, height)
                table_top = height - 270
            else:
                table_top = height - 150
            self._draw_table_header(c, width, table_top)
            y_pos = table_top - 35
            page_num += 1

        start_new_page()

        insurance_claim = self.job_info.get("insurance_claim", "")
        base_charge = self.job_info.get("base_charge", {})
        base_amount = base_charge.get("amount", 0)

        if insurance_claim or base_amount > 0:
            base_charge_desc = base_charge.get("description", "")
            custom_text = base_charge_desc if base_charge_desc and base_charge_desc != "Base Charge" else ""

            if insurance_claim:
                first_line_text = f"Insurance Claim # {insurance_claim}"
                if custom_text:
                    first_line_text += f" - {custom_text}"
            elif custom_text:
                first_line_text = custom_text
            else:
                first_line_text = ""

            if first_line_text or base_amount > 0:
                needs_space_for_total = not active_line_items
                if y_pos < MIN_Y + (50 if needs_space_for_total else 20):
                    start_new_page()

                c.setFont("Helvetica", 10.5)
                if first_line_text:
                    max_desc_width = width - 200
                    displayed_text = first_line_text
                    while c.stringWidth(displayed_text, "Helvetica", 10.5) > max_desc_width and len(displayed_text) > 0:
                        displayed_text = displayed_text[:-1]
                    if len(displayed_text) < len(first_line_text):
                        displayed_text = displayed_text[:-3] + "..."
                    c.drawString(48, y_pos, displayed_text)

                if base_amount > 0:
                    c.drawRightString(width - 43.5, y_pos, f"${base_amount:,.2f}")

                y_pos -= 20

        for i, (description, amount) in enumerate(active_line_items):
            is_last_item = (i == len(active_line_items) - 1)
            needed_room = 50 if is_last_item else 20
            if y_pos < MIN_Y + needed_room:
                start_new_page()

            c.setFont("Helvetica", 10.5)
            max_desc_width = width - 200
            displayed_desc = description
            while c.stringWidth(displayed_desc, "Helvetica", 10.5) > max_desc_width and len(displayed_desc) > 0:
                displayed_desc = displayed_desc[:-1]
            if len(displayed_desc) < len(description):
                displayed_desc = displayed_desc[:-3] + "..."

            c.drawString(48, y_pos, displayed_desc)

            if amount >= 0:
                price_str = f"${amount:,.2f}"
            else:
                price_str = f"-${abs(amount):,.2f}"
            c.drawRightString(width - 43.5, y_pos, price_str)

            y_pos -= 20

        if y_pos < MIN_Y + 40:
            start_new_page()
            y_pos -= 20

        y_pos -= 10

        c.setFillColor(self.light_gray)
        c.rect(36, y_pos - 25, width - 72, 30, fill=1, stroke=0)

        c.setFillColor(self.secondary_color)
        c.setFont("Helvetica-Bold", 12)
        c.drawString(45.75, y_pos - 10, "Grand Total")
        c.drawRightString(width - 43.5, y_pos - 10, f"${grand_total:,.2f}")

        notes = self.job_info.get("invoice_notes", "")
        if notes:
            notes_y = y_pos - 45
            if notes_y < MIN_Y:
                c.showPage()
                self._draw_header(c, width, height)
                notes_y = height - 150

            c.setFillColor(self.secondary_color)
            c.setFont("Helvetica-Bold", 10)
            c.drawString(45.75, notes_y, "Notes:")

            c.setFont("Helvetica", 9)
            note_lines = self._wrap_text(notes, "Helvetica", 9, width - 100, c)
            for i, line in enumerate(note_lines):
                c.drawString(45.75, notes_y - 15 - (i * 12), line)

        c.save()
        return self.output_path

    def _draw_header(self, c, width, height):
        logo_path = self._get_logo_path()
        if logo_path:
            try:
                logo_x = self.company_config.get("invoice_logo_x", 36)
                logo_y = self.company_config.get("invoice_logo_y", height - 60)
                logo_w = self.company_config.get("invoice_logo_width", 112.5)
                logo_h = self.company_config.get("invoice_logo_height", 24.75)
                c.drawImage(logo_path, logo_x, logo_y, width=logo_w, height=logo_h,
                            preserveAspectRatio=True, mask="auto", anchor="nw")
            except Exception as e:
                print(f"Warning: Could not load logo: {e}")

        c.setFont("Helvetica", 10.5)
        c.setFillColor(self.secondary_color)
        c.drawString(154.5, height - 50, self.company_config.get("name", "Company"))
        c.drawString(154.5, height - 63, self.company_config.get("address", ""))
        c.drawString(154.5, height - 76, self.company_config.get("city_state_zip", ""))

        invoice_title = self.company_config.get("invoice_title", "INVOICE")
        c.setFont("Helvetica-Bold", 22.5)
        c.setFillColor(self.secondary_color)
        c.drawString(396, height - 52, invoice_title)

    def _draw_job_info(self, c, width, height):
        c.setFont("Helvetica-Bold", 9)
        c.setFillColor(self.secondary_color)

        c.drawString(36, height - 117, "Location Address")
        c.setFont("Helvetica", 10)

        street = self.job_info.get("street", "")
        city_state_zip = self.job_info.get("city_state_zip", "")
        c.drawString(36, height - 132, street)
        c.drawString(36, height - 145, city_state_zip)

        customer_name = self.job_info.get("customer_name", "")
        c.setFont("Helvetica", 12)

        left_margin = 110
        if customer_name:
            c.drawString(left_margin, height - 195, customer_name)
        if street:
            c.drawString(left_margin, height - 210, street)
        if city_state_zip:
            c.drawString(left_margin, height - 225, city_state_zip)

        c.setFont("Helvetica-Bold", 9)
        label_x = 396

        c.drawString(label_x, height - 87, "Job:")
        c.setFont("Helvetica", 9)
        job_label_width = c.stringWidth("Job: ", "Helvetica-Bold", 9)
        c.drawString(label_x + job_label_width, height - 87, self.job_info.get("job_number", ""))

        c.setFont("Helvetica-Bold", 9)
        c.drawString(label_x, height - 101, "Invoice Number:")
        c.setFont("Helvetica", 9)
        inv_label_width = c.stringWidth("Invoice Number: ", "Helvetica-Bold", 9)
        c.drawString(label_x + inv_label_width, height - 101, self.job_info.get("invoice_number", ""))

        c.setFont("Helvetica-Bold", 9)
        c.drawString(label_x, height - 115, "Invoice Date:")
        c.setFont("Helvetica", 9)
        date_label_width = c.stringWidth("Invoice Date: ", "Helvetica-Bold", 9)
        c.drawString(label_x + date_label_width, height - 115, self.job_info.get("invoice_date", ""))

        c.setFont("Helvetica-Bold", 9)
        c.drawString(label_x, height - 129, "Terms:")
        c.setFont("Helvetica", 9)
        terms_label_width = c.stringWidth("Terms: ", "Helvetica-Bold", 9)
        default_terms = self.company_config.get("default_terms", "Upon Receipt")
        c.drawString(label_x + terms_label_width, height - 129, self.job_info.get("terms", default_terms))

    def _draw_table_header(self, c, width, table_top):
        header_height = 15
        c.setFillColor(self.light_gray)
        c.rect(36, table_top - header_height, width - 72, header_height, fill=1, stroke=0)
        c.setFillColor(self.secondary_color)
        c.setFont("Helvetica-Bold", 7.5)
        c.drawRightString(width - 43.5, table_top - 11, "PRICE")
