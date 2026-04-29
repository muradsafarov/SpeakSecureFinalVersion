# ===========================================================
# Acme Shop Demo — Configuration
#
# This is a fake "third-party e-commerce site" used to demonstrate
# how a real integrator would consume the SpeakSecure OAuth flow.
#
# Configurable values are loaded from environment variables so that
# in production (Hugging Face Spaces) the SpeakSecure URL and the
# API key can be set via the platform's secret manager rather than
# hardcoded in source.
# ===========================================================

import os

# ----------- Where SpeakSecure lives -----------
# In local development this is http://localhost:8000.
# When deployed to HF Spaces this becomes the public Spaces URL,
# e.g. https://murad-speaksecure.hf.space
SPEAKSECURE_BASE_URL = os.environ.get(
    "SPEAKSECURE_BASE_URL",
    "http://localhost:8000",
)

# ----------- Where Acme Shop lives -----------
# Used to construct the redirect_uri sent to SpeakSecure /authorize.
# It must match one of the redirect_uris registered for our API key,
# otherwise SpeakSecure will reject the request.
ACME_SHOP_BASE_URL = os.environ.get(
    "ACME_SHOP_BASE_URL",
    "http://localhost:8001",
)

# ----------- Our API key -----------
# Issued by SpeakSecure via the create_api_key.py CLI.
# In production this would live in a secret manager — never in code.
# For the demo, you can either set the env var or paste the key below.
SPEAKSECURE_API_KEY = os.environ.get(
    "SPEAKSECURE_API_KEY",
    "Here has to be a key",  # Paste your key here for local dev, or set the env var
)

# ----------- Acme Shop server port -----------
ACME_SHOP_PORT = int(os.environ.get("ACME_SHOP_PORT", "8001"))

# ----------- Derived URLs -----------
# The redirect URI is sent to SpeakSecure as part of /authorize and
# must be registered exactly. Don't add trailing slashes by accident.
REDIRECT_URI = f"{ACME_SHOP_BASE_URL}/callback"