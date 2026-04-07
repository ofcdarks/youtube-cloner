"""
ImageFX (Google Labs Imagen 3.5) client.

Port of the LaCasaStudio Node TS client to Python. Uses the user's
labs.google session cookie to fetch a short-lived bearer token, then
calls the runImageFx endpoint.

Usage:
    client = ImageFXClient(cookie)
    images = client.generate("a viral youtube thumbnail with bold red text", aspect="LANDSCAPE")
    # images = [{"base64": "...", "url": "data:image/png;base64,...", "seed": 42, "media_id": "..."}]
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import time
from datetime import datetime, timedelta
from typing import Any

import requests

logger = logging.getLogger("ytcloner.imagefx")


class ImageFXError(Exception):
    """Raised by ImageFXClient on any failure."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


_DEFAULT_HEADERS = {
    "Origin": "https://labs.google",
    "Content-Type": "application/json",
    "Referer": "https://labs.google/fx/tools/image-fx",
}


class ImageFXClient:
    """Single-account ImageFX client. Refreshes its bearer token automatically."""

    def __init__(self, cookie: str):
        if not cookie or not cookie.strip():
            raise ImageFXError("Cookie obrigatório — configure em Admin > ImageFX")
        self.cookie = cookie.strip()
        self._token: str | None = None
        self._token_expires_at: datetime | None = None
        self._user: dict | None = None

    # ─── auth ────────────────────────────────────────────────────

    def _fetch_session(self) -> dict:
        """Hit labs.google/fx/api/auth/session to grab a fresh bearer."""
        try:
            resp = requests.get(
                "https://labs.google/fx/api/auth/session",
                headers={
                    "Origin": "https://labs.google",
                    "Referer": "https://labs.google/fx/tools/image-fx",
                    "Cookie": self.cookie,
                },
                timeout=20,
            )
        except requests.RequestException as e:
            raise ImageFXError(f"Erro de rede ao buscar sessão: {e}")

        if resp.status_code in (401, 403):
            raise ImageFXError(
                "Cookie do ImageFX expirado ou inválido. Atualize em Admin > ImageFX.",
                status=resp.status_code,
            )
        if resp.status_code != 200:
            raise ImageFXError(
                f"labs.google/auth/session retornou {resp.status_code}",
                status=resp.status_code,
            )

        try:
            return resp.json()
        except ValueError as e:
            raise ImageFXError(f"Sessão retornou JSON inválido: {e}")

    def _refresh_session_if_needed(self) -> None:
        """Refresh the bearer token if it's missing or expires within 30s."""
        if (
            self._token
            and self._token_expires_at
            and self._token_expires_at > datetime.utcnow() + timedelta(seconds=30)
        ):
            return

        session = self._fetch_session()
        access_token = session.get("access_token")
        expires = session.get("expires")
        if not access_token or not expires:
            raise ImageFXError(
                "Sessão ImageFX inválida (sem access_token/expires). Atualize o cookie."
            )

        # `expires` is an ISO 8601 string like "2025-04-07T16:00:00.000Z"
        try:
            # Strip trailing Z and fractional seconds for fromisoformat
            cleaned = expires.replace("Z", "").split(".")[0]
            self._token_expires_at = datetime.fromisoformat(cleaned)
        except Exception:
            # Fallback: assume 50 minutes from now
            self._token_expires_at = datetime.utcnow() + timedelta(minutes=50)

        self._token = access_token
        self._user = session.get("user")
        logger.info(f"ImageFX session refreshed (expires {self._token_expires_at.isoformat()})")

    def _auth_headers(self) -> dict[str, str]:
        if not self._token:
            raise ImageFXError("Token ausente após refresh — bug interno")
        return {
            **_DEFAULT_HEADERS,
            "Cookie": self.cookie,
            "Authorization": f"Bearer {self._token}",
        }

    # ─── generation ──────────────────────────────────────────────

    def generate(
        self,
        prompt: str,
        aspect: str = "LANDSCAPE",
        num_images: int = 1,
        timeout: int = 90,
    ) -> list[dict[str, Any]]:
        """
        Generate images via ImageFX (Imagen 3.5).

        aspect: LANDSCAPE | PORTRAIT | SQUARE
        num_images: 1-4
        Returns list of {base64, url, seed, media_id}.
        """
        if not prompt or not prompt.strip():
            raise ImageFXError("Prompt vazio")

        self._refresh_session_if_needed()

        aspect_map = {
            "LANDSCAPE": "IMAGE_ASPECT_RATIO_LANDSCAPE",
            "PORTRAIT": "IMAGE_ASPECT_RATIO_PORTRAIT",
            "SQUARE": "IMAGE_ASPECT_RATIO_SQUARE",
        }
        aspect_ratio = aspect_map.get(aspect.upper(), "IMAGE_ASPECT_RATIO_LANDSCAPE")

        payload = {
            "userInput": {
                "candidatesCount": max(1, min(num_images, 4)),
                "prompts": [prompt.strip()],
                "seed": secrets.randbelow(2_147_483_647),
            },
            "clientContext": {
                "sessionId": f"{int(time.time() * 1000)}-{secrets.token_hex(8)}",
                "tool": "IMAGE_FX",
            },
            "modelInput": {"modelNameType": "IMAGEN_3_5"},
            "aspectRatio": aspect_ratio,
        }

        try:
            resp = requests.post(
                "https://aisandbox-pa.googleapis.com/v1:runImageFx",
                json=payload,
                headers=self._auth_headers(),
                timeout=timeout,
            )
        except requests.Timeout:
            raise ImageFXError(f"Timeout — ImageFX demorou mais de {timeout}s")
        except requests.RequestException as e:
            raise ImageFXError(f"Erro de rede ImageFX: {e}")

        if resp.status_code != 200:
            raise ImageFXError(
                self._parse_error(resp.text, resp.status_code),
                status=resp.status_code,
            )

        try:
            data = resp.json()
        except ValueError:
            raise ImageFXError("ImageFX retornou JSON inválido")

        panels = data.get("imagePanels") or []
        if not panels:
            raise ImageFXError("Nenhum painel de imagens retornado")
        generated = panels[0].get("generatedImages") or []
        if not generated:
            raise ImageFXError("Nenhuma imagem gerada")

        results: list[dict[str, Any]] = []
        for img in generated:
            b64 = img.get("encodedImage")
            if not b64:
                continue
            results.append(
                {
                    "base64": b64,
                    "url": f"data:image/png;base64,{b64}",
                    "seed": img.get("seed"),
                    "media_id": img.get("mediaGenerationId"),
                }
            )

        if not results:
            raise ImageFXError("Imagens retornadas sem dado base64")

        logger.info(f"ImageFX generated {len(results)} image(s) for prompt: {prompt[:60]}…")
        return results

    @staticmethod
    def _parse_error(text: str, status: int) -> str:
        """Best-effort error message extraction from a Google API error body."""
        try:
            data = json.loads(text)
            details = (data.get("error") or {}).get("details") or []
            reason = details[0].get("reason") if details else None
            if reason == "PUBLIC_ERROR_UNSAFE_GENERATION":
                return "Prompt bloqueado: conteúdo inseguro/explícito"
            if reason == "PUBLIC_ERROR_PROMINENT_PEOPLE_FILTER_FAILED":
                return "Prompt bloqueado: pessoas famosas não permitidas"
            if reason and ("QUALITY" in reason or "AESTHETIC" in reason):
                return "Prompt bloqueado: qualidade insuficiente, melhore o prompt"
            msg = (data.get("error") or {}).get("message")
            if msg:
                return f"ImageFX {status}: {msg}"
        except Exception:
            pass
        if status == 429:
            return "Limite de requisições do ImageFX atingido. Aguarde alguns minutos."
        return f"ImageFX {status}: {text[:200]}"


