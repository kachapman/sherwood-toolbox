#!/usr/bin/env python3
"""Photo report PDF generator and its image-discovery utilities."""

import os
import shutil
import tempfile
from typing import Callable, List, Optional

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor, black
from reportlab.pdfgen import canvas

from PIL import Image

from ..paths import LOGO_DIR
from ..companies import flat_address
from ..exif import get_image_date, format_date


class PhotoReportPDF:
    """Professional PDF photo report generator driven by a company_config dict."""

    PAGE_SIZE = letter
    MARGIN_TOP = 0.5 * inch
    MARGIN_BOTTOM = 0.5 * inch
    MARGIN_LEFT = 0.75 * inch
    MARGIN_RIGHT = 0.75 * inch
    IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".tiff", ".tif", ".webp"}
    PHOTO_INFO_PADDING = 20
    MAX_FILE_SIZE_MB = 5
    JPEG_QUALITY_START = 85
    JPEG_QUALITY_MIN = 30

    FONT_COMPANY_NAME = 14
    FONT_COMPANY_INFO = 9
    FONT_TITLE = 14
    FONT_PHOTO_INFO = 10
    FONT_FOOTER = 9

    def __init__(self, output_path: str, job_info: dict, company_config: dict, logo_path: str = None):
        self.output_path = output_path
        self.job_info = job_info
        self.company_config = company_config
        self.page_width, self.page_height = self.PAGE_SIZE
        self.logo_path = logo_path

        primary_hex = company_config.get("primary_color", "#333333")
        self.primary_color = HexColor(primary_hex)
        self.header_line_color = HexColor("#666666")
        self.text_color = black

    def generate(self, image_files: List[str],
                 progress_callback: Optional[Callable[[int, int], None]] = None,
                 max_size_mb: float = None) -> bool:
        if max_size_mb is None:
            max_size_mb = self.MAX_FILE_SIZE_MB

        max_size_bytes = max_size_mb * 1024 * 1024
        temp_dir = tempfile.mkdtemp(prefix="photo_report_")

        try:
            quality = self.JPEG_QUALITY_START
            while quality >= self.JPEG_QUALITY_MIN:
                processed_images = self._process_images(
                    image_files, temp_dir, quality, progress_callback
                )
                success = self._create_pdf(processed_images, progress_callback)
                if not success:
                    return False

                file_size = os.path.getsize(self.output_path)
                file_size_mb = file_size / (1024 * 1024)
                if file_size <= max_size_bytes:
                    print(f"  Final size: {file_size_mb:.2f} MB (quality: {quality})")
                    return True

                print(f"  Size {file_size_mb:.2f} MB exceeds {max_size_mb} MB, reducing quality...")
                quality -= 10
                for img_path, _, _ in processed_images:
                    if os.path.exists(img_path):
                        os.remove(img_path)

            print(f"  Warning: Could not reduce below {max_size_mb} MB at minimum quality")
            return True

        except Exception as e:
            print(f"Error generating PDF: {e}")
            import traceback
            traceback.print_exc()
            return False
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def _process_images(self, image_files: List[str], temp_dir: str,
                        quality: int, progress_callback) -> List[tuple]:
        processed = []
        total = len(image_files)
        for idx, image_path in enumerate(image_files):
            if progress_callback:
                progress_callback(idx + 1, total * 2)
            original_filename = os.path.basename(image_path)
            try:
                with Image.open(image_path) as img:
                    if img.mode in ("RGBA", "P"):
                        img = img.convert("RGB")
                    max_dimension = 1800
                    if img.width > max_dimension or img.height > max_dimension:
                        ratio = min(max_dimension / img.width, max_dimension / img.height)
                        new_size = (int(img.width * ratio), int(img.height * ratio))
                        img = img.resize(new_size, Image.LANCZOS)
                    output_path = os.path.join(temp_dir, f"img_{idx:04d}.jpg")
                    img.save(output_path, "JPEG", quality=quality, optimize=True)
                    processed.append((output_path, original_filename, image_path))
            except Exception as e:
                print(f"Warning: Could not process {image_path}: {e}")
                processed.append((image_path, original_filename, image_path))
        return processed

    def _create_pdf(self, image_data: List[tuple], progress_callback) -> bool:
        try:
            c = canvas.Canvas(self.output_path, pagesize=self.PAGE_SIZE)
            c.setTitle(f"{self.job_info['photo_title']} - {self.job_info['customer_name']}")
            c.setAuthor(self.company_config.get("name", "Company"))
            c.setSubject(f"Photo Report for {self.job_info['job_location']}")

            total = len(image_data)
            for idx, (image_path, original_filename, original_path) in enumerate(image_data):
                if progress_callback:
                    progress_callback(total + idx + 1, total * 2)
                self._create_page(c, image_path, original_filename, original_path, page_index=idx)
                if idx < total - 1:
                    c.showPage()
            c.save()
            return True
        except Exception as e:
            print(f"Error creating PDF: {e}")
            return False

    def _create_page(self, c: canvas.Canvas, image_path: str, display_filename: str = None,
                     original_path: str = None, page_index: int = 0):
        if display_filename is None:
            display_filename = os.path.basename(image_path)

        y_pos = self._draw_header(c)

        y_pos -= 10
        c.setStrokeColor(self.header_line_color)
        c.setLineWidth(0.5)
        c.line(self.MARGIN_LEFT, y_pos,
               self.page_width - self.MARGIN_RIGHT, y_pos)

        title_includes_claim = self.company_config.get("title_includes_claim", False)
        title_on_all_pages = self.company_config.get("title_on_all_pages", True)
        show_title = (page_index == 0) or title_on_all_pages

        if show_title:
            y_pos -= 25
            c.setFillColor(self.text_color)
            c.setFont("Helvetica-Bold", self.FONT_TITLE)
            if title_includes_claim and page_index == 0:
                title_text = f"{self.job_info['photo_title']} - Claim #{self.job_info['claim_number']}"
            else:
                title_text = self.job_info['photo_title']
            c.drawString(self.MARGIN_LEFT, y_pos, title_text)

        photo_date_str = None
        if self.job_info.get("photo_date"):
            photo_date_str = self.job_info["photo_date"]
        else:
            src = original_path if original_path else image_path
            dt = get_image_date(src)
            if dt:
                photo_date_str = format_date(dt)

        show_photo_date = self.company_config.get("show_photo_date", True)
        photo_info_height = 50 if (show_photo_date and photo_date_str) else 35
        footer_height = 45
        image_top = y_pos - 20
        image_bottom = self.MARGIN_BOTTOM + footer_height + photo_info_height + self.PHOTO_INFO_PADDING
        available_height = image_top - image_bottom
        available_width = self.page_width - self.MARGIN_LEFT - self.MARGIN_RIGHT

        max_img_width_inches = self.company_config.get("max_image_width", 5.0)
        max_width = min(available_width, max_img_width_inches * inch)
        x_offset = self.MARGIN_LEFT
        if self.company_config.get("image_alignment", "left") == "center":
            x_offset = self.MARGIN_LEFT + (available_width - max_width) / 2

        img_y, img_height = self._draw_image(c, image_path,
                                             x_offset,
                                             image_bottom,
                                             max_width,
                                             available_height)

        photo_info_y = img_y - self.PHOTO_INFO_PADDING
        self._draw_photo_info(c, display_filename, photo_info_y,
                              photo_date_str if show_photo_date else None)
        self._draw_footer(c)

    def _draw_header(self, c: canvas.Canvas) -> float:
        y_pos = self.page_height - self.MARGIN_TOP
        left_edge = self.MARGIN_LEFT
        right_edge = self.page_width - self.MARGIN_RIGHT

        logo_height = 0
        if self.logo_path and os.path.exists(self.logo_path):
            try:
                with Image.open(self.logo_path) as logo_img:
                    logo_w, logo_h = logo_img.size
                    aspect = logo_h / logo_w
                    logo_width_inches = self.company_config.get("logo_width", 1.0)
                    display_width = logo_width_inches * inch
                    display_height = display_width * aspect

                    logo_x = left_edge
                    logo_y = y_pos - display_height + 5

                    c.drawImage(self.logo_path, logo_x, logo_y,
                                width=display_width, height=display_height,
                                preserveAspectRatio=True, mask="auto")
                    logo_height = display_height
            except Exception as e:
                print(f"Warning: Could not load logo: {e}")
                self._draw_text_logo(c, y_pos, left_edge)
                logo_height = 30
        else:
            self._draw_text_logo(c, y_pos, left_edge)
            logo_height = 30

        contact_y = y_pos
        c.setFont("Helvetica", self.FONT_COMPANY_INFO)
        c.setFillColor(self.text_color)
        info_lines = [
            self.company_config.get("name", ""),
            flat_address(self.company_config),
            self.company_config.get("phone", ""),
        ]
        for line in info_lines:
            text_width = c.stringWidth(line, "Helvetica", self.FONT_COMPANY_INFO)
            c.drawString(right_edge - text_width, contact_y, line)
            contact_y -= 12

        contact_height = len(info_lines) * 12
        y_pos -= max(logo_height, contact_height) + 8
        return y_pos

    def _draw_text_logo(self, c: canvas.Canvas, y_pos: float, left_edge: float):
        lines = self.company_config.get("text_logo_lines", ["Company"])
        main_size = self.company_config.get("text_logo_font_size", 16)
        tagline_size = self.company_config.get("text_logo_tagline_size", 8)
        tagline_offset = self.company_config.get("text_logo_tagline_y_offset", 14)

        c.setFillColor(self.primary_color)
        c.setFont("Helvetica-Bold", main_size)
        c.drawString(left_edge, y_pos, lines[0])

        if len(lines) > 1:
            c.setFont("Helvetica", tagline_size)
            c.setFillColor(HexColor("#333333"))
            c.drawString(left_edge, y_pos - tagline_offset, lines[1])

    def _draw_image(self, c: canvas.Canvas, image_path: str,
                    x: float, y_bottom: float,
                    max_width: float, max_height: float) -> tuple:
        try:
            with Image.open(image_path) as img:
                img_width, img_height = img.size
                width_ratio = max_width / img_width
                height_ratio = max_height / img_height
                scale = min(width_ratio, height_ratio)

                final_width = img_width * scale
                final_height = img_height * scale

                x_pos = x
                if self.company_config.get("image_alignment", "left") == "center":
                    x_pos = x + (max_width - final_width) / 2

                y_pos = y_bottom + (max_height - final_height)

                c.drawImage(image_path, x_pos, y_pos,
                            width=final_width, height=final_height,
                            preserveAspectRatio=True)
                return (y_pos, final_height)
        except Exception as e:
            print(f"Error loading image {image_path}: {e}")
            c.setStrokeColor(self.header_line_color)
            c.rect(x, y_bottom, max_width, max_height)
            c.drawString(x + 10, y_bottom + max_height / 2,
                         f"Error loading: {os.path.basename(image_path)}")
            return (y_bottom, max_height)

    def _draw_photo_info(self, c: canvas.Canvas, filename: str, y_pos: float,
                         photo_date: str = None):
        c.setFont("Helvetica-Bold", self.FONT_PHOTO_INFO)
        c.setFillColor(self.text_color)
        c.drawString(self.MARGIN_LEFT, y_pos, filename)

        if photo_date:
            date_y = y_pos - 16
            label = "Photo Taken Date: "
            c.setFont("Helvetica-Bold", self.FONT_PHOTO_INFO)
            c.setFillColor(self.text_color)
            c.drawString(self.MARGIN_LEFT, date_y, label)
            label_width = c.stringWidth(label, "Helvetica-Bold", self.FONT_PHOTO_INFO)
            c.setFont("Helvetica", self.FONT_PHOTO_INFO)
            c.drawString(self.MARGIN_LEFT + label_width, date_y, photo_date)

    def _draw_footer(self, c: canvas.Canvas):
        y_pos = self.MARGIN_BOTTOM + 25
        c.setFont("Helvetica", self.FONT_FOOTER)
        c.setFillColor(self.text_color)
        job_id = self.job_info.get("job_id", "")
        if job_id:
            left_text = job_id
        else:
            left_text = self.job_info["customer_name"]
        c.drawString(self.MARGIN_LEFT, y_pos, left_text)
        right_text = f"Job Location: {self.job_info['job_location']}"
        text_width = c.stringWidth(right_text, "Helvetica", self.FONT_FOOTER)
        c.drawString(self.page_width - self.MARGIN_RIGHT - text_width, y_pos, right_text)


