"""API endpoints for the auto-reply module."""

import json
import logging
from flask import Blueprint, request, jsonify, g

from api.auth import require_auth
from config import DB_PATH
from services.reply_service import (
    ReplyCampaignService, ReplyTaskService, ReplyLogService,
)
from services.platform_repliers.registry import get_supported_platforms

logger = logging.getLogger(__name__)

replies_bp = Blueprint("replies", __name__)


# ── Campaign CRUD ──────────────────────────────────────────────


@replies_bp.route("/api/reply-campaigns", methods=["POST"])
@require_auth
def create_campaign():
    """Create a new reply campaign."""
    try:
        data = request.get_json(force=True)

        required = ["name", "platform", "account_id"]
        for field in required:
            if not data.get(field):
                return jsonify({"error": f"缺少必填字段: {field}"}), 400

        if data["platform"] not in get_supported_platforms():
            return jsonify({"error": f"不支持的平台: {data['platform']}"}), 400

        svc = ReplyCampaignService(DB_PATH)
        campaign_id = svc.create(data)
        campaign = svc.get(campaign_id)
        return jsonify({"id": campaign_id, "campaign": campaign}), 201
    except Exception as e:
        logger.exception("创建回复计划失败")
        return jsonify({"error": f"创建失败: {str(e)}"}), 500


@replies_bp.route("/api/reply-campaigns", methods=["GET"])
@require_auth
def list_campaigns():
    """List reply campaigns with optional filters."""
    try:
        status = request.args.get("status")
        platform = request.args.get("platform")
        account_id = request.args.get("account_id", type=int)
        limit = request.args.get("limit", 100, type=int)
        offset = request.args.get("offset", 0, type=int)

        svc = ReplyCampaignService(DB_PATH)
        campaigns = svc.list_all(
            status=status, platform=platform,
            account_id=account_id, limit=limit, offset=offset
        )
        return jsonify({"campaigns": campaigns, "total": len(campaigns)})
    except Exception as e:
        logger.exception("获取回复计划列表失败")
        return jsonify({"error": str(e)}), 500


@replies_bp.route("/api/reply-campaigns/<int:campaign_id>", methods=["GET"])
@require_auth
def get_campaign(campaign_id):
    """Get a single campaign."""
    try:
        svc = ReplyCampaignService(DB_PATH)
        campaign = svc.get(campaign_id)
        if not campaign:
            return jsonify({"error": "计划不存在"}), 404
        return jsonify(campaign)
    except Exception as e:
        logger.exception("获取回复计划失败")
        return jsonify({"error": str(e)}), 500


@replies_bp.route("/api/reply-campaigns/<int:campaign_id>", methods=["PUT"])
@require_auth
def update_campaign(campaign_id):
    """Update a campaign."""
    try:
        data = request.get_json(force=True)
        svc = ReplyCampaignService(DB_PATH)

        if not svc.get(campaign_id):
            return jsonify({"error": "计划不存在"}), 404

        svc.update(campaign_id, data)
        campaign = svc.get(campaign_id)
        return jsonify(campaign)
    except Exception as e:
        logger.exception("更新回复计划失败")
        return jsonify({"error": str(e)}), 500


@replies_bp.route("/api/reply-campaigns/<int:campaign_id>", methods=["DELETE"])
@require_auth
def delete_campaign(campaign_id):
    """Delete a campaign and its tasks."""
    try:
        svc = ReplyCampaignService(DB_PATH)
        if not svc.get(campaign_id):
            return jsonify({"error": "计划不存在"}), 404
        svc.delete(campaign_id)
        return jsonify({"success": True, "message": "已删除"})
    except Exception as e:
        logger.exception("删除回复计划失败")
        return jsonify({"error": str(e)}), 500


# ── Campaign Actions ───────────────────────────────────────────


@replies_bp.route("/api/reply-campaigns/<int:campaign_id>/start", methods=["POST"])
@require_auth
def start_campaign(campaign_id):
    """Start a campaign (transition to active)."""
    try:
        svc = ReplyCampaignService(DB_PATH)
        campaign = svc.get(campaign_id)
        if not campaign:
            return jsonify({"error": "计划不存在"}), 404

        from datetime import datetime
        svc.update_next_run(campaign_id, datetime.now().isoformat())

        if not svc.transition(campaign_id, "active"):
            return jsonify({"error": f"无法从状态 '{campaign['status']}' 启动"}), 400

        return jsonify({"success": True, "message": "计划已启动"})
    except Exception as e:
        logger.exception("启动回复计划失败")
        return jsonify({"error": str(e)}), 500


@replies_bp.route("/api/reply-campaigns/<int:campaign_id>/pause", methods=["POST"])
@require_auth
def pause_campaign(campaign_id):
    """Pause a campaign."""
    try:
        svc = ReplyCampaignService(DB_PATH)
        campaign = svc.get(campaign_id)
        if not campaign:
            return jsonify({"error": "计划不存在"}), 404

        if not svc.transition(campaign_id, "paused"):
            return jsonify({"error": f"无法从状态 '{campaign['status']}' 暂停"}), 400

        return jsonify({"success": True, "message": "计划已暂停"})
    except Exception as e:
        logger.exception("暂停回复计划失败")
        return jsonify({"error": str(e)}), 500


