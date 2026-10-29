"""Buktikan WeasyPrint benar-benar bisa merender PDF di image (§11 T-005).

Test ini menjaga risiko utama scaffold: dependensi Pango/Cairo di python:slim.
Tanpa test ini, kegagalan baru terlihat di T-009 (export PDF).
"""

from weasyprint import HTML

MINIMAL_HTML = """
<!doctype html>
<html lang="id">
  <head><meta charset="utf-8"><title>Uji</title></head>
  <body><h1>Laporan Telur</h1><p>Halo dunia</p></body>
</html>
"""


def test_weasyprint_merender_pdf_minimal():
    pdf = HTML(string=MINIMAL_HTML).write_pdf()

    assert isinstance(pdf, bytes)
    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 1000
