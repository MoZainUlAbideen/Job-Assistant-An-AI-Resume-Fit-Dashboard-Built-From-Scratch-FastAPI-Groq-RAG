// Where the backend lives. After deploying on Render, put your service URL here
// (no trailing slash), e.g. "https://job-assistant-api-vy8j.onrender.com".
// Locally (uvicorn on port 8000) this falls back to http://localhost:8000.
window.API_BASE = ["localhost", "127.0.0.1"].includes(location.hostname)
  ? "http://localhost:8000"
  : "https://job-assistant-api-vy8j.onrender.com";