@replies_bp.route("/api/reply-campaigns/<int:campaign_id>/resume", methods=["POST"])
@require_auth
def resume_campaign(campaign_id):
    """Resume a paused campaign."""
    try:
        svc = ReplyCampaignService(DB_PATH)
        campaign = svc.get(campaign_id)
        if not campaign:
            return jsonify({"error": "计划不存在"}), 404

        from datetime import datetime
        svc.update_next_run(campaign_id, datetime.now().isoformat())

        if not svc.transition(campaign_id, "active"):
            return jsonify({"error": f"无法从状态 '{campaign['status']}' 恢复"}), 400

        return jsonify({"success": True, "message": "计划已恢复"})
    except Exception as e:
        logger.exception("恢复回复计划失败")
        return jsonify({"error": str(e)}), 500


# ── Reply Task CRUD ────────────────────────────────────────────


@replies_bp.route("/api/reply-tasks", methods=["POST"])
@require_auth
def create_reply_task():
    """Create a manual reply task (URL input)."""
    try:
        data = request.get_json(force=True)

        required = ["account_id", "platform", "post_url"]
        for field in required:
            if not data.get(field):
                return jsonify({"error": f"缺少必填字段: {field}"}), 400

        svc = ReplyTaskService(DB_PATH)

        # Check duplicate
        if svc.check_duplicate(data["account_id"], data["post_url"]):
            return jsonify({"error": "该账号已对此帖子创建过回复任务"}), 409

        # If reply content provided, set to ready; otherwise pending (needs generation)
        if data.get("reply_content"):
            data.setdefault("state", "ready")
        else:
            data.setdefault("state", "pending")

        task_id = svc.create(data)
        task = svc.get(task_id)
        return jsonify({"id": task_id, "task": task}), 201
    except Exception as e:
        logger.exception("创建回复任务失败")
        return jsonify({"error": f"创建失败: {str(e)}"}), 500


@replies_bp.route("/api/reply-tasks", methods=["GET"])
@require_auth
def list_reply_tasks():
    """List reply tasks with optional filters."""
    try:
        state = request.args.get("state")
        campaign_id = request.args.get("campaign_id", type=int)
        account_id = request.args.get("account_id", type=int)
        platform = request.args.get("platform")
        limit = request.args.get("limit", 100, type=int)
        offset = request.args.get("offset", 0, type=int)

        svc = ReplyTaskService(DB_PATH)
        tasks = svc.list_all(
            state=state, campaign_id=campaign_id,
            account_id=account_id, platform=platform,
            limit=limit, offset=offset
        )
        return jsonify({"tasks": tasks, "total": len(tasks)})
    except Exception as e:
        logger.exception("获取回复任务列表失败")
        return jsonify({"error": str(e)}), 500


@replies_bp.route("/api/reply-tasks/<int:task_id>", methods=["GET"])
@require_auth
def get_reply_task(task_id):
    """Get a single task with logs."""
    try:
        task_svc = ReplyTaskService(DB_PATH)
        task = task_svc.get(task_id)
        if not task:
            return jsonify({"error": "任务不存在"}), 404

        log_svc = ReplyLogService(DB_PATH)
        logs = log_svc.list_by_task(task_id)
        task["logs"] = logs

        return jsonify(task)
    except Exception as e:
        logger.exception("获取回复任务失败")
        return jsonify({"error": str(e)}), 500


@replies_bp.route("/api/reply-tasks/<int:task_id>/retry", methods=["POST"])
@require_auth
def retry_reply_task(task_id):
    """Retry a failed task."""
    try:
        svc = ReplyTaskService(DB_PATH)
        task = svc.get(task_id)
        if not task:
            return jsonify({"error": "任务不存在"}), 404

        if task["state"] != "failed":
            return jsonify({"error": "只能重试失败的任务"}), 400

        if not svc.transition(task_id, "pending"):
            return jsonify({"error": "状态转换失败"}), 400

        # If has reply content, set to ready directly
        if task.get("reply_content"):
            svc.transition(task_id, "ready")

        return jsonify({"success": True, "message": "任务已重新排队"})
    except Exception as e:
        logger.exception("重试回复任务失败")
        return jsonify({"error": str(e)}), 500


@replies_bp.route("/api/reply-tasks/<int:task_id>/cancel", methods=["POST"])
@require_auth
def cancel_reply_task(task_id):
    """Cancel a pending/ready task."""
    try:
        svc = ReplyTaskService(DB_PATH)
        task = svc.get(task_id)
        if not task:
            return jsonify({"error": "任务不存在"}), 404

        if not svc.transition(task_id, "cancelled"):
            return jsonify({"error": f"无法取消状态为 '{task['state']}' 的任务"}), 400

        return jsonify({"success": True, "message": "任务已取消"})
    except Exception as e:
        logger.exception("取消回复任务失败")
        return jsonify({"error": str(e)}), 500