# =============================================================================
# Image discovery utilities
# =============================================================================

def get_image_files(folder: str, company_config: dict, exclude_logo: bool = True) -> List[str]:
    images = []
    logo_patterns = set(company_config.get("logo_patterns", ["logo"]))
    for filename in sorted(os.listdir(folder)):
        ext = os.path.splitext(filename)[1].lower()
        name_lower = os.path.splitext(filename)[0].lower()
        if ext in PhotoReportPDF.IMAGE_EXTENSIONS:
            if exclude_logo and any(pattern in name_lower for pattern in logo_patterns):
                continue
            images.append(os.path.join(folder, filename))
    return images


def generate_output_filename(job_info: dict) -> str:
    return f"{job_info['photo_title']} {job_info['customer_name']} - Claim #{job_info['claim_number']}.pdf"


def find_logo(photos_folder: str, company_config: dict) -> Optional[str]:
    logo_filename = company_config.get("logo_file", "logo.png")
    search_locations = [
        os.path.join(photos_folder, logo_filename),
        os.path.join(photos_folder, "logo.png"),
        os.path.join(photos_folder, "logo.jpg"),
        str(LOGO_DIR / logo_filename),
        str(LOGO_DIR / "logo.png"),
        str(LOGO_DIR / "logo.jpg"),
        logo_filename,
        "logo.png",
        "logo.jpg",
    ]
    for path in search_locations:
        if os.path.exists(path):
            return os.path.abspath(path)
    return None
