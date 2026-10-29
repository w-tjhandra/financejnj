"""Aset lokal: tidak ada CDN runtime dan CSS hasil build tersedia."""

from pathlib import Path

from django.conf import settings

TEMPLATES_DIR = Path(settings.BASE_DIR) / "templates"
STATIC_DIR = Path(settings.BASE_DIR) / "static"


def test_template_tidak_memuat_url_eksternal():
    offenders = []
    for path in TEMPLATES_DIR.rglob("*.html"):
        text = path.read_text(encoding="utf-8")
        if "http://" in text or "https://" in text:
            offenders.append(path.relative_to(TEMPLATES_DIR).as_posix())

    assert offenders == [], f"Template memuat URL eksternal: {offenders}"


def test_css_dan_vendor_tersedia():
    css = STATIC_DIR / "css" / "app.css"
    assert css.is_file(), "static/css/app.css belum di-build"
    assert ".btn" in css.read_text(encoding="utf-8")

    for name in ("htmx-2.0.4.min.js", "alpine-3.14.9.min.js", "chart-4.4.7.umd.min.js"):
        assert (STATIC_DIR / "vendor" / name).is_file(), f"vendor {name} hilang"
