const captureButton = document.getElementById("capture-button");
const optionsButton = document.getElementById("options-button");
const statusElement = document.getElementById("status");
const resultLinkElement = document.getElementById("result-link");

function setStatus(message, isError = false) {
  statusElement.textContent = message;
  statusElement.classList.toggle("error", isError);
}

function setResultLink(trackerUrl, jobUuid) {
  resultLinkElement.replaceChildren();
  if (!trackerUrl || !jobUuid) {
    return;
  }

  const link = document.createElement("a");
  link.href = `${trackerUrl}/jobs/${jobUuid}`;
  link.target = "_blank";
  link.rel = "noreferrer";
  link.textContent = "Open captured job";
  resultLinkElement.appendChild(link);
}

async function getActiveTab() {
  const tabs = await browser.tabs.query({ active: true, currentWindow: true });
  return tabs[0];
}

async function extractCurrentPage(tabId, captureMode) {
  await browser.scripting.executeScript({
    target: { tabId },
    func: (options) => {
      globalThis.__APPLICATION_TRACKER_CAPTURE_OPTIONS__ = options;
    },
    args: [{ captureMode }]
  });

  const results = await browser.scripting.executeScript({
    target: { tabId },
    files: ["capture-page.js"]
  });
  return results && results[0] ? results[0].result : null;
}

async function captureCurrentTab() {
  captureButton.disabled = true;
  setResultLink();
  setStatus("Capturing...");

  try {
    const stored = await browser.storage.local.get({
      trackerUrl: "",
      captureToken: "",
      captureMode: "full"
    });
    const trackerUrl = stored.trackerUrl.trim().replace(/\/$/, "");
    const captureToken = stored.captureToken.trim();
    if (!trackerUrl || !captureToken) {
      throw new Error("Open Settings and save tracker URL plus capture token first.");
    }

    const tab = await getActiveTab();
    if (!tab || !tab.id) {
      throw new Error("No active tab available.");
    }
    if (!tab.url || !/^https?:|^file:/.test(tab.url)) {
      throw new Error("This page cannot be captured. Open a normal web page or local HTML fixture.");
    }

    const payload = await extractCurrentPage(tab.id, stored.captureMode);
    if (!payload) {
      throw new Error("Could not extract page data.");
    }

    const response = await fetch(`${trackerUrl}/api/capture/jobs`, {
      method: "POST",
      headers: {
        "Authorization": `Bearer ${captureToken}`,
        "Content-Type": "application/json"
      },
      body: JSON.stringify(payload)
    });

    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      if (response.status === 401 || response.status === 403) {
        throw new Error("Capture token was rejected. Create a new token in Settings and save it here.");
      }
      throw new Error(data.detail || `Capture failed with HTTP ${response.status}.`);
    }

    setStatus(`${data.created ? "Captured" : "Updated"}: ${data.title}`);
    setResultLink(trackerUrl, data.uuid);
  } catch (error) {
    if (error instanceof TypeError) {
      setStatus("Tracker unreachable. Check that Application Tracker is running and the tracker URL is correct.", true);
    } else {
      setStatus(error.message, true);
    }
  } finally {
    captureButton.disabled = false;
  }
}

captureButton.addEventListener("click", captureCurrentTab);
optionsButton.addEventListener("click", () => browser.runtime.openOptionsPage());
