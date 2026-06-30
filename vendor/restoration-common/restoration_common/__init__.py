"""Shared core for the restoration document and photo-report tools.

Re-exports the common data and PDF helpers so apps can do::

    from restoration_common import load_companies, InvoicePDFGenerator
"""

from .paths import (
    DATA_DIR,
    LOGO_DIR,
    DEFAULT_COMPANIES_JSON,
    USER_CONFIG_DIR,
    USER_COMPANIES_JSON,
    USER_SIGNATURES_JSON,
    CRM_LOGIN_URL,
)
from .companies import (
    load_companies,
    load_default_companies,
    save_companies,
    get_company_by_id,
    flat_address,
)
from .credentials import (
    NeedsCredentialsError,
    load_crm_credentials,
    save_crm_credentials,
    clear_crm_credentials,
)
from .crm import crm_login, fetch_job_info_from_url
from .color import extract_primary_color
from .exif import get_image_date, parse_date_from_filename, format_date
from .signatures import (
    load_signatures,
    save_signatures,
    get_signature_path,
    save_signature_for_company,
    migrate_legacy_signatures,
)
from .pdf import (
    PDFGenerator,
    InvoicePDFGenerator,
    COCPDFGenerator,
    PhotoReportPDF,
    get_image_files,
    generate_output_filename,
    find_logo,
)

__all__ = [
    "DATA_DIR",
    "LOGO_DIR",
    "DEFAULT_COMPANIES_JSON",
    "USER_CONFIG_DIR",
    "USER_COMPANIES_JSON",
    "USER_SIGNATURES_JSON",
    "CRM_LOGIN_URL",
    "load_companies",
    "load_default_companies",
    "save_companies",
    "get_company_by_id",
    "flat_address",
    "NeedsCredentialsError",
    "load_crm_credentials",
    "save_crm_credentials",
    "clear_crm_credentials",
    "crm_login",
    "fetch_job_info_from_url",
    "extract_primary_color",
    "get_image_date",
    "parse_date_from_filename",
    "format_date",
    "load_signatures",
    "save_signatures",
    "get_signature_path",
    "save_signature_for_company",
    "migrate_legacy_signatures",
    "PDFGenerator",
    "InvoicePDFGenerator",
    "COCPDFGenerator",
    "PhotoReportPDF",
    "get_image_files",
    "generate_output_filename",
    "find_logo",
]
