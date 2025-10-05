# CivicPulse Digest Preview

To preview the digest locally (with live data loading), serve the repository over HTTP and open the page in your browser.

```bash
python3 -m http.server 8000
```

Then visit [http://localhost:8000/docs/index.html](http://localhost:8000/docs/index.html).

When you are finished previewing, press `Ctrl+C` in the terminal to stop the server. This avoids cross-origin blocking when the page fetches `civicpulse_digest_New_York_NY.json`.
