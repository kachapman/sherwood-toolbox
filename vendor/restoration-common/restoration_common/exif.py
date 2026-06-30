#!/usr/bin/env python3
"""Photo date extraction from EXIF, filename, or file mtime."""

import os
import re
from datetime import datetime
from typing import Optional

from PIL import Image
from PIL.ExifTags import TAGS


def get_image_date(filepath: str) -> Optional[datetime]:
    """Best-effort photo date: EXIF first, then file mtime, then now."""
    try:
        with Image.open(filepath) as img:
            exif_data = img._getexif()
            if exif_data:
                for tag_id, value in exif_data.items():
                    tag = TAGS.get(tag_id, tag_id)
                    if tag in ("DateTimeOriginal", "DateTime", "DateTimeDigitized"):
                        try:
                            return datetime.strptime(value, "%Y:%m:%d %H:%M:%S")
                        except ValueError:
                            continue
    except Exception:
        pass
    try:
        mtime = os.path.getmtime(filepath)
        return datetime.fromtimestamp(mtime)
    except Exception:
        return datetime.now()


def parse_date_from_filename(filename: str) -> Optional[datetime]:
    patterns = [
        (r"(\d{4})-(\d{2})-(\d{2})-(\d{2})-(\d{2})-(\d{2})",
         lambda m: datetime(int(m[1]), int(m[2]), int(m[3]), int(m[4]), int(m[5]), int(m[6]))),
        (r"(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})",
         lambda m: datetime(int(m[1]), int(m[2]), int(m[3]), int(m[4]), int(m[5]), int(m[6]))),
        (r"(\d{4})-(\d{2})-(\d{2})",
         lambda m: datetime(int(m[1]), int(m[2]), int(m[3]))),
    ]
    for pattern, parser in patterns:
        match = re.search(pattern, filename)
        if match:
            try:
                return parser(match)
            except ValueError:
                continue
    return None


def format_date(dt: datetime) -> str:
    return dt.strftime("%A, %B %d, %Y %I:%M %p").replace(" 0", " ")
