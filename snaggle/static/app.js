const form = document.querySelector("#download-form");
const input = document.querySelector("#video-url");
const button = document.querySelector("#download-button");
const detectStatus = document.querySelector("#detect-status");
const message = document.querySelector("#message");

let detectTimer = null;
let detectRequestId = 0;

function setMessage(text, type = "") {
  message.textContent = text;
  message.className = `message ${type}`.trim();
}

function setDetect(text, type = "") {
  detectStatus.textContent = text;
  detectStatus.className = `detect-status ${type}`.trim();
}

async function detectSource(url, requestId) {
  if (!url.trim()) {
    setDetect("Paste a link to detect source");
    return;
  }

  try {
    const response = await fetch("/api/detect", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    });
    const result = await response.json();
    if (requestId !== detectRequestId) return;

    if (result.supported) {
      setDetect(`Detected: ${result.platform}`, "is-supported");
    } else {
      setDetect("Unsupported link", "is-error");
    }
  } catch {
    if (requestId !== detectRequestId) return;
    setDetect("Could not check link", "is-error");
  }
}

function filenameFromResponse(response) {
  const disposition = response.headers.get("content-disposition") || "";
  const match = disposition.match(/filename\*=UTF-8''([^;]+)|filename="?([^"]+)"?/i);
  const rawName = match?.[1] || match?.[2] || "snaggle-video.mp4";
  return decodeURIComponent(rawName);
}

function scheduleDetection() {
  clearTimeout(detectTimer);
  detectRequestId += 1;
  const requestId = detectRequestId;
  const url = input.value.trim();

  setMessage("");
  if (!url) {
    setDetect("Paste a link to detect source");
    return;
  }

  setDetect("Checking link...");
  detectTimer = setTimeout(() => detectSource(url, requestId), 250);
}

input.addEventListener("input", scheduleDetection);
input.addEventListener("change", scheduleDetection);
input.addEventListener("paste", () => {
  window.setTimeout(scheduleDetection, 0);
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();

  button.disabled = true;
  button.textContent = "Working";
  setMessage("Preparing download...");

  try {
    const response = await fetch("/api/download", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url: input.value }),
    });

    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: "Download failed." }));
      throw new Error(error.detail || "Download failed.");
    }

    const blob = await response.blob();
    const fileUrl = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = fileUrl;
    anchor.download = filenameFromResponse(response);
    document.body.append(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(fileUrl);
    setMessage("Download ready.");
  } catch (error) {
    setMessage(error.message, "is-error");
  } finally {
    button.disabled = false;
    button.textContent = "Download";
  }
});