# ── Batch Operations ───────────────────────────────────────────


@replies_bp.route("/api/reply-tasks/batch", methods=["POST"])
@require_auth
def batch_create_tasks():
    """Create multiple reply tasks from a list of URLs."""
    try:
        data = request.get_json(force=True)
        account_id = data.get("account_id")
        platform = data.get("platform")
        post_urls = data.get("post_urls", [])

        if not account_id or not platform:
            return jsonify({"error": "缺少 account_id 或 platform"}), 400
        if not post_urls:
            return jsonify({"error": "缺少 post_urls 列表"}), 400

        svc = ReplyTaskService(DB_PATH)
        tasks = []
        for url in post_urls:
            if svc.check_duplicate(account_id, url):
                continue
            tasks.append({
                "account_id": account_id,
                "platform": platform,
                "post_url": url,
                "state": "pending",
                "reply_content": data.get("reply_content", ""),
            })

        if not tasks:
            return jsonify({"error": "所有URL已存在回复任务"}), 409

        task_ids = svc.batch_create(tasks)
        return jsonify({"created": len(task_ids), "task_ids": task_ids}), 201
    except Exception as e:
        logger.exception("批量创建回复任务失败")
        return jsonify({"error": str(e)}), 500


# ── Preview ────────────────────────────────────────────────────


@replies_bp.route("/api/reply-preview", methods=["POST"])
@require_auth
def preview_reply():
    """Generate AI reply preview without executing."""
    try:
        data = request.get_json(force=True)
        post_content = data.get("post_content", "")
        post_title = data.get("post_title", "")
        post_author = data.get("post_author", "")
        platform = data.get("platform", "")
        tone = data.get("tone", "friendly")
        language = data.get("language", "zh")
        max_length = data.get("max_length", 200)
        custom_instructions = data.get("custom_instructions", "")
        config_key = data.get("config_key", "default")

        if not post_content and not post_title:
            return jsonify({"error": "请提供帖子内容或标题"}), 400

        # Build a fake post_info and campaign for the executor's generate method
        from services.platform_repliers.base import PostInfo
        post_info = PostInfo(
            url="",
            author=post_author,
            title=post_title,
            content=post_content,
            likes=data.get("post_likes", 0),
            comments=data.get("post_comments", 0),
        )

        fake_campaign = {
            "platform": platform,
            "reply_tone": tone,
            "reply_language": language,
            "reply_max_length": max_length,
            "custom_instructions": custom_instructions,
            "ai_config_key": config_key,
        }

        from services.reply_executor import ReplyExecutor
        executor = ReplyExecutor(db_path=DB_PATH)
        reply_text, alternatives_json, tokens = executor._generate_reply(post_info, fake_campaign)

        alternatives = []
        try:
            alternatives = json.loads(alternatives_json)
        except Exception:
            if reply_text:
                alternatives = [reply_text]

        return jsonify({
            "reply": reply_text,
            "alternatives": alternatives,
            "tokens_used": tokens,
        })
    except Exception as e:
        logger.exception("生成回复预览失败")
        return jsonify({"error": f"预览生成失败: {str(e)}"}), 500


# ── Logs ───────────────────────────────────────────────────────


@replies_bp.route("/api/reply-tasks/<int:task_id>/logs", methods=["GET"])
@require_auth
def get_task_logs(task_id):
    """Get execution logs for a task."""
    try:
        svc = ReplyLogService(DB_PATH)
        logs = svc.list_by_task(task_id)
        return jsonify({"logs": logs})
    except Exception as e:
        logger.exception("获取任务日志失败")
        return jsonify({"error": str(e)}), 500


# ── Statistics ─────────────────────────────────────────────────


@replies_bp.route("/api/reply-stats", methods=["GET"])
@require_auth
def get_reply_stats():
    """Get global reply statistics."""
    try:
        task_svc = ReplyTaskService(DB_PATH)
        campaign_svc = ReplyCampaignService(DB_PATH)

        stats = task_svc.get_stats()

        # Campaign stats
        all_campaigns = campaign_svc.list_all(limit=1000)
        active_campaigns = sum(1 for c in all_campaigns if c.get("status") == "active")

        # Today's replies
        from models.database import get_connection
        from datetime import datetime
        conn = get_connection(DB_PATH)
        try:
            today_start = datetime.now().replace(hour=0, minute=0, second=0).isoformat()
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM reply_tasks WHERE state = 'success' AND updated_at >= ?",
                (today_start,)
            ).fetchone()
            today_replies = row["cnt"] if row else 0
        finally:
            conn.close()

        stats["active_campaigns"] = active_campaigns
        stats["total_campaigns"] = len(all_campaigns)
        stats["today_replies"] = today_replies

        # Success rate
        total = stats.get("total", 0)
        success = stats.get("success", 0)
        stats["success_rate"] = round(success / total * 100, 1) if total > 0 else 0

        return jsonify(stats)
    except Exception as e:
        logger.exception("获取回复统计失败")
        return jsonify({"error": str(e)}), 500
