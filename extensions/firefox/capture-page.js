(() => {
  const captureOptions = globalThis.__APPLICATION_TRACKER_CAPTURE_OPTIONS__ || {};
  const captureMode = captureOptions.captureMode || "full";

  function text(value) {
    return (value || "").replace(/\s+/g, " ").trim();
  }

  function findJobPosting() {
    const scripts = document.querySelectorAll('script[type="application/ld+json"]');
    for (const script of scripts) {
      try {
        const raw = JSON.parse(script.textContent || "null");
        const items = Array.isArray(raw) ? raw : [raw];
        for (const item of items) {
          const graph = item && item["@graph"];
          const candidates = Array.isArray(graph) ? graph.concat(items) : items;
          for (const candidate of candidates) {
            const type = candidate && candidate["@type"];
            const types = Array.isArray(type) ? type : [type];
            if (types.includes("JobPosting")) {
              return candidate;
            }
          }
        }
      } catch (_error) {
        // Backend extraction will record invalid JSON-LD warnings when raw HTML is submitted.
      }
    }
    return {};
  }

  const jobPosting = findJobPosting();
  const selectedText = String(window.getSelection ? window.getSelection() : "").trim();
  const bodyText = text(document.body ? document.body.innerText : "").slice(0, 20000);
  const includeRawHtml = captureMode === "full" || captureMode === "structured";
  const rawHtml = includeRawHtml && document.documentElement
    ? document.documentElement.outerHTML.slice(0, 200000)
    : null;
  const h1 = document.querySelector("h1");
  const description = captureMode === "selection" ? selectedText : selectedText || bodyText;

  return {
    source_url: location.href,
    apply_url: location.href,
    title: text(jobPosting.title) || text(h1 && h1.innerText) || text(document.title) || location.href,
    description,
    selected_text: selectedText || null,
    source_platform: location.hostname,
    raw_html: rawHtml,
    raw_extraction_metadata: {
      extractor: "firefox_extension",
      capture_mode: captureMode,
      page_title: document.title,
      body_text: captureMode === "selection" ? null : bodyText,
      json_ld_job_posting: Boolean(jobPosting.title),
      captured_at: new Date().toISOString()
    }
  };
})();
