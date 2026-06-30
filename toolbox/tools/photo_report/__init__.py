"""Photo Report tool: a web form over restoration_common's PhotoReportPDF.
Routes in routes.py; PDF logic is reused headless from restoration_common."""
from .routes import bp

__all__ = ["bp"]
