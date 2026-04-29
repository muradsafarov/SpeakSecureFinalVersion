# Deployment Guide

Step-by-step instructions for deploying SpeakSecure and the Acme Shop demo integrator to Hugging Face Spaces. Two separate Spaces are needed because the OAuth flow is genuinely cross-domain — Acme Shop must redirect to SpeakSecure on a different host.

---

## Pre-deployment checklist

Before pushing anything, verify:

- [ ] `requirements.txt` is UTF-8 (run `file requirements.txt` — should say "UTF-8 text", not "UTF-16")
- [ ] `.gitignore` is at the project root
- [ ] `Demo/Js/config.js` has `API_BASE = "/api/v1"` (relative)
- [ ] `Demo/Js/config.js` has `API_KEY = "<your real key>"` (issued via the CLI)
- [ ] `AcmeShopDemo/config.py` reads from the env var name `SPEAKSECURE_API_KEY` (first arg to `os.environ.get`)
- [ ] `Data/speaksecure.db` is **NOT** committed (gitignored)
- [ ] `Core/AASIST/AASIST.pth` **IS** committed (small enough to ship in the repo)

---

## Part 1 — Push to GitHub

### 1.1 Initialise the repo

```
cd C:\Users\murad\PycharmProjects\SpeakSecureFinal
git init
git branch -M main
```

### 1.2 Verify `.gitignore` is working

```
git status
```

You should NOT see:
- `Data/speaksecure.db`
- `Data/Embeddings/*` (any user voice files)
- `Data/Logs/*`
- `__pycache__/`
- `.idea/`
- `.venv/`

If you see any of those, the `.gitignore` isn't being picked up. Check it's at the root of the repo (same folder as `main.py`).

### 1.3 First commit

```
git add .
git commit -m "Initial commit: SpeakSecure final project"
```

### 1.4 Create the GitHub repo

On https://github.com:
- New repository → name it `SpeakSecureFinal` (or whatever you want)
- Public or private (Hugging Face Spaces can pull from either)
- **Don't** initialise with a README — your local repo already has one

Then push:

```
git remote add origin https://github.com/<your-username>/SpeakSecureFinal.git
git push -u origin main
```

---

## Part 2 — Deploy SpeakSecure to Hugging Face Spaces

### 2.1 Create the Space

