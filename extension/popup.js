const apiUrlInput = document.getElementById('apiUrl');
const resumeIdInput = document.getElementById('resumeId');
const scanBtn = document.getElementById('scanBtn');
const statusEl = document.getElementById('status');
const resultsEl = document.getElementById('results');

// Persist settings across popup opens so the user doesn't retype them every time
chrome.storage.local.get(['apiUrl', 'resumeId'], (data) => {
  if (data.apiUrl) apiUrlInput.value = data.apiUrl;
  if (data.resumeId) resumeIdInput.value = data.resumeId;
});
apiUrlInput.addEventListener('change', () => chrome.storage.local.set({ apiUrl: apiUrlInput.value }));
resumeIdInput.addEventListener('change', () => chrome.storage.local.set({ resumeId: resumeIdInput.value }));

function setStatus(msg, kind) {
  statusEl.textContent = msg;
  statusEl.className = kind || '';
}

async function getActiveTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  return tab;
}

async function askContentScriptToScan(tabId) {
  try {
    return await chrome.tabs.sendMessage(tabId, { type: 'SCAN_JOBS' });
  } catch (e) {
    // No content script listening yet (e.g. tab was open before the extension
    // loaded) -- inject it now, then retry once.
    await chrome.scripting.executeScript({ target: { tabId }, files: ['content.js'] });
    return await chrome.tabs.sendMessage(tabId, { type: 'SCAN_JOBS' });
  }
}

scanBtn.addEventListener('click', async () => {
  const apiUrl = apiUrlInput.value.trim().replace(/\/$/, '');
  const resumeId = parseInt(resumeIdInput.value, 10);
  resultsEl.innerHTML = '';

  if (!resumeId) {
    setStatus('Enter your Resume ID first (from the dashboard).', 'err');
    return;
  }

  const tab = await getActiveTab();
  if (!tab || !/linkedin\.com|indeed\.com/.test(tab.url || '')) {
    setStatus('Open a LinkedIn or Indeed job search page first.', 'err');
    return;
  }

  scanBtn.disabled = true;
  setStatus('Scanning visible listings...', '');

  let scanResponse;
  try {
    scanResponse = await askContentScriptToScan(tab.id);
  } catch (e) {
    setStatus('Could not read this page: ' + e.message, 'err');
    scanBtn.disabled = false;
    return;
  }

  if (!scanResponse || !scanResponse.ok) {
    setStatus('Scan failed: ' + (scanResponse ? scanResponse.error : 'no response'), 'err');
    scanBtn.disabled = false;
    return;
  }

  const jobs = scanResponse.jobs || [];
  if (jobs.length === 0) {
    setStatus('No job listings found on this page. Site layout may have changed -- see extension README.', 'err');
    scanBtn.disabled = false;
    return;
  }

  setStatus(`Found ${jobs.length} listing(s). Scoring against resume ${resumeId}...`, '');

  try {
    const res = await fetch(`${apiUrl}/jobs/capture-batch`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        resume_id: resumeId,
        jobs: jobs.map(j => ({ raw_text: j.raw_text, source_url: j.source_url })),
      }),
    });
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();

    const okCount = data.results.filter(r => r.ok).length;
    setStatus(`Captured ${okCount} of ${data.processed}. Open the dashboard to review.`, 'ok');

    resultsEl.innerHTML = '';
    data.results.forEach(r => {
      const row = document.createElement('div');
      row.className = 'result-row';
      if (r.ok) {
        row.innerHTML = `<span>${(r.job_title || 'Untitled').slice(0, 28)}</span><span class="score">${Math.round(r.fit_score)}</span>`;
      } else {
        row.innerHTML = `<span style="color:var(--signal-bad)">Failed: ${(r.error || '').slice(0, 40)}</span>`;
      }
      resultsEl.appendChild(row);
    });
  } catch (e) {
    setStatus('Backend request failed: ' + e.message, 'err');
  } finally {
    scanBtn.disabled = false;
  }
});
