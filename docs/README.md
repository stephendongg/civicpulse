# CivicPulse Digest Preview

To preview the digest locally (with live data loading), serve the repository over HTTP and open the page in your browser.

```bash
python3 -m http.server 8000
```

Then visit [http://localhost:8000/docs/index.html](http://localhost:8000/docs/index.html).

When you are finished previewing, press `Ctrl+C` in the terminal to stop the server. This avoids cross-origin blocking when the page fetches `civicpulse_digest_New_York_NY.json`.

## Contributing to `docs/index.html`

* Keep the page self-contained: CSS lives in the `<style>` block at the top of the file, and JavaScript in the `<script>` block at the bottom.
* Group related selectors and functions, and prefer semantic HTML elements (e.g., `<header>`, `<main>`, `<footer>`, `<nav>`) for readability and accessibility.
* When adding new data-driven features, extend the JavaScript helper functions rather than introducing inline event handlers or duplicated DOM queries.
* Test changes by running the local preview server (above) to confirm the JSON data still renders without console errors.

## Capturing a quick preview screenshot

If you need to share a snapshot of the current layout, you can use Playwright once the local server is running:

```bash
python3 -m http.server 8000 &
playwright screenshot --device="Desktop Chrome" http://localhost:8000/docs/index.html digest-preview.png
```

Remember to stop the HTTP server afterward with `Ctrl+C`.
