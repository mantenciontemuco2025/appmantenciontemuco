import json
import os
from pathlib import Path
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict

# The project's .env lives inside the backend/ directory, next to the app code.
# Resolve it absolutely (relative to this file) so it works no matter where the
# command is run from (uvicorn, alembic, seed, tests...).
_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent  # backend/
_DEFAULT_ENV_FILE = _BACKEND_DIR / ".env"
_ENV_FILE = Path(
    os.environ.get("MAINTENANCE_ENV_FILE", _DEFAULT_ENV_FILE)
)


class Settings(BaseSettings):
    # PostgreSQL
    DATABASE_URL: str = (
        "postgresql+asyncpg://maintenance_user:maintenance_pass@localhost:5433/maintenance_db"
    )
    # Async SQLAlchemy pool. Keep these below the database provider's maximum
    # connection limit; the values are intentionally configurable per VPS.
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_TIMEOUT: int = 30
    DB_POOL_RECYCLE: int = 1800

    # JWT
    SECRET_KEY: str = "change-this-to-a-secure-random-string-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    # Web Push (VAPID). Keep the private key only in the local environment.
    VAPID_PUBLIC_KEY: str = ""
    VAPID_PRIVATE_KEY: str = ""
    VAPID_SUBJECT: str = "mailto:admin@example.com"

    # Email notifications. SMTP credentials stay only in backend/.env.
    EMAIL_ENABLED: bool = False
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = ""
    SMTP_REPLY_TO: str = ""
    SMTP_USE_TLS: bool = True
    EMAIL_APP_URL: str = "https://app.mantenciontemuco.cl"

    # CORS (JSON array as a string, e.g. '["http://localhost:3000"]')
    CORS_ORIGINS: str = '["http://localhost:3000"]'

    # Google OAuth (preferred — use your own Google account)
    # Obtained via: python scripts/google_oauth_setup.py
    GOOGLE_OAUTH_CLIENT_ID: str = ""
    GOOGLE_OAUTH_CLIENT_SECRET: str = ""
    GOOGLE_OAUTH_REFRESH_TOKEN: str = ""

    # Google Sheets via Service Account (fallback, optional).
    # Two mutually-complementary sources for the service account credentials:
    #   - GOOGLE_SERVICE_ACCOUNT_FILE: path (relative to backend/) to a JSON file
    #   - GOOGLE_SERVICE_ACCOUNT_JSON: the service-account JSON inline as a string.
    # GOOGLE_SERVICE_ACCOUNT_FILE takes precedence when both are present.
    GOOGLE_SERVICE_ACCOUNT_FILE: str = ""
    GOOGLE_SERVICE_ACCOUNT_JSON: str = ""
    GOOGLE_SPREADSHEET_ID: str = ""
    GOOGLE_SHEET_NAME: str = "Hoja1"

    # Google Drive — Work Order integration
    GOOGLE_OT_TEMPLATE_FILE_ID: str = ""
    # Optional dedicated template for contractor/external work orders.
    # When empty, external OTs use the regular template for backwards
    # compatibility; regular OTs are never affected by this setting.
    GOOGLE_EXTERNAL_OT_TEMPLATE_FILE_ID: str = ""
    GOOGLE_OT_ROOT_FOLDER_ID: str = ""
    # Legacy single monthly spreadsheet (kept for backfill/compat only; new
    # per-year resolution uses GoogleMonthlyRegister in PostgreSQL).
    GOOGLE_MONTHLY_SPREADSHEET_ID: str = ""
    # Master annual template (12 tabs, headers, formats; zero real OTs) and the
    # "REGISTRO MENSUAL/" folder where per-year registers are created.
    GOOGLE_MONTHLY_TEMPLATE_FILE_ID: str = ""
    GOOGLE_MONTHLY_ROOT_FOLDER_ID: str = ""

    # Google Drive — user signatures. Folder where each user's handwritten
    # signature image is stored (one file per user). Kept readable to
    # "anyone with the link" so Google Sheets can render it as an overlay
    # image on the OT document.
    GOOGLE_SIGNATURES_FOLDER_ID: str = ""
    # Apps Script web app that inserts a real signature image into the OT.
    GOOGLE_SIGNATURES_APPS_SCRIPT_URL: str = ""
    GOOGLE_SIGNATURES_APPS_SCRIPT_SECRET: str = ""

    # Environment: "development" | "production" (avoids mixing Drive/dev vs client).
    APP_ENV: str = "development"

    model_config = SettingsConfigDict(
        env_file=_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # -- Derived helpers (never expose secrets) -------------------------------

    @property
    def cors_origins_list(self) -> List[str]:
        return json.loads(self.CORS_ORIGINS)

    @property
    def push_configured(self) -> bool:
        return bool(self.VAPID_PUBLIC_KEY and self.VAPID_PRIVATE_KEY and self.VAPID_SUBJECT)

    @property
    def email_configured(self) -> bool:
        """True when email delivery is explicitly enabled and configured."""
        return bool(
            self.EMAIL_ENABLED
            and self.SMTP_HOST
            and self.SMTP_FROM
            and self.SMTP_USERNAME
            and self.SMTP_PASSWORD
        )

    @property
    def _google_oauth_configured(self) -> bool:
        """True when all three OAuth env vars are set."""
        return bool(
            self.GOOGLE_OAUTH_CLIENT_ID
            and self.GOOGLE_OAUTH_CLIENT_SECRET
            and self.GOOGLE_OAUTH_REFRESH_TOKEN
        )

    def get_google_credentials(self):
        """Return OAuth credentials (preferred) or Service Account (fallback).

        OAuth credentials auto-refresh the access token using the refresh_token.
        Service Account credentials are scoped to the requested API.
        Returns None if neither is configured.
        """
        # 1) OAuth (user's own Google account — preferred)
        if self._google_oauth_configured:
            from google.oauth2.credentials import Credentials

            return Credentials(
                token=None,  # will be auto-refreshed on first API call
                refresh_token=self.GOOGLE_OAUTH_REFRESH_TOKEN,
                token_uri="https://oauth2.googleapis.com/token",
                client_id=self.GOOGLE_OAUTH_CLIENT_ID,
                client_secret=self.GOOGLE_OAUTH_CLIENT_SECRET,
            )

        # 2) Service Account fallback
        try:
            sa_dict = self.google_credentials_dict
        except ValueError:
            # Misconfigured SA (missing/invalid file or JSON) => not usable
            return None
        if sa_dict is None:
            return None

        from google.oauth2 import service_account

        return service_account.Credentials.from_service_account_info(
            sa_dict,
            scopes=["https://www.googleapis.com/auth/drive"],
        )

    def get_google_write_credentials(self):
        """Return OAuth credentials for WRITE operations ONLY.

        Writes (Drive copy/create, Sheets edits/appends) are gated to OAuth:
        the Service Account is NEVER used as a fallback for writes. If OAuth
        is not configured, this raises a clear error. Callers must not swallow
        it silently — failing a write is safer than silently using the wrong
        identity.
        """
        if not self._google_oauth_configured:
            raise RuntimeError(
                "Google OAuth credentials are required for Drive/Sheets "
                "write operations."
            )
        return self.get_google_credentials()

    @property
    def google_write_enabled(self) -> bool:
        """True only when OAuth is configured (writes are possible)."""
        return self._google_oauth_configured

    @property
    def google_auth_method(self) -> str | None:
        """'oauth', 'service_account', or None if unconfigured.

        A misconfigured Service Account (missing/invalid file or JSON) is
        treated as NOT service_account configured — never raises.
        """
        if self._google_oauth_configured:
            return "oauth"
        try:
            return "service_account" if self.google_credentials_dict is not None else None
        except ValueError:
            return None

    @property
    def _credentials_file_path(self) -> Path | None:
        """Absolute path to the service-account file, if configured."""
        if not self.GOOGLE_SERVICE_ACCOUNT_FILE:
            return None
        candidate = Path(self.GOOGLE_SERVICE_ACCOUNT_FILE)
        return candidate if candidate.is_absolute() else (_BACKEND_DIR / candidate)

    def _load_credentials_from_file(self) -> dict:
        path = self._credentials_file_path
        if path is None:
            raise ValueError("GOOGLE_SERVICE_ACCOUNT_FILE no está definido")
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            raise ValueError(
                f"Archivo de credenciales no encontrado: {path}"
            )
        except json.JSONDecodeError:
            raise ValueError(
                f"El archivo de credenciales no es JSON válido: {path}"
            )
        if not isinstance(data, dict) or "private_key" not in data:
            raise ValueError(
                "El archivo de credenciales no parece un service-account de Google "
                "(falta la clave 'private_key')."
            )
        return data

    @property
    def google_credentials_dict(self) -> dict | None:
        """The service-account credentials as a dict, or None if unconfigured.

        Uses the file if set, otherwise the inline JSON string. Parsing errors are
        raised with a clear message that never includes the secret value.
        """
        # 1) File-based credentials (preferred)
        if self._credentials_file_path is not None:
            return self._load_credentials_from_file()

        # 2) Inline JSON string
        if not self.GOOGLE_SERVICE_ACCOUNT_JSON:
            return None
        try:
            data = json.loads(self.GOOGLE_SERVICE_ACCOUNT_JSON)
        except json.JSONDecodeError:
            raise ValueError(
                "GOOGLE_SERVICE_ACCOUNT_JSON no es JSON válido. "
                "Revisa la configuración de la variable de entorno."
            )
        if not isinstance(data, dict) or "private_key" not in data:
            raise ValueError(
                "GOOGLE_SERVICE_ACCOUNT_JSON no parece un service-account de Google "
                "(falta la clave 'private_key')."
            )
        return data

    @property
    def google_configured(self) -> bool:
        """True only when all three required Google settings are present.

        Never exposes the values themselves.
        """
        try:
            creds = self.google_credentials_dict
        except ValueError:
            # Misconfigured credentials with syntax errors => not "configured"
            return False
        return bool(creds and self.GOOGLE_SPREADSHEET_ID and self.GOOGLE_SHEET_NAME)


settings = Settings()
