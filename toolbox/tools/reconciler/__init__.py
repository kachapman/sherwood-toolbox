"""Estimate Reconciler tool: compare a carrier insurance estimate against a
contractor Xactimate estimate, surface the line items and Overhead & Profit the
carrier omits, and bridge the RCV gap between the two files. The blueprint and
routes live in routes.py; the pure engine (extract/match/reconcile/report) is
ported unchanged from the standalone reconciler, with text extraction on
PyMuPDF instead of poppler/Tesseract subprocesses."""
from .routes import bp

__all__ = ["bp"]
