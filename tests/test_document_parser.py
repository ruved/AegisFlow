import pytest

from aegisflow.rag.document_parser import clean_text, parse_document


@pytest.mark.parametrize(
    "text",
    ["alpha\r\nbeta  \r\n", "alpha\rbeta \n"],
)
def test_clean_text_normalizes_line_endings_and_trailing_space(text):
    assert clean_text(text) == "alpha\nbeta"


def test_clean_text_preserves_leading_indentation_and_paragraphs():
    assert clean_text("  code\n\n\nnext paragraph  ") == "  code\n\nnext paragraph"


def test_markdown_and_log_keep_content_as_plain_text():
    markdown = "# Heading\r\n\r\n  - item  \r\n"
    log = "2026-10-30 ERROR payment failed\r\n"

    assert parse_document(markdown, ".md") == "# Heading\n\n  - item"
    assert parse_document(log, ".log") == "2026-10-30 ERROR payment failed"


def test_html_extracts_visible_text_and_block_boundaries():
    html = """<html><head><title>Incident</title>
    <style>.secret { display: none }</style></head><body>
    <h1>Payment outage</h1><p>Retries &amp; timeouts.</p>
    <script>ignore this token</script><ul><li>Check logs</li></ul>
    </body></html>"""

    result = parse_document(html, ".html")

    assert result == "Incident\n\nPayment outage\n\nRetries & timeouts.\n\nCheck logs"
    assert "ignore this token" not in result


def test_html_suffix_matching_is_case_insensitive():
    assert parse_document("<p>Hello</p>", ".HTML") == "Hello"
