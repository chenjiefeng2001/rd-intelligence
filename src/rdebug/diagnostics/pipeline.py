"""D7.1: a single public entry point that coordinates the diagnostic stages.

The pipeline does not reimplement any stage; each layer keeps its own public
interface so it can be tested and reused independently.
"""

from .markdown_renderer import render_markdown
from .report_assembler import assemble_report
from .report_validator import validate_report_quality


def run_diagnostic_pipeline(analysis, metadata=None, capture=None):
    """Return the authoritative JSON report and its Markdown rendering."""
    report = assemble_report(analysis, metadata, capture)
    markdown = render_markdown(report)
    quality = validate_report_quality(report, markdown)
    return {"report": report, "markdown": markdown, "quality": quality}