1. Go to https://huggingface.co/new-space
2. Owner: your username
3. Space name: `speak-secure` (the full URL will be `https://<your-username>-speak-secure.hf.space`)
4. License: MIT
5. Space SDK: **Docker** (this gives full control; the alternative "Gradio" / "Streamlit" SDKs won't work for FastAPI)
6. Hardware: CPU basic (the free tier is enough for a demo)
7. Visibility: Public

### 2.2 Create a `Dockerfile` at the project root

Hugging Face Spaces with the Docker SDK needs a Dockerfile. Add this at the **root of the project** (next to `main.py`):

```
FROM python:3.11-slim

WORKDIR /app

# System dependencies — ffmpeg is required for audio decoding
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Python dependencies first (for layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Project files
COPY . .

# Hugging Face Spaces expects port 7860
ENV PORT=7860
EXPOSE 7860

# Override the default port from config.py via an env var
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7860"]
```

Commit and push:

```
git add Dockerfile
git commit -m "Add Dockerfile for HF Spaces"
git push
```

### 2.3 Connect the GitHub repo to the Space

1. On your Space page → Settings → "Repository" section
2. Sync the Space with your GitHub repo (HF Spaces can either mirror a GitHub repo or be its own git remote — the simplest is to make the Space's git URL a second remote on your local repo and push there too)

Alternatively, push directly to the HF Space's git remote:

```
git remote add space https://huggingface.co/spaces/<your-username>/speak-secure
git push space main
```

### 2.4 Watch the build

The Space's "Logs" tab shows the Docker build. First build takes ~5–10 minutes:
- Layer 1: install ffmpeg + system deps (~30s)
- Layer 2: install Python deps incl. torch + CUDA libs (~3 min)
- Layer 3: copy project files (~5s)
- Startup: download ML model weights from HuggingFace Hub (~2 min — Whisper is the largest at ~470 MB)

Once you see `INFO:     Uvicorn running on http://0.0.0.0:7860`, the service is live at:

```
https://<your-username>-speak-secure.hf.space
```

### 2.5 Issue an API key for the Demo

The Demo embedded in this Space needs an API key. SSH into the Space's container is not enabled on the free tier, but you can run the script locally against your local SpeakSecure instance, then **copy the resulting database file** to the Space.

Easier: run the API key creation script locally **before** pushing:

```
# On your local machine
python Scripts/create_api_key.py \
    --name "Demo" \
    --origins "https://<your-username>-speak-secure.hf.space" \
    --redirect-uris "" \
    --rate-limit 1000
```

This prints the plaintext key. Copy it into `Demo/Js/config.js`:

```
const API_KEY = "ssk_live_<the-plaintext-key>";
```

Commit and push:

```
git add Demo/Js/config.js
git commit -m "Set API key for the deployed Demo"
git push
git push space main
```

⚠️ **The plaintext API key is now in your git history.** If the repo is public, anyone can read it and call your deployed API. The mitigations: (a) the key is bound to the HF Space origin (calls from elsewhere are blocked), and (b) it has an hourly rate limit. If the key is misused, you can revoke it via the CLI and issue a new one.

If the repo is private, this is much less of a concern.

### 2.6 Verify

Open `https://<your-username>-speak-secure.hf.space/api/v1/status` in a browser. You should see JSON with all four models showing `"loaded"`.

Open the root URL and try registering a voice — full pipeline should work.

---

## Part 3 — Deploy Acme Shop to its own Space

### 3.1 Create a separate repo for Acme

Acme Shop is a standalone app and needs its own Space. Easiest is to create a second GitHub repo containing only the `AcmeShopDemo/` folder's contents:

```
# Create a new local folder
mkdir AcmeShopDemoStandalone
cd AcmeShopDemoStandalone

# Copy AcmeShopDemo contents in (NOT the folder itself, the contents)
xcopy /E /I C:\Users\murad\PycharmProjects\SpeakSecureFinal\AcmeShopDemo\* .

# Init repo
git init
git branch -M main
git add .
git commit -m "Initial commit: Acme Shop demo"
```

On GitHub, create a new repo `AcmeShopDemo` and push:

```
git remote add origin https://github.com/<your-username>/AcmeShopDemo.git
git push -u origin main
```

### 3.2 Create the second Space

1. https://huggingface.co/new-space
2. Space name: `acme-shop` (URL: `https://<your-username>-acme-shop.hf.space`)
3. SDK: Docker
4. Hardware: CPU basic

### 3.3 Add a `Dockerfile` for Acme

Inside `AcmeShopDemoStandalone/`:

```
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PORT=7860
EXPOSE 7860

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "7860"]
```

(Note: `app:app` — `app.py` defines a variable named `app`.)

Commit and push:

```
git add Dockerfile
git commit -m "Add Dockerfile"
git push
```

### 3.4 Issue an API key for Acme

Back in your SpeakSecureFinal local checkout:

```
python Scripts/create_api_key.py \
    --name "Acme Shop" \
    --origins "https://<your-username>-acme-shop.hf.space" \
    --redirect-uris "https://<your-username>-acme-shop.hf.space/callback" \
    --rate-limit 5000
```

Copy the printed key — you'll paste it into the Space's environment variables in the next step.

⚠️ If you've already pushed `Demo/Js/config.js` with a different key for the Demo, this is a **second** key for Acme. Don't reuse the Demo key for Acme — the origin/redirect_uri whitelists wouldn't match.

⚠️ The new key is in `Data/speaksecure.db` on your local machine. You need to push this updated `.db` to the SpeakSecure Space (since `.db` is gitignored, you can't push it via git). Options:

- **Easiest:** delete `Data/speaksecure.db` from `.gitignore`, commit it, push, then add it back. Quick and dirty for a demo.
- **Cleaner:** add a startup script to the SpeakSecure container that creates fixed API keys from environment variables. Out of scope for this deadline.

For the FYP submission, the easiest path is:
1. Run `Scripts/create_api_key.py` locally to issue both keys
2. Temporarily remove `*.db` from `.gitignore`
3. Commit `Data/speaksecure.db`
4. Push to both remotes (GitHub and the HF Space)
5. Re-add `*.db` to `.gitignore` and commit that, but the .db is now tracked

### 3.5 Set environment variables on the Acme Space

On the Space page → Settings → "Variables and secrets":

| Name | Value | Type |
|---|---|---|
| `SPEAKSECURE_BASE_URL` | `https://<your-username>-speak-secure.hf.space` | Public variable |
| `ACME_SHOP_BASE_URL` | `https://<your-username>-acme-shop.hf.space` | Public variable |
| `SPEAKSECURE_API_KEY` | `ssk_live_<the-key-issued-above>` | **Secret** |

Click "Save" — the Space will restart automatically, picking up the new env vars.

### 3.6 Push and deploy

```
# Inside AcmeShopDemoStandalone/
git remote add space https://huggingface.co/spaces/<your-username>/acme-shop
git push space main
```

Wait for the build to finish (~2 min — much faster than SpeakSecure since no ML deps).

### 3.7 End-to-end test

1. Open `https://<your-username>-acme-shop.hf.space`
2. Click "Sign in with SpeakSecure"
3. You should be redirected to `https://<your-username>-speak-secure.hf.space/api/v1/authorize?...`
4. The page should show "Sign in to **Acme Shop**" (banner pulls the name from `/oauth/client-info`)
5. Enter a username that you registered earlier on SpeakSecure, get a challenge, speak it, submit
6. You should be redirected back to `https://<your-username>-acme-shop.hf.space/callback?code=...&state=...`
7. Acme Shop's backend exchanges the code, creates a session, redirects to `/dashboard`
8. The dashboard should greet you by your SpeakSecure user_id

If any step fails, check both Spaces' Logs tabs — the error will be there.

---

## Common deployment problems

**`requirements.txt` parse error during build.**
The file is UTF-16. Convert it to UTF-8: open in VS Code → Save with Encoding → UTF-8. Or use `iconv -f UTF-16LE -t UTF-8 requirements.txt > requirements.txt.new && mv requirements.txt.new requirements.txt`.

**Frontend loads but API calls return 401 / CORS errors.**
The API key in `Demo/Js/config.js` doesn't match what's in the deployed `speaksecure.db`. Either re-push `.db` with the right key, or re-issue the key bound to the deployed Space's origin and update `config.js`.

**Acme redirects to SpeakSecure but the page says "Unknown client".**
Acme's API key isn't in the SpeakSecure Space's `speaksecure.db`. You issued the key locally but didn't push the `.db`. See section 3.4.

**OAuth redirect_uri mismatch.**
SpeakSecure rejects the redirect_uri because it doesn't exactly match what's registered for Acme's API key. Common cause: trailing slash, http vs https, or the env var `ACME_SHOP_BASE_URL` doesn't match the actual Space URL.

**ML models fail to download on startup.**
HuggingFace Hub may be temporarily unavailable. The model loader retries 3 times with 5-second delays. If all retries fail, the container exits and HF restarts it automatically — usually works on the second container start.

**Container runs out of memory.**
The free CPU tier has 16 GB RAM, which is plenty for SpeakSecure (~3 GB peak). If you upgrade hardware, the model load time goes down dramatically (GPU loads Whisper in ~5s vs 60s on CPU).

---

## Post-deploy checklist for the FYP submission

- [ ] SpeakSecure Space `https://<your-username>-speak-secure.hf.space/api/v1/status` returns 200 with all four models loaded
- [ ] SpeakSecure root URL serves the Demo
- [ ] Acme Shop Space `https://<your-username>-acme-shop.hf.space` loads
- [ ] Click "Sign in" on Acme → redirects to SpeakSecure → completes flow → back to Acme dashboard
- [ ] Both Space URLs are added to the FYP report appendix (clickable links)
- [ ] GitHub repo URLs are added to the FYP report appendix
- [ ] A short demo video (screen recording) shows the OAuth round-trip