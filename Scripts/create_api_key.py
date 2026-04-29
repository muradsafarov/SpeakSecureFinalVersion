# ===========================================================
# SpeakSecure — API Key Creation CLI
#
# Usage:
#   python scripts/create_api_key.py \
#       --name "Acme Shop" \
#       --origins "https://acme.com,https://staging.acme.com" \
#       --redirect-uris "https://acme.com/callback,https://staging.acme.com/callback"
#
# Optional flags:
#   --env live|test    (default: live)
#   --rate-limit N     (default: 1000 requests per hour)
#   --list             (list existing keys instead of creating)
#   --revoke KEY_ID    (revoke a key by its database ID)
#
# SECURITY WARNING:
#   The generated plaintext key is printed to stdout ONCE. It cannot
#   be retrieved later. The integrator must store it securely
#   (environment variable, secret manager, etc.) on their side.
#
# OAuth 2.0 NOTE:
#   --origins protects direct API calls (browsers checking the Origin header).
#   --redirect-uris protects the OAuth /authorize redirect — the URL where
#   we send the user after a successful voice verification. We require an
#   exact match of the redirect_uri at /authorize AND at /token exchange,
#   so phishing-style "redirect_uri=https://evil.com" attacks are blocked.
#
#   For self-service keys (used only by the SpeakSecure demo itself),
#   leave --redirect-uris empty.
# ===========================================================

import argparse
import sys
from pathlib import Path

# Add parent directory to path so we can import from project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from Storage.database import init_database
from Storage.api_key_repository import ApiKeyRepository
from Security.api_keys import (
    generate_api_key,
    hash_api_key,
    get_display_prefix,
)


def _parse_csv(value: str) -> list[str]:
    """Parse a comma-separated string into a list of trimmed non-empty strings."""
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def create_key(args):
    """Handle the create action."""
    origins = _parse_csv(args.origins)
    redirect_uris = _parse_csv(args.redirect_uris)

    # Generate the key (plaintext, shown to user once)
    plaintext_key = generate_api_key(environment=args.env)
    key_hash = hash_api_key(plaintext_key)
    key_prefix = get_display_prefix(plaintext_key)

    # Store in database
    repo = ApiKeyRepository()
    key_id = repo.create(
        key_hash=key_hash,
        key_prefix=key_prefix,
        name=args.name,
        origins=origins,
        redirect_uris=redirect_uris,
        rate_limit_per_hour=args.rate_limit,
    )

    # Output — this is the only time the plaintext key is ever displayed
    print()
    print("=" * 68)
    print(" API KEY CREATED")
    print("=" * 68)
    print(f"  Name:          {args.name}")
    print(f"  Environment:   {args.env}")
    print(f"  Rate limit:    {args.rate_limit} requests/hour")
    if origins:
        print("  Allowed from:")
        for origin in origins:
            print(f"                 {origin}")
    else:
        print("  Allowed from:  (any origin — server-to-server only)")
    if redirect_uris:
        print("  Redirect URIs:")
        for uri in redirect_uris:
            print(f"                 {uri}")
    else:
        print("  Redirect URIs: (none — this key cannot use OAuth /authorize)")
    print(f"  Database ID:   {key_id}")
    print()
    print(" API KEY (save this now — it will NOT be shown again):")
    print()
    print(f"   {plaintext_key}")
    print()
    print("=" * 68)
    print(" HOW TO USE:")
    print(f"   curl -H 'X-API-Key: {plaintext_key}' ...")
    print("=" * 68)
    print()


def list_keys(args):
    """Handle the --list action."""
    repo = ApiKeyRepository()
    keys = repo.list_all(include_revoked=args.include_revoked)

    if not keys:
        print("No API keys found. Create one with --name, --origins, --redirect-uris.")
        return

    print()
    print(f"{'ID':<4} {'PREFIX':<14} {'NAME':<28} {'RATE/HR':<10} {'STATUS':<8}")
    print("-" * 72)
    for key in keys:
        status = "revoked" if key["revoked_at"] else "active"
        name = key["name"][:27] + "…" if len(key["name"]) > 27 else key["name"]
        print(
            f"{key['id']:<4} "
            f"{key['key_prefix']:<14} "
            f"{name:<28} "
            f"{key['rate_limit_per_hour']:<10} "
            f"{status:<8}"
        )
        if key["origins"]:
            print(f"      origins:       {', '.join(key['origins'])}")
        if key["redirect_uris"]:
            print(f"      redirect_uris: {', '.join(key['redirect_uris'])}")
    print()


def revoke_key(args):
    """Handle the --revoke action."""
    repo = ApiKeyRepository()
    success = repo.revoke(args.revoke)
    if success:
        print(f"API key {args.revoke} has been revoked. It will no longer work.")
    else:
        print(f"No active API key with ID {args.revoke} was found.")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Manage SpeakSecure API keys."
    )
    parser.add_argument("--name", help="Human-readable name (e.g. 'Acme Shop')")
    parser.add_argument(
        "--origins",
        help="Comma-separated allowed origins for direct API calls "
             "(e.g. 'https://acme.com,https://staging.acme.com'). "
             "Leave empty for server-to-server-only keys.",
        default="",
    )
    parser.add_argument(
        "--redirect-uris",
        help="Comma-separated allowed OAuth redirect URIs "
             "(e.g. 'https://acme.com/callback'). "
             "Required if the integrator will use the /authorize OAuth flow. "
             "Leave empty for self-service keys.",
        default="",
    )
    parser.add_argument("--env", choices=["live", "test"], default="live",
                        help="Environment prefix for the key (default: live)")
    parser.add_argument("--rate-limit", type=int, default=1000,
                        help="Max requests per hour (default: 1000)")
    parser.add_argument("--list", action="store_true",
                        help="List existing keys instead of creating a new one")
    parser.add_argument("--include-revoked", action="store_true",
                        help="When listing, also show revoked keys")
    parser.add_argument("--revoke", type=int, metavar="KEY_ID",
                        help="Revoke an existing key by its database ID")

    args = parser.parse_args()

    # Make sure the database exists before any operation
    init_database()

    # Dispatch based on which action was requested
    if args.list:
        list_keys(args)
    elif args.revoke is not None:
        revoke_key(args)
    elif args.name:
        create_key(args)
    else:
        parser.print_help()
        print("\nERROR: Must specify --name (to create), --list, or --revoke.",
              file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()