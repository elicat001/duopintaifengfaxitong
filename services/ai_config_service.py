"""
Service for AI configuration CRUD and connection testing.
"""

import json
from datetime import datetime
from typing import Optional, List

from models.database import get_connection


# ── helpers ──────────────────────────────────────────────────────────────

def _row_to_dict(row) -> dict:
    """Convert a sqlite3.Row to a plain dict, deserialising JSON fields."""
    if row is None:
        return {}
    d = dict(row)
    # Deserialise JSON fields
    for field in ("prompt_templates",):
        if field in d and isinstance(d[field], str):
            try:
                d[field] = json.loads(d[field])
            except (json.JSONDecodeError, TypeError):
                pass
    return d


def _now() -> str:
    return datetime.now().isoformat()


# ── AIConfigService ────────────────────────────────────────────────────

class AIConfigService:
    """CRUD + connection test for the `ai_configs` table."""

    def __init__(self, db_path: str):
        self.db_path = db_path

    # -- create ----------------------------------------------------------------

    def create(self, data: dict) -> int:
        """Insert a new AI config and return its id.
        `config_key` must be unique."""
        conn = get_connection(self.db_path)
        try:
            now = _now()
            prompt_templates = data.get("prompt_templates", {})
            if not isinstance(prompt_templates, str):
                prompt_templates = json.dumps(prompt_templates, ensure_ascii=False)

            # Accept both "api_key" (frontend) and "api_key_encrypted" (DB column)
            api_key = data.get("api_key") or data.get("api_key_encrypted", "")

            cur = conn.execute(
                """
                INSERT INTO ai_configs
                    (config_key, provider, model, api_key_encrypted,
                     base_url, max_tokens, temperature, system_prompt,
                     prompt_templates, rate_limit_rpm, daily_token_budget,
                     enabled, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    data.get("config_key", ""),
                    data.get("provider", "anthropic"),
                    data.get("model", "claude-sonnet-4-20250514"),
                    api_key,
                    data.get("base_url", ""),
                    data.get("max_tokens", 4096),
                    data.get("temperature", 0.7),
                    data.get("system_prompt", ""),
                    prompt_templates,
                    data.get("rate_limit_rpm", 60),
                    data.get("daily_token_budget", 500000),
                    data.get("enabled", 1),
                    now,
                    now,
                ),
            )
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()

    # -- get -------------------------------------------------------------------

    def get(self, config_id: int) -> Optional[dict]:
        """Return a single AI config dict or None."""
        conn = get_connection(self.db_path)
        try:
            row = conn.execute(
                "SELECT * FROM ai_configs WHERE id = ?", (config_id,)
            ).fetchone()
            if row is None:
                return None
            return _row_to_dict(row)
        finally:
            conn.close()

    # -- get_by_key ------------------------------------------------------------

    def get_by_key(self, config_key: str) -> Optional[dict]:
        """Return an AI config by its unique config_key, or None."""
        conn = get_connection(self.db_path)
        try:
            row = conn.execute(
                "SELECT * FROM ai_configs WHERE config_key = ?", (config_key,)
            ).fetchone()
            if row is None:
                return None
            return _row_to_dict(row)
        finally:
            conn.close()

    # -- list_all --------------------------------------------------------------

    def list_all(self) -> List[dict]:
        """Return all AI configs."""
        conn = get_connection(self.db_path)
        try:
            rows = conn.execute(
                "SELECT * FROM ai_configs ORDER BY id DESC"
            ).fetchall()
            return [_row_to_dict(row) for row in rows]
        finally:
            conn.close()

    # -- update ----------------------------------------------------------------

    def update(self, config_id: int, data: dict) -> bool:
        """Dynamically update mutable fields. Returns True if a row was updated."""
        conn = get_connection(self.db_path)
        try:
            # Map frontend "api_key" to DB column "api_key_encrypted"
            if "api_key" in data and "api_key_encrypted" not in data:
                data["api_key_encrypted"] = data.pop("api_key")

            sets: List[str] = []
            params: list = []

            simple_fields = [
                "config_key", "provider", "model", "api_key_encrypted",
                "base_url", "max_tokens", "temperature", "system_prompt",
                "rate_limit_rpm", "daily_token_budget", "enabled",
            ]
            for field in simple_fields:
                if field in data:
                    sets.append(f"{field} = ?")
                    params.append(data[field])

            # JSON field
            if "prompt_templates" in data:
                sets.append("prompt_templates = ?")
                val = data["prompt_templates"]
                if not isinstance(val, str):
                    val = json.dumps(val, ensure_ascii=False)
                params.append(val)

            if not sets:
                return False

            sets.append("updated_at = ?")
            params.append(_now())
            params.append(config_id)

            cur = conn.execute(
                f"UPDATE ai_configs SET {', '.join(sets)} WHERE id = ?",
                params,
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    # -- delete ----------------------------------------------------------------

    def delete(self, config_id: int) -> bool:
        """Delete an AI config. Returns True if deleted."""
        conn = get_connection(self.db_path)
        try:
            cur = conn.execute(
                "DELETE FROM ai_configs WHERE id = ?", (config_id,)
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    # -- test_connection -------------------------------------------------------

    def test_connection(self, config_id: int) -> dict:
        """Try calling the configured AI API with a simple prompt.

        Returns ``{"ok": True/False, "message": "..."}``
        """
        cfg = self.get(config_id)
        if not cfg:
            return {"ok": False, "message": "Config not found"}

        provider = cfg.get("provider", "anthropic")
        api_key = cfg.get("api_key_encrypted", "")
        model = cfg.get("model", "")
        base_url = cfg.get("base_url", "")

        if not api_key:
            return {"ok": False, "message": "API key is empty"}

        try:
            from services.ai_provider_registry import get_sdk_type, get_default_base_url
            sdk_type = get_sdk_type(provider)
            effective_url = base_url or get_default_base_url(provider)

            if sdk_type == "anthropic":
                return self._test_anthropic(api_key, model, effective_url)
            elif sdk_type == "google":
                return self._test_google(api_key, model)
            else:  # openai_compatible
                return self._test_openai(api_key, model, effective_url)
        except Exception as exc:
            return {"ok": False, "message": str(exc)}

    def test_connection_direct(self, provider: str, model: str,
                               api_key: str, base_url: str) -> dict:
        """Test connection with raw parameters — no saved config needed."""
        if not api_key:
            return {"ok": False, "message": "API key is empty"}
        try:
            from services.ai_provider_registry import get_sdk_type, get_default_base_url
            sdk_type = get_sdk_type(provider)
            effective_url = base_url or get_default_base_url(provider)

            if sdk_type == "anthropic":
                return self._test_anthropic(api_key, model, effective_url)
            elif sdk_type == "google":
                return self._test_google(api_key, model)
            else:
                return self._test_openai(api_key, model, effective_url)
        except Exception as exc:
            return {"ok": False, "message": str(exc)}

    # -- private helpers -------------------------------------------------------

    @staticmethod
    def _test_anthropic(api_key: str, model: str, base_url: str) -> dict:
        """Send a minimal request to the Anthropic messages API."""
        import httpx

        url = (base_url.rstrip("/") if base_url else "https://api.anthropic.com") + "/v1/messages"
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        payload = {
            "model": model or "claude-sonnet-4-20250514",
            "max_tokens": 32,
            "messages": [{"role": "user", "content": "hi"}],
        }

        resp = httpx.post(url, headers=headers, json=payload, timeout=30)
        if resp.status_code == 200:
            return {"ok": True, "message": "连接成功"}
        else:
            try:
                body = resp.content.decode("utf-8", errors="replace")[:500]
            except Exception:
                body = str(resp.status_code)
            return {"ok": False, "message": f"HTTP {resp.status_code}: {body}"}

    @staticmethod
    def _test_openai(api_key: str, model: str, base_url: str) -> dict:
        """Send a minimal request to the OpenAI chat completions API."""
        import httpx

        # base_url from registry already includes /v1 (e.g. https://api.openai.com/v1)
        base = (base_url.rstrip("/") if base_url else "https://api.openai.com/v1")
        if base.endswith("/v1"):
            url = base + "/chat/completions"
        else:
            url = base + "/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model or "gpt-4o-mini",
            "max_tokens": 32,
            "messages": [{"role": "user", "content": "hi"}],
        }

        resp = httpx.post(url, headers=headers, json=payload, timeout=30)
        if resp.status_code == 200:
            return {"ok": True, "message": "连接成功"}
        else:
            try:
                body = resp.content.decode("utf-8", errors="replace")[:500]
            except Exception:
                body = str(resp.status_code)
            return {"ok": False, "message": f"HTTP {resp.status_code}: {body}"}

    @staticmethod
    def _test_google(api_key: str, model: str) -> dict:
        """Send a minimal request to the Google Gemini API."""
        try:
            from google import genai
        except ImportError:
            return {"ok": False, "message": "Google Gemini SDK 未安装，请运行: pip install google-genai"}
        try:
            client = genai.Client(api_key=api_key)
            response = client.models.generate_content(
                model=model or "gemini-2.0-flash",
                contents="hi",
                config={"max_output_tokens": 32},
            )
            if response.text:
                return {"ok": True, "message": "Google Gemini 连接成功"}
            return {"ok": False, "message": "Gemini 无响应"}
        except Exception as e:
            return {"ok": False, "message": f"Gemini 连接失败: {str(e)}"}
