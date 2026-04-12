import json
from pathlib import Path


EXTENSION_DIR = Path("extensions/firefox")


def test_firefox_extension_manifest_points_to_required_files() -> None:
    manifest = json.loads((EXTENSION_DIR / "manifest.json").read_text())

    assert manifest["manifest_version"] == 3
    assert manifest["permissions"] == ["activeTab", "storage", "scripting"]
    assert "http://127.0.0.1:8000/*" in manifest["host_permissions"]
    assert manifest["action"]["default_popup"] == "popup.html"
    assert manifest["options_ui"]["page"] == "options.html"

    required_files = [
        manifest["action"]["default_popup"],
        manifest["options_ui"]["page"],
        "popup.js",
        "options.js",
        "capture-page.js",
        "styles.css",
    ]
    for file_name in required_files:
        assert (EXTENSION_DIR / file_name).is_file()


def test_firefox_extension_posts_to_capture_api_with_bearer_token() -> None:
    popup_js = (EXTENSION_DIR / "popup.js").read_text()
    capture_js = (EXTENSION_DIR / "capture-page.js").read_text()
    options_html = (EXTENSION_DIR / "options.html").read_text()
    popup_html = (EXTENSION_DIR / "popup.html").read_text()

    assert "/api/capture/jobs" in popup_js
    assert "Authorization" in popup_js
    assert "Bearer" in popup_js
    assert "Open captured job" in popup_js
    assert "Tracker unreachable" in popup_js
    assert "Capture token was rejected" in popup_js
    assert "raw_html" in capture_js
    assert "capture_mode" in capture_js
    assert "application/ld+json" in capture_js
    assert "firefox_extension" in capture_js
    assert "capture-mode" in options_html
    assert "Selected text only" in options_html
    assert "result-link" in popup_html


def test_makefile_has_firefox_package_target() -> None:
    makefile = Path("Makefile").read_text()

    assert "package-firefox-extension" in makefile
    assert "application-tracker-firefox.zip" in makefile


def test_firefox_fixture_contains_jsonld_job_posting() -> None:
    fixture = Path("extensions/fixtures/jsonld-job.html").read_text()

    assert 'type="application/ld+json"' in fixture
    assert '"@type": "JobPosting"' in fixture
    assert "Fixture Product Lead" in fixture
