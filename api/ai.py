"""
Blueprint for all AI module REST APIs:
  - AI Configs
  - Trends
  - Topic Suggestions
  - Content / Variant Generation
  - Generation Logs
  - Pipelines & Pipeline Runs
  - AI Dashboard
"""

import logging

from flask import Blueprint, request, jsonify
from config import DB_PATH, DEFAULT_RSS_FEEDS
from api.auth import require_auth
from services.ai_config_service import AIConfigService
from services.trend_service import TrendService
from services.topic_suggestion_service import TopicSuggestionService
from services.ai_generation_service import AIGenerationService
from services.pipeline_service import PipelineService, PipelineRunService
from agents.ai_pipeline_executor import AIPipelineExecutor

logger = logging.getLogger(__name__)

ai_bp = Blueprint("ai", __name__)

# ── Service instances ────────────────────────────────────────────────────

ai_config_svc = AIConfigService(DB_PATH)
trend_svc = TrendService(DB_PATH)
topic_svc = TopicSuggestionService(DB_PATH)
gen_svc = AIGenerationService(DB_PATH)
pipeline_svc = PipelineService(DB_PATH)
run_svc = PipelineRunService(DB_PATH)


# ══════════════════════════════════════════════════════════════════════════
# AI Configs
# ══════════════════════════════════════════════════════════════════════════


@ai_bp.route("/api/ai/providers", methods=["GET"])
@require_auth
def list_ai_providers():
    """Return provider registry with model catalogs for frontend dropdowns."""
    try:
        from services.ai_provider_registry import get_all_providers
        providers = get_all_providers()
        return jsonify(providers), 200
    except Exception as e:
        logger.error("Failed to load AI providers: %s", e)
        return jsonify({"error": str(e)}), 500


@ai_bp.route("/api/ai/configs", methods=["POST"])
@require_auth
def create_ai_config():
    """Create a new AI configuration."""
    try:
        data = request.get_json(force=True)
        if not data or not data.get("config_key"):
            return jsonify({"error": "config_key is required"}), 400
        config_id = ai_config_svc.create(data)
        config = ai_config_svc.get(config_id)
        return jsonify(config), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@ai_bp.route("/api/ai/configs", methods=["GET"])
@require_auth
def list_ai_configs():
    """List all AI configurations."""
    try:
        items = ai_config_svc.list_all()
        return jsonify(items), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@ai_bp.route("/api/ai/configs/<int:config_id>", methods=["GET"])
@require_auth
def get_ai_config(config_id):
    """Get a single AI configuration."""
    try:
        config = ai_config_svc.get(config_id)
        if not config:
            return jsonify({"error": "config not found"}), 404
        return jsonify(config), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@ai_bp.route("/api/ai/configs/<int:config_id>", methods=["PUT"])
@require_auth
def update_ai_config(config_id):
    """Update an AI configuration."""
    try:
        data = request.get_json(force=True)
        if not data:
            return jsonify({"error": "request body is required"}), 400
        existing = ai_config_svc.get(config_id)
        if not existing:
            return jsonify({"error": "config not found"}), 404
        ai_config_svc.update(config_id, data)
        updated = ai_config_svc.get(config_id)
        return jsonify(updated), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@ai_bp.route("/api/ai/configs/<int:config_id>", methods=["DELETE"])
