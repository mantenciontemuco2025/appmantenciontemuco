"""OAuth 2.0 setup script for Google Drive + Sheets.

Run from the backend/ directory:
    python scripts/google_oauth_setup.py

Opens a browser for Google consent. Prints the refresh_token ONCE
so you can add it to .env. NEVER commit secrets to Git.
"""

import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
CLIENT_SECRETS_FILE = BACKEND_DIR / "credentials" / "google-oauth-client.json"

SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/spreadsheets",
]


def main() -> None:
    if not CLIENT_SECRETS_FILE.exists():
        print(f"ERROR: No se encontro {CLIENT_SECRETS_FILE}")
        print("Descarga las credenciales OAuth de Google Cloud Console")
        print("y guardalas como backend/credentials/google-oauth-client.json")
        sys.exit(1)

    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_secrets_file(
        str(CLIENT_SECRETS_FILE), scopes=SCOPES
    )

    # Open browser for user consent. port=0 picks a random free port.
    credentials = flow.run_local_server(port=0, open_browser=True)

    print()
    print("=" * 60)
    print("  AUTENTICACION EXITOSA")
    print("=" * 60)
    print()
    print("Agrega estas 3 lineas a tu archivo backend/.env:")
    print()
    print(f"GOOGLE_OAUTH_CLIENT_ID={credentials.client_id}")
    print(f"GOOGLE_OAUTH_CLIENT_SECRET={credentials.client_secret}")
    print(f"GOOGLE_OAUTH_REFRESH_TOKEN={credentials.refresh_token}")
    print()
    print("  *** WARNING: NO hagas commit de estos valores ***")
    print("  *** WARNING: NO los subas a ningun repositorio  ***")
    print()

    # Verify token works
    try:
        from googleapiclient.discovery import build

        service = build("drive", "v3", credentials=credentials)
        about = service.about().get(fields="user").execute()
        user = about.get("user", {})
        print(f"Cuenta autenticada: {user.get('displayName')} ({user.get('emailAddress')})")
    except Exception as exc:
        print(f"Advertencia: no se pudo verificar Drive: {exc}")


if __name__ == "__main__":
    main()
