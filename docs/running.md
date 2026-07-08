# Running the App

## Recommended

Run the launcher from the repository root:

```powershell
.\run.ps1
```

The app will be available at:

```text
http://127.0.0.1:8000
```

## What the launcher does

- installs frontend dependencies if needed
- builds the frontend into static files
- prepares the backend virtual environment
- starts the API and serves the UI from the same local address

## Manual fallback

If you want to run the pieces separately, use the commands in the main README. The launcher is the easiest path because it gives you one local URL.

