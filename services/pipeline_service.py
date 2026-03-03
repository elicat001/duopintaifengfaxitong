"""
Services for Pipeline and PipelineRun CRUD operations.
"""

import json
from datetime import datetime
from typing import Optional, List

from models.database import get_connection


# -- helpers ------------------------------------------------------------------

_JSON_FIELDS_PIPELINE = (
    "enabled_stages", "trigger_config", "target_platforms",
    "target_account_group_ids", "target_topics", "target_languages",
    "target_content_types",
)

_JSON_FIELDS_RUN = ("stage_logs",)


def _row_to_dict(row, json_fields: tuple) -> dict:
    """Convert a sqlite3.Row to a plain dict, deserialising JSON fields."""
    if row is None:
        return {}
    d = dict(row)
    for field in json_fields:
        if field in d and isinstance(d[field], str):
            try:
                d[field] = json.loads(d[field])
            except (json.JSONDecodeError, TypeError):
                pass
    # Convert enabled (int 0/1) to bool when present
    if "enabled" in d:
        d["enabled"] = bool(d["enabled"])
    if "auto_approve" in d:
        d["auto_approve"] = bool(d["auto_approve"])
    return d


def _pipeline_dict(row) -> dict:
    return _row_to_dict(row, _JSON_FIELDS_PIPELINE)


def _run_dict(row) -> dict:
    return _row_to_dict(row, _JSON_FIELDS_RUN)


def _now() -> str:
    return datetime.now().isoformat()


# -- PipelineService ----------------------------------------------------------

