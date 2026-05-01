# ===========================================================
# Acme Shop Demo - Configuration
#
# This is a fake "third-party e-commerce site" used to demonstrate
# how a real integrator would consume the SpeakSecure OAuth flow.
#
# All configurable values are loaded from environment variables.
# In production (Hugging Face Spaces) these are set via the
# platform's "Variables and secrets" settings panel; in local
# development you can either export them or rely on the defaults
# below (which assume both apps run on localhost).
# ===========================================================

import os

# ----------- Where SpeakSecure lives -----------
# In local development this is http://localhost:8000.
# When deployed to HF Spaces this becomes the public Spaces URL,
# e.g. https://NotDeadTed-speak-secure.hf.space
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
# Issued by SpeakSecure via the create_api_key.py CLI script.
# In production this lives in the Hugging Face Spaces secret manager.
# Never commit a real key to source control.
SPEAKSECURE_API_KEY = os.environ.get(
    "SPEAKSECURE_API_KEY",
    "PASTE_YOUR_API_KEY_HERE",
)

# ----------- Acme Shop server port -----------
# Hugging Face Spaces expects the application to listen on 7860.
# Locally we use 8001 to avoid clashing with SpeakSecure on 8000.
ACME_SHOP_PORT = int(os.environ.get("ACME_SHOP_PORT", "8001"))

# ----------- Derived URLs -----------
# The redirect URI is sent to SpeakSecure as part of /authorize and
# must be registered exactly. Don't add trailing slashes by accident.
REDIRECT_URI = f"{ACME_SHOP_BASE_URL}/callback"