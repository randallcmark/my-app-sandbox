# Firefox Capture Extension

The Firefox extension is the first proper browser-capture client. It is currently a local
developer-loaded WebExtension.

## Install For Local Testing

1. Start Application Tracker:

```bash
source .venv/bin/activate
make run
```

2. Log in and open Settings:

```text
http://127.0.0.1:8000/settings
```

3. Create a capture token and copy the one-time `ats_...` secret.

4. Open Firefox:

```text
about:debugging#/runtime/this-firefox
```

5. Select `Load Temporary Add-on`.

6. Choose:

```text
extensions/firefox/manifest.json
```

7. Open the extension Settings page and save:

```text
Tracker URL: http://127.0.0.1:8000
Capture token: ats_...
Capture mode: Full page and selected text
```

## Manual Smoke Test

1. Open the fixture page from this repository in Firefox:

```text
extensions/fixtures/jsonld-job.html
```

2. Click the extension icon.

3. Click `Capture this job`.

4. Open the board:

```text
http://127.0.0.1:8000/board?workflow=prospects
```

5. Confirm a saved job appears with:

- title: `Fixture Product Lead`;
- company: `Fixture Co`;
- location: `London, GB`;
- source platform from the opened page;
- description from JSON-LD.

Duplicate capture of the same page should update the existing job and report `Updated`.

The popup includes an `Open captured job` link after a successful capture.

## Capture Modes

- `Full page and selected text`: sends selected text, visible page text, and raw HTML.
- `Selected text only`: sends only selected text as the description and omits raw HTML/body text.
- `Structured page data only`: sends raw HTML for backend JSON-LD extraction and does not use body
  text as the description fallback.

## Package Locally

Create a repeatable zip package:

```bash
make package-firefox-extension
```

The package is written to:

```text
dist/application-tracker-firefox.zip
```

## Current Limits

- The extension is loaded temporarily and is not packaged or signed.
- Host permissions are currently limited to local tracker URLs.
- Some job sites may restrict content extraction. The extension sends raw page HTML when available so
  backend extraction can do the structured parsing.
- Chrome support should reuse most of this source after the Firefox path is stable.