class PipelineService:
    """CRUD for the `pipelines` table."""

    def __init__(self, db_path: str):
        self.db_path = db_path

    # -- create ---------------------------------------------------------------

    def create(self, data: dict) -> int:
        """Insert a new pipeline and return its id."""
        conn = get_connection(self.db_path)
        try:
            now = _now()

            # -- field-name compat: accept frontend aliases ---------------
            if "max_daily_generations" not in data and "daily_limit" in data:
                data["max_daily_generations"] = data["daily_limit"]
            if "max_daily_tokens" not in data and "daily_token_budget" in data:
                data["max_daily_tokens"] = data["daily_token_budget"]
            if "auto_approve" not in data and "auto_review" in data:
                data["auto_approve"] = data["auto_review"]
            if "ai_config_id" not in data and data.get("config_key"):
                # Resolve config_key string to its numeric id
                row = conn.execute(
                    "SELECT id FROM ai_configs WHERE config_key = ?",
                    (data["config_key"],),
                ).fetchone()
                if row:
                    data["ai_config_id"] = row[0] if not isinstance(row, dict) else row["id"]
            # -------------------------------------------------------------

            def _json_val(key, default):
                val = data.get(key, default)
                if not isinstance(val, str):
                    return json.dumps(val, ensure_ascii=False)
                return val

            enabled_stages = _json_val(
                "enabled_stages",
                ["trend_scan", "topic_select", "content_gen",
                 "variant_gen", "auto_review", "job_dispatch"],
            )
            trigger_config = _json_val("trigger_config", {})
            target_platforms = _json_val("target_platforms", [])
            target_account_group_ids = _json_val("target_account_group_ids", [])
            target_topics = _json_val("target_topics", [])
            target_languages = _json_val("target_languages", ["zh"])
            target_content_types = _json_val("target_content_types", ["image_single"])

            cur = conn.execute(
                """
                INSERT INTO pipelines
                    (name, description, enabled, mode, auto_approve,
                     enabled_stages, trigger_type, cron_expression,
                     trigger_config, target_platforms,
                     target_account_group_ids, target_topics,
                     target_languages, target_content_types,
                     max_daily_generations, max_daily_tokens,
                     max_daily_cost_usd, ai_config_id,
                     total_runs, last_run_at,
                     created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    data.get("name", ""),
                    data.get("description", ""),
                    1 if data.get("enabled") else 0,
                    data.get("mode", "semi_auto"),
                    1 if data.get("auto_approve") else 0,
                    enabled_stages,
                    data.get("trigger_type", "scheduled"),
                    data.get("cron_expression", ""),
                    trigger_config,
                    target_platforms,
                    target_account_group_ids,
                    target_topics,
                    target_languages,
                    target_content_types,
                    data.get("max_daily_generations", 20),
                    data.get("max_daily_tokens", 500000),
                    data.get("max_daily_cost_usd", 10.0),
                    data.get("ai_config_id"),
                    0,
                    None,
                    now,
                    now,
                ),
            )
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()

    # -- get ------------------------------------------------------------------

    def get(self, pipeline_id: int) -> Optional[dict]:
        """Return a single pipeline dict or None."""
        conn = get_connection(self.db_path)
        try:
            row = conn.execute(
                "SELECT * FROM pipelines WHERE id = ?", (pipeline_id,)
            ).fetchone()
            if row is None:
                return None
            return _pipeline_dict(row)
        finally:
            conn.close()

    # -- list_all -------------------------------------------------------------

    def list_all(self) -> List[dict]:
        """Return all pipelines, newest first."""
        conn = get_connection(self.db_path)
        try:
            rows = conn.execute(
                "SELECT * FROM pipelines ORDER BY id DESC"
            ).fetchall()
            return [_pipeline_dict(row) for row in rows]
        finally:
            conn.close()

    # -- update ---------------------------------------------------------------

    def update(self, pipeline_id: int, data: dict) -> bool:
        """Dynamically update mutable fields. Returns True if a row was updated."""
        conn = get_connection(self.db_path)
        try:
            # -- field-name compat: accept frontend aliases ---------------
            if "max_daily_generations" not in data and "daily_limit" in data:
                data["max_daily_generations"] = data.pop("daily_limit")
            if "max_daily_tokens" not in data and "daily_token_budget" in data:
                data["max_daily_tokens"] = data.pop("daily_token_budget")
            if "auto_approve" not in data and "auto_review" in data:
                data["auto_approve"] = data.pop("auto_review")
            if "ai_config_id" not in data and data.get("config_key"):
                config_key = data.pop("config_key")
                row = conn.execute(
                    "SELECT id FROM ai_configs WHERE config_key = ?",
                    (config_key,),
                ).fetchone()
                if row:
                    data["ai_config_id"] = row[0] if not isinstance(row, dict) else row["id"]
            # -------------------------------------------------------------

            sets: List[str] = []
            params: list = []

            simple_fields = [
                "name", "description", "mode",
                "trigger_type", "cron_expression",
                "max_daily_generations", "max_daily_tokens",
                "max_daily_cost_usd", "ai_config_id",
                "total_runs", "last_run_at",
            ]
            for field in simple_fields:
                if field in data:
                    sets.append(f"{field} = ?")
                    params.append(data[field])

            # Bool -> int fields
            for bool_field in ("enabled", "auto_approve"):
                if bool_field in data:
                    sets.append(f"{bool_field} = ?")
                    params.append(1 if data[bool_field] else 0)

            # JSON fields
            json_fields = [
                "enabled_stages", "trigger_config", "target_platforms",
                "target_account_group_ids", "target_topics",
                "target_languages", "target_content_types",
            ]
            for field in json_fields:
                if field in data:
                    sets.append(f"{field} = ?")
                    val = data[field]
                    if not isinstance(val, str):
                        val = json.dumps(val, ensure_ascii=False)
                    params.append(val)

            if not sets:
                return False

            sets.append("updated_at = ?")
            params.append(_now())
            params.append(pipeline_id)

            cur = conn.execute(
                f"UPDATE pipelines SET {', '.join(sets)} WHERE id = ?",
                params,
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    # -- delete ---------------------------------------------------------------

    def delete(self, pipeline_id: int) -> bool:
        """Delete a pipeline. Returns True if deleted."""
        conn = get_connection(self.db_path)
        try:
            cur = conn.execute(
                "DELETE FROM pipelines WHERE id = ?", (pipeline_id,)
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    # -- toggle ---------------------------------------------------------------

    def toggle(self, pipeline_id: int, enabled: bool) -> bool:
        """Enable or disable a pipeline. Returns True if a row was updated."""
        conn = get_connection(self.db_path)
        try:
            cur = conn.execute(
                "UPDATE pipelines SET enabled = ?, updated_at = ? WHERE id = ?",
                (1 if enabled else 0, _now(), pipeline_id),
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()


# -- PipelineRunService -------------------------------------------------------

class PipelineRunService:
    """CRUD for the `pipeline_runs` table."""

    def __init__(self, db_path: str):
        self.db_path = db_path

    # -- create_run -----------------------------------------------------------

    def create_run(self, pipeline_id: int, triggered_by: str = "scheduled") -> int:
        """Insert a new pipeline run and return its id."""
        conn = get_connection(self.db_path)
        try:
            now = _now()
            cur = conn.execute(
                """
                INSERT INTO pipeline_runs
                    (pipeline_id, status, current_stage, triggered_by,
                     trigger_detail, trends_found, topics_suggested,
                     contents_generated, variants_generated, jobs_created,
                     total_tokens_used, total_cost_usd,
                     error_message, stage_logs, started_at, completed_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    pipeline_id,
                    "running",
                    "",
                    triggered_by,
                    "",
                    0, 0, 0, 0, 0,
                    0, 0.0,
                    "",
                    "[]",
                    now,
                    None,
                ),
            )
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()

    # -- get_run --------------------------------------------------------------

    def get_run(self, run_id: int) -> Optional[dict]:
        """Return a single pipeline run dict or None."""
        conn = get_connection(self.db_path)
        try:
            row = conn.execute(
                "SELECT * FROM pipeline_runs WHERE id = ?", (run_id,)
            ).fetchone()
            if row is None:
                return None
            return _run_dict(row)
        finally:
            conn.close()

    # -- list_runs ------------------------------------------------------------

    def list_runs(
        self,
        pipeline_id: Optional[int] = None,
        status: Optional[str] = None,
        limit: int = 20,
    ) -> List[dict]:
        """Return pipeline runs, optionally filtered by pipeline_id / status."""
        conn = get_connection(self.db_path)
        try:
            query = "SELECT * FROM pipeline_runs WHERE 1=1"
            params: list = []

            if pipeline_id is not None:
                query += " AND pipeline_id = ?"
                params.append(pipeline_id)
            if status is not None:
                query += " AND status = ?"
                params.append(status)

            query += " ORDER BY id DESC LIMIT ?"
            params.append(limit)

            rows = conn.execute(query, params).fetchall()
            return [_run_dict(row) for row in rows]
        finally:
            conn.close()

    # -- update_run -----------------------------------------------------------

    def update_run(self, run_id: int, data: dict) -> bool:
        """Dynamically update mutable fields. Returns True if a row was updated."""
        conn = get_connection(self.db_path)
        try:
            sets: List[str] = []
            params: list = []

            simple_fields = [
                "status", "current_stage", "triggered_by", "trigger_detail",
                "trends_found", "topics_suggested", "contents_generated",
                "variants_generated", "jobs_created",
                "total_tokens_used", "total_cost_usd",
                "error_message", "completed_at",
            ]
            for field in simple_fields:
                if field in data:
                    sets.append(f"{field} = ?")
                    params.append(data[field])

            # JSON field
            if "stage_logs" in data:
                sets.append("stage_logs = ?")
                val = data["stage_logs"]
                if not isinstance(val, str):
                    val = json.dumps(val, ensure_ascii=False)
                params.append(val)

            if not sets:
                return False

            params.append(run_id)

            cur = conn.execute(
                f"UPDATE pipeline_runs SET {', '.join(sets)} WHERE id = ?",
                params,
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()
