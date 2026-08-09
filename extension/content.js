/**
 * Reads job listing cards from whatever LinkedIn/Indeed search results
 * page the user is currently viewing in their own logged-in tab.
 *
 * IMPORTANT (why this file exists the way it does): this script only reads
 * the DOM of a page the user navigated to and is actively looking at. It
 * never logs in, never navigates on its own, never queries an API behind
 * the scenes. That distinction is what keeps this inside normal browser
 * use instead of automated scraping.
 *
 * CAVEAT: LinkedIn/Indeed frequently change their page markup, and these
 * class names aren't public/documented -- they're current best guesses.
 * If a scan comes back with 0 results, the first thing to check is
 * whether the selectors below still match what's actually in the page
 * (right-click a job card -> Inspect -> compare class names).
 */

function textOf(el) {
  return el ? el.textContent.replace(/\s+/g, ' ').trim() : '';
}

function absoluteUrl(href) {
  if (!href) return null;
  try {
    return new URL(href, window.location.origin).href;
  } catch {
    return null;
  }
}

function scanLinkedIn() {
  const cards = document.querySelectorAll(
    'li.jobs-search-results__list-item, div.job-card-container, li[data-occludable-job-id]'
  );
  const jobs = [];
  const seen = new Set();

  cards.forEach(card => {
    const link = card.querySelector('a[href*="/jobs/view/"]');
    const url = link ? absoluteUrl(link.getAttribute('href')) : null;
    if (url && seen.has(url)) return;

    const title = textOf(card.querySelector('.job-card-list__title, .job-card-container__link, strong'));
    const company = textOf(card.querySelector('.job-card-container__primary-description, .artdeco-entity-lockup__subtitle'));
    const fullText = textOf(card);

    if (title && fullText.length > 20) {
      jobs.push({ raw_text: `${title}\n${company}\n${fullText}`, source_url: url, title_hint: title });
      if (url) seen.add(url);
    }
  });

  if (jobs.length === 0) {
    // Fallback: grab any card-shaped container around a job-view link
    document.querySelectorAll('a[href*="/jobs/view/"]').forEach(link => {
      const url = absoluteUrl(link.getAttribute('href'));
      if (url && seen.has(url)) return;
      const container = link.closest('li') || link.closest('div') || link.parentElement;
      const fullText = textOf(container);
      if (fullText.length > 20) {
        jobs.push({ raw_text: fullText, source_url: url, title_hint: textOf(link) });
        if (url) seen.add(url);
      }
    });
  }

  return jobs;
}

function scanIndeed() {
  const cards = document.querySelectorAll('div.job_seen_beacon, td.resultContent');
  const jobs = [];
  const seen = new Set();

  cards.forEach(card => {
    const link = card.querySelector('a.jcs-JobTitle, h2.jobTitle a, a[id^="job_"]');
    const url = link ? absoluteUrl(link.getAttribute('href')) : null;
    if (url && seen.has(url)) return;

    const title = textOf(card.querySelector('h2.jobTitle, .jcs-JobTitle'));
    const company = textOf(card.querySelector('span.companyName'));
    const snippet = textOf(card.querySelector('.job-snippet, .css-9446fg'));
    const fullText = textOf(card);

    if (title && fullText.length > 20) {
      jobs.push({
        raw_text: `${title}\n${company}\n${snippet}\n${fullText}`,
        source_url: url,
        title_hint: title,
      });
      if (url) seen.add(url);
    }
  });

  if (jobs.length === 0) {
    document.querySelectorAll('a.jcs-JobTitle, h2.jobTitle a').forEach(link => {
      const url = absoluteUrl(link.getAttribute('href'));
      if (url && seen.has(url)) return;
      const container = link.closest('td') || link.closest('div') || link.parentElement;
      const fullText = textOf(container);
      if (fullText.length > 20) {
        jobs.push({ raw_text: fullText, source_url: url, title_hint: textOf(link) });
        if (url) seen.add(url);
      }
    });
  }

  return jobs;
}

function scanCurrentPage() {
  const host = window.location.hostname;
  if (host.includes('linkedin.com')) return scanLinkedIn();
  if (host.includes('indeed.com')) return scanIndeed();
  return [];
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === 'SCAN_JOBS') {
    try {
      const jobs = scanCurrentPage();
      sendResponse({ ok: true, jobs, site: window.location.hostname });
    } catch (e) {
      sendResponse({ ok: false, error: e.message });
    }
  }
  return true; // keep the message channel open for the async-style response
});
