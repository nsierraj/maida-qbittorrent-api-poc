"""Load connection settings from .env and build a connected client."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field

import requests
from dotenv import load_dotenv

from .client import QbtClient
from .errors import QbtError


@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    api_key: str = field(repr=False)
    sandbox_tag: str = "poc"
    sandbox_savepath: str | None = None

    @classmethod
    def from_env(cls) -> Settings:
        load_dotenv()
        missing = [k for k in ("QBT_HOST", "QBT_API_KEY") if not os.getenv(k)]
        if missing:
            sys.exit(f"Missing settings in .env: {', '.join(missing)} (copy .env.example)")
        try:
            port = int(os.getenv("QBT_PORT") or "8090")
        except ValueError:
            sys.exit(f"QBT_PORT must be a number, not {os.getenv('QBT_PORT')!r}")
        return cls(
            host=os.environ["QBT_HOST"].strip(),
            port=port,
            api_key=os.environ["QBT_API_KEY"].strip(),
            sandbox_tag=(os.getenv("QBT_SANDBOX_TAG") or "poc").strip(),
            sandbox_savepath=(os.getenv("QBT_SANDBOX_SAVEPATH") or "").strip() or None,
        )

    def client(self) -> QbtClient:
        return QbtClient(self.host, self.port, api_key=self.api_key)


def connect(settings: Settings) -> QbtClient:
    """Build a client and probe the key with app/webapiVersion, turning setup mistakes
    into readable exits. API keys can't call auth/login, so this is the auth check."""
    client = settings.client()
    try:
        client.get("app/webapiVersion")
    except requests.exceptions.ConnectionError as e:
        client.close()
        sys.exit(
            f"Cannot reach {client.base_url}: {e}\n"
            "Check QBT_HOST (the NAS LAN IP) and QBT_PORT (the WebUI port gluetun publishes)."
        )
    except QbtError as e:
        client.close()
        if e.is_auth_error:
            sys.exit(
                f"{e}\nCheck QBT_API_KEY (WebUI -> Options -> Web UI -> API Key). If QBT_HOST is a "
                "name rather than an IP, add it to 'Server domains' in the same options page."
            )
        sys.exit(f"Unexpected answer from {client.base_url}: {e}")
    return client


def mask(secret: str, keep: int = 6) -> str:
    return secret[:keep] + "…" if len(secret) > keep else "…"