# ─── DB-backed convenience helpers ───────────────────────────────

def get_imagefx_cookie() -> str:
    """Read the saved (Fernet-encrypted) ImageFX cookie from admin_settings.

    Falls back to env IMAGEFX_COOKIE if no DB row exists. Returns empty
    string if neither is configured.
    """
    try:
        from database import get_setting
        from database import _decrypt_api_key  # private but useful
        raw = get_setting("imagefx_cookie") or ""
        if not raw:
            return os.environ.get("IMAGEFX_COOKIE", "")
        # Try to decrypt; if it isn't encrypted (legacy/plain), return as-is
        try:
            decrypted = _decrypt_api_key(raw)
            return decrypted or raw
        except Exception:
            return raw
    except Exception as e:
        logger.warning(f"get_imagefx_cookie failed: {e}")
        return os.environ.get("IMAGEFX_COOKIE", "")


def set_imagefx_cookie(cookie: str) -> None:
    """Persist the cookie Fernet-encrypted in admin_settings."""
    from database import set_setting, _encrypt_api_key
    encrypted = _encrypt_api_key(cookie) if cookie else ""
    set_setting("imagefx_cookie", encrypted)


def get_client() -> ImageFXClient:
    """Build a client from the saved cookie. Raises ImageFXError if missing."""
    cookie = get_imagefx_cookie()
    if not cookie:
        raise ImageFXError(
            "Cookie do ImageFX não configurado. Vá em Admin > Configurações e cole o cookie."
        )
    return ImageFXClient(cookie)
