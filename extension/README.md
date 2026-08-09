# Job Control Capture — Chrome Extension

Bulk-captures job listings from a LinkedIn or Indeed search results page
you're already viewing in your own logged-in browser, and sends them to
your Job Control backend to be parsed and scored against your resume.

**What this does NOT do:** log into anything, navigate on your behalf, or
query any site's search API directly. It only reads the DOM of the page
you're currently looking at -- same as any browser extension that reads
page content (ad blockers, price trackers, etc. all do this). That's what
keeps this inside normal browser use instead of automated scraping.

## Install (unpacked, for development)

1. Open Chrome and go to `chrome://extensions`
2. Turn on **Developer mode** (top-right toggle)
3. Click **Load unpacked**
4. Select this `extension/` folder
5. Pin the extension (puzzle-piece icon in the toolbar → pin "Job Control Capture")

## Use

1. Make sure your backend is running (`uvicorn app.main:app --reload`) and
   you've uploaded a resume via the dashboard — note the **Resume ID** it
   gives you (shown after upload, also visible in the dashboard status line).
2. Go to LinkedIn and run a normal job search (e.g. `linkedin.com/jobs/search/?keywords=AI+Engineer`),
   or search Indeed the same way.
3. Click the extension icon.
4. Enter your Resume ID (only needs doing once — it's remembered).
5. Click **Scan & capture this page**.
6. It reads every listing visible on that results page, sends them to your
   backend in one batch, and each gets parsed + scored immediately. Open
   the dashboard (`http://localhost:8000/`) to see them all as cards.
7. Scroll down the search results page (or go to the next results page) and
   click **Scan & capture this page** again to pick up more — it dedupes
   nothing on the extension side, so re-scanning the same page twice will
   create duplicate entries. Scan once per page of results.

## If a scan finds 0 listings

LinkedIn and Indeed change their page markup periodically, and the class
names `content.js` looks for aren't public/documented — they're current
best guesses, not something guaranteed to keep working. If a scan comes
back empty:

1. Right-click on a job card in the search results → **Inspect**
2. Look at the class names on the card container and the title link
3. Compare against the selectors at the top of `scanLinkedIn()` or
   `scanIndeed()` in `content.js`
4. Update the selectors to match what's actually there, reload the
   extension (`chrome://extensions` → refresh icon), and try again

This is a normal, expected maintenance task for any tool that reads a
third-party site's markup — it's not a sign something is fundamentally
broken.