@require_auth
def delete_ai_config(config_id):
    """Delete an AI configuration."""
    try:
        ok = ai_config_svc.delete(config_id)
        if not ok:
            return jsonify({"error": "config not found"}), 404
        return jsonify({"message": "deleted"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@ai_bp.route("/api/ai/configs/test", methods=["POST"])
@require_auth
def test_ai_config():
    """Test an AI configuration connection.

    Supports two modes:
    1. By config_id: test a saved configuration
    2. By raw params (provider, model, api_key, base_url): test without saving first
    """
    try:
        data = request.get_json(force=True)
        config_id = data.get("config_id")

        if config_id:
            result = ai_config_svc.test_connection(int(config_id))
        elif data.get("provider") and data.get("api_key"):
            # Direct test with form values — no need to save first
            result = ai_config_svc.test_connection_direct(
                provider=data["provider"],
                model=data.get("model", ""),
                api_key=data["api_key"],
                base_url=data.get("base_url", ""),
            )
        else:
            return jsonify({"error": "需要 config_id 或 provider+api_key"}), 400

        return jsonify(result), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ══════════════════════════════════════════════════════════════════════════
# Trends
# ══════════════════════════════════════════════════════════════════════════


@ai_bp.route("/api/ai/trends/scan", methods=["POST"])
@require_auth
def scan_trends():
    """Scan RSS feeds for new trends."""
    try:
        data = request.get_json(silent=True) or {}
        feed_urls = data.get("feed_urls", DEFAULT_RSS_FEEDS)
        new_ids = trend_svc.scan_rss(feed_urls)
        return jsonify({"new_trend_ids": new_ids, "count": len(new_ids)}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@ai_bp.route("/api/ai/trends", methods=["GET"])
@require_auth
def list_trends():
    """List trends with optional filters."""
    try:
        status = request.args.get("status")
        source = request.args.get("source")
        limit = request.args.get("limit", 50, type=int)
        items = trend_svc.list_all(status=status, source=source, limit=limit)
        return jsonify(items), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@ai_bp.route("/api/ai/trends/<int:trend_id>", methods=["GET"])
@require_auth
def get_trend(trend_id):
    """Get a single trend."""
    try:
        trend = trend_svc.get(trend_id)
        if not trend:
            return jsonify({"error": "trend not found"}), 404
        return jsonify(trend), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@ai_bp.route("/api/ai/trends/<int:trend_id>", methods=["DELETE"])
@require_auth
def delete_trend(trend_id):
    """Delete a trend."""
    try:
        ok = trend_svc.delete(trend_id)
        if not ok:
            return jsonify({"error": "trend not found"}), 404
        return jsonify({"message": "deleted"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ══════════════════════════════════════════════════════════════════════════
# Topic Suggestions
# ══════════════════════════════════════════════════════════════════════════


@ai_bp.route("/api/ai/topics/analyze", methods=["POST"])
@require_auth
def analyze_topics():
    """Analyze top-performing topics from historical data."""
    try:
        results = topic_svc.analyze_top_topics()
        created = []
        for r in results[:10]:  # top 10
            try:
                sid = topic_svc.create({
                    "topic": r.get("topic", ""),
                    "source_type": "analysis",
                    "score": r.get("avg_likes", 0),
                    "status": "pending",
                    "reasoning": f"基于数据分析: 平均浏览{r.get('avg_views', 0):.0f}, 平均点赞{r.get('avg_likes', 0):.0f}",
                })
                created.append(sid)
            except Exception as e:
                logger.warning("Failed to create topic suggestion: %s", e)
        return jsonify({"analyzed": len(results), "suggestions_created": len(created), "data": results}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@ai_bp.route("/api/ai/topics/suggestions", methods=["GET"])
@require_auth
def list_suggestions():
    """List topic suggestions with optional filters."""
    try:
        status = request.args.get("status")
        sort_by = request.args.get("sort_by", "score")
        limit = request.args.get("limit", 50, type=int)
        items = topic_svc.list_all(status=status, sort_by=sort_by, limit=limit)
        return jsonify(items), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@ai_bp.route("/api/ai/topics/suggestions/<int:suggestion_id>", methods=["GET"])
@require_auth
def get_suggestion(suggestion_id):
    """Get a single topic suggestion."""
    try:
        item = topic_svc.get(suggestion_id)
        if not item:
            return jsonify({"error": "suggestion not found"}), 404
        return jsonify(item), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@ai_bp.route("/api/ai/topics/suggestions/<int:suggestion_id>", methods=["PUT"])
@require_auth
def update_suggestion(suggestion_id):
    """Update a topic suggestion status."""
    try:
        data = request.get_json(force=True)
        if not data or not data.get("status"):
            return jsonify({"error": "status is required"}), 400
        existing = topic_svc.get(suggestion_id)
        if not existing:
            return jsonify({"error": "suggestion not found"}), 404
        topic_svc.update_status(suggestion_id, data["status"])
        updated = topic_svc.get(suggestion_id)
        return jsonify(updated), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@ai_bp.route("/api/ai/topics/suggestions/<int:suggestion_id>/generate", methods=["POST"])
@require_auth
def generate_from_suggestion(suggestion_id):
    """Generate content from a topic suggestion."""
    try:
        suggestion = topic_svc.get(suggestion_id)
        if not suggestion:
            return jsonify({"error": "suggestion not found"}), 404

        data = request.get_json(silent=True) or {}

        # Resolve AI config
        config_key = data.get("config_key", "default")
        config = ai_config_svc.get_by_key(config_key)
        if not config:
            return jsonify({"error": "No AI config found. Create one first."}), 400

        # Determine platform from suggestion or request
        platforms = suggestion.get("suggested_platforms", [])
        platform = data.get("platform") or (platforms[0] if platforms else "instagram")

        result = gen_svc.generate_content(
            ai_config=config,
            topic=suggestion.get("topic", ""),
            platform=platform,
            language=data.get("language", suggestion.get("language", "zh")),
            content_type=data.get("content_type",
                                  suggestion.get("suggested_content_type", "image_single")),
            style=data.get("style", ""),
            suggestion_id=suggestion_id,
        )

        # Mark suggestion as used
        if result.get("content_id"):
            topic_svc.mark_used(suggestion_id, result["content_id"])

        return jsonify(result), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ══════════════════════════════════════════════════════════════════════════
# Content / Variant Generation
# ══════════════════════════════════════════════════════════════════════════


@ai_bp.route("/api/ai/generate/content", methods=["POST"])
@require_auth
def ai_generate_content():
    """Generate content using AI."""
    try:
        data = request.get_json(force=True)
        # Resolve AI config
        config = ai_config_svc.get_by_key(data.get("config_key", "default"))
        if not config:
            return jsonify({"error": "No AI config found. Create one first."}), 400

        result = gen_svc.generate_content(
            ai_config=config,
            topic=data.get("topic", ""),
            platform=data.get("platform", "instagram"),
            language=data.get("language", "zh"),
            content_type=data.get("content_type", "image_single"),
            style=data.get("style", ""),
        )
        return jsonify(result), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@ai_bp.route("/api/ai/generate/variants", methods=["POST"])
@require_auth
def ai_generate_variants():
    """Generate platform variants for an existing content item."""
    try:
        data = request.get_json(force=True)
        content_id = data.get("content_id")
        if not content_id:
            return jsonify({"error": "content_id is required"}), 400

        target_platforms = data.get("target_platforms", [])
        if not target_platforms:
            return jsonify({"error": "target_platforms is required"}), 400

        config = ai_config_svc.get_by_key(data.get("config_key", "default"))
        if not config:
            return jsonify({"error": "No AI config found. Create one first."}), 400

        results = gen_svc.generate_variants(
            ai_config=config,
            content_id=content_id,
            target_platforms=target_platforms,
        )
        return jsonify(results), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@ai_bp.route("/api/ai/generate/tasks", methods=["GET"])
@require_auth
def list_generation_tasks():
    """List generation tasks with optional filters."""
    try:
        status = request.args.get("status")
        task_type = request.args.get("task_type")
        limit = request.args.get("limit", 50, type=int)
        items = gen_svc.list_tasks(status=status, task_type=task_type, limit=limit)
        return jsonify(items), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@ai_bp.route("/api/ai/generate/tasks/<int:task_id>", methods=["GET"])
@require_auth
def get_generation_task(task_id):
    """Get a single generation task."""
    try:
        item = gen_svc.get_task(task_id)
        if not item:
            return jsonify({"error": "task not found"}), 404
        return jsonify(item), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ══════════════════════════════════════════════════════════════════════════
# Generation Logs
# ══════════════════════════════════════════════════════════════════════════


@ai_bp.route("/api/ai/logs", methods=["GET"])
@require_auth
def list_generation_logs():
    """List generation logs with optional task_id filter."""
    try:
        task_id = request.args.get("task_id", type=int)
        limit = request.args.get("limit", 50, type=int)
        items = gen_svc.list_logs(task_id=task_id, limit=limit)
        return jsonify(items), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@ai_bp.route("/api/ai/logs/stats", methods=["GET"])
@require_auth
def generation_log_stats():
    """Get generation log statistics (tokens, cost, call counts)."""
    try:
        stats = gen_svc.get_log_stats()
        return jsonify(stats), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ══════════════════════════════════════════════════════════════════════════
# Pipelines
# ══════════════════════════════════════════════════════════════════════════


@ai_bp.route("/api/ai/pipelines", methods=["POST"])
@require_auth
def create_pipeline():
    """Create a new pipeline."""
    try:
        data = request.get_json(force=True)
        if not data or not data.get("name"):
            return jsonify({"error": "name is required"}), 400
        pid = pipeline_svc.create(data)
        pipeline = pipeline_svc.get(pid)
        return jsonify(pipeline), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@ai_bp.route("/api/ai/pipelines", methods=["GET"])
@require_auth
def list_pipelines():
    """List all pipelines."""
    try:
        items = pipeline_svc.list_all()
        return jsonify(items), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@ai_bp.route("/api/ai/pipelines/<int:pipeline_id>", methods=["GET"])
@require_auth
def get_pipeline(pipeline_id):
    """Get a single pipeline."""
    try:
        pipeline = pipeline_svc.get(pipeline_id)
        if not pipeline:
            return jsonify({"error": "pipeline not found"}), 404
        return jsonify(pipeline), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@ai_bp.route("/api/ai/pipelines/<int:pipeline_id>", methods=["PUT"])
@require_auth
def update_pipeline(pipeline_id):
    """Update a pipeline."""
    try:
        data = request.get_json(force=True)
        if not data:
            return jsonify({"error": "request body is required"}), 400
        existing = pipeline_svc.get(pipeline_id)
        if not existing:
            return jsonify({"error": "pipeline not found"}), 404
        pipeline_svc.update(pipeline_id, data)
        updated = pipeline_svc.get(pipeline_id)
        return jsonify(updated), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@ai_bp.route("/api/ai/pipelines/<int:pipeline_id>", methods=["DELETE"])
@require_auth
def delete_pipeline(pipeline_id):
    """Delete a pipeline."""
    try:
        ok = pipeline_svc.delete(pipeline_id)
        if not ok:
            return jsonify({"error": "pipeline not found"}), 404
        return jsonify({"message": "deleted"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@ai_bp.route("/api/ai/pipelines/<int:pipeline_id>/toggle", methods=["POST"])
@require_auth
def toggle_pipeline(pipeline_id):
    """Enable or disable a pipeline."""
    try:
        data = request.get_json(force=True)
        enabled = data.get("enabled")
        if enabled is None:
            return jsonify({"error": "enabled is required"}), 400
        existing = pipeline_svc.get(pipeline_id)
        if not existing:
            return jsonify({"error": "pipeline not found"}), 404
        pipeline_svc.toggle(pipeline_id, bool(enabled))
        updated = pipeline_svc.get(pipeline_id)
        return jsonify(updated), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@ai_bp.route("/api/ai/pipelines/<int:pipeline_id>/run", methods=["POST"])
@require_auth
def run_pipeline(pipeline_id):
    """Manually trigger a pipeline execution."""
    try:
        existing = pipeline_svc.get(pipeline_id)
        if not existing:
            return jsonify({"error": "pipeline not found"}), 404

        data = request.get_json(silent=True) or {}
        triggered_by = data.get("triggered_by", "manual")

        executor = AIPipelineExecutor(DB_PATH)
        result = executor.execute(pipeline_id, triggered_by=triggered_by)
        return jsonify(result), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@ai_bp.route("/api/ai/pipelines/<int:pipeline_id>/runs", methods=["GET"])
@require_auth
def list_pipeline_runs(pipeline_id):
    """List runs for a specific pipeline."""
    try:
        existing = pipeline_svc.get(pipeline_id)
        if not existing:
            return jsonify({"error": "pipeline not found"}), 404
        status = request.args.get("status")
        limit = request.args.get("limit", 20, type=int)
        items = run_svc.list_runs(pipeline_id=pipeline_id, status=status, limit=limit)
        return jsonify(items), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@ai_bp.route("/api/ai/pipeline-runs/<int:run_id>", methods=["GET"])
@require_auth
def get_pipeline_run(run_id):
    """Get a single pipeline run."""
    try:
        run = run_svc.get_run(run_id)
        if not run:
            return jsonify({"error": "pipeline run not found"}), 404
        return jsonify(run), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ══════════════════════════════════════════════════════════════════════════
# Dashboard
# ══════════════════════════════════════════════════════════════════════════


@ai_bp.route("/api/ai/dashboard", methods=["GET"])
@require_auth
def ai_dashboard():
    """Return AI module dashboard summary."""
    try:
        from models.database import get_connection
        conn = get_connection(DB_PATH)
        try:
            active_trends_count = conn.execute(
                "SELECT COUNT(*) AS cnt FROM trends WHERE trend_status = 'active'"
            ).fetchone()["cnt"]
            pending_suggestions_count = conn.execute(
                "SELECT COUNT(*) AS cnt FROM topic_suggestions WHERE status = 'pending'"
            ).fetchone()["cnt"]
            running_pipelines_count = conn.execute(
                "SELECT COUNT(*) AS cnt FROM pipeline_runs WHERE status = 'running'"
            ).fetchone()["cnt"]
        finally:
            conn.close()

        log_stats = gen_svc.get_log_stats()
        recent_tasks = gen_svc.list_tasks(limit=10)

        return jsonify({
            "today_generations": log_stats.get("today_calls", 0),
            "today_tokens": log_stats.get("today_tokens", 0),
            "active_trends": active_trends_count,
            "pending_suggestions": pending_suggestions_count,
            "running_pipelines": running_pipelines_count,
            "recent_tasks": recent_tasks,
            "log_stats": log_stats,
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
