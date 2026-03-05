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
import sqlite3

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
        logger.exception("Failed to load AI providers")
        return jsonify({"error": "服务器内部错误，请稍后重试"}), 500


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
    except sqlite3.IntegrityError:
        return jsonify({"error": f"config_key '{data.get('config_key')}' already exists"}), 409
    except Exception as e:
        logger.exception("Unexpected error in ai API")
        return jsonify({"error": "服务器内部错误，请稍后重试"}), 500


@ai_bp.route("/api/ai/configs", methods=["GET"])
@require_auth
def list_ai_configs():
    """List all AI configurations."""
    try:
        items = ai_config_svc.list_all()
        return jsonify(items), 200
    except Exception as e:
        logger.exception("Unexpected error in ai API")
        return jsonify({"error": "服务器内部错误，请稍后重试"}), 500


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
        logger.exception("Unexpected error in ai API")
        return jsonify({"error": "服务器内部错误，请稍后重试"}), 500


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
        logger.exception("Unexpected error in ai API")
        return jsonify({"error": "服务器内部错误，请稍后重试"}), 500


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
        logger.exception("Unexpected error in ai API")
        return jsonify({"error": "服务器内部错误，请稍后重试"}), 500


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
        logger.exception("Unexpected error in ai API")
        return jsonify({"error": "服务器内部错误，请稍后重试"}), 500


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
        logger.exception("Unexpected error in ai API")
        return jsonify({"error": "服务器内部错误，请稍后重试"}), 500


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
        logger.exception("Unexpected error in ai API")
        return jsonify({"error": "服务器内部错误，请稍后重试"}), 500


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
        logger.exception("Unexpected error in ai API")
        return jsonify({"error": "服务器内部错误，请稍后重试"}), 500


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
        logger.exception("Unexpected error in ai API")
        return jsonify({"error": "服务器内部错误，请稍后重试"}), 500


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
        logger.exception("Unexpected error in ai API")
        return jsonify({"error": "服务器内部错误，请稍后重试"}), 500


@ai_bp.route("/api/ai/topics/stats", methods=["GET"])
@require_auth
def topic_suggestion_stats():
    """Return topic suggestion counts grouped by status."""
    try:
        stats = topic_svc.get_stats()
        return jsonify(stats), 200
    except Exception as e:
        logger.exception("Unexpected error in ai API")
        return jsonify({"error": "服务器内部错误，请稍后重试"}), 500


@ai_bp.route("/api/ai/topics/suggestions/seed", methods=["POST"])
@require_auth
def seed_topic_suggestions():
    """Create a batch of high-quality demo topic suggestions for Chinese social media."""
    try:
        seed_data = [
            {
                "topic": "春季穿搭灵感分享",
                "description": "分享春季时尚穿搭技巧，包括色彩搭配、单品推荐和不同场景的穿搭方案",
                "keywords": ["春季穿搭", "时尚搭配", "OOTD", "春装推荐", "色彩搭配"],
                "suggested_tags": ["穿搭", "时尚", "春季", "OOTD", "搭配灵感"],
                "suggested_platforms": ["xiaohongshu", "douyin", "weibo"],
                "suggested_content_type": "image_carousel",
                "score": 88,
                "source_type": "manual",
                "reasoning": "春季是换季高峰，穿搭类内容搜索量大幅上升，适合图文种草",
            },
            {
                "topic": "健康早餐一周食谱",
                "description": "为上班族和学生设计的一周七天健康早餐计划，简单快手又营养均衡",
                "keywords": ["健康早餐", "一周食谱", "快手早餐", "营养搭配", "减脂餐"],
                "suggested_tags": ["早餐", "食谱", "健康饮食", "减脂", "快手菜"],
                "suggested_platforms": ["xiaohongshu", "douyin", "bilibili"],
                "suggested_content_type": "video",
                "score": 92,
                "source_type": "manual",
                "reasoning": "健康饮食持续热门，早餐类内容互动率高，适合视频展示制作过程",
            },
            {
                "topic": "居家收纳神器推荐",
                "description": "盘点高性价比的居家收纳好物，从厨房到衣柜的全屋收纳解决方案",
                "keywords": ["收纳", "居家好物", "整理收纳", "收纳神器", "家居"],
                "suggested_tags": ["收纳", "居家", "好物推荐", "家居整理", "断舍离"],
                "suggested_platforms": ["xiaohongshu", "douyin", "taobao"],
                "suggested_content_type": "image_carousel",
                "score": 85,
                "source_type": "manual",
                "reasoning": "居家收纳内容种草属性强，转化率高，适合图文对比展示",
            },
            {
                "topic": "短视频拍摄技巧教学",
                "description": "从手机摄影到剪辑的全流程短视频制作教程，零基础也能拍出高质量内容",
                "keywords": ["短视频", "拍摄技巧", "手机摄影", "视频剪辑", "运镜"],
                "suggested_tags": ["拍摄教程", "短视频", "摄影技巧", "剪辑", "创作者"],
                "suggested_platforms": ["douyin", "bilibili", "kuaishou"],
                "suggested_content_type": "video",
                "score": 90,
                "source_type": "manual",
                "reasoning": "创作者生态持续扩大，拍摄教学类内容收藏率极高，长尾流量好",
            },
            {
                "topic": "热门美妆新品测评",
                "description": "测评当季热门美妆护肤新品，包括真实使用感受、成分分析和性价比对比",
                "keywords": ["美妆测评", "新品", "护肤", "化妆品", "成分党"],
                "suggested_tags": ["美妆", "测评", "护肤", "新品", "好物分享"],
                "suggested_platforms": ["xiaohongshu", "douyin", "bilibili"],
                "suggested_content_type": "video",
                "score": 91,
                "source_type": "manual",
                "reasoning": "美妆测评是小红书和抖音核心品类，商业变现潜力大",
            },
            {
                "topic": "旅行Vlog拍摄指南",
                "description": "旅行Vlog从策划到发布的完整指南，包括设备选择、叙事结构和后期制作",
                "keywords": ["旅行Vlog", "旅行攻略", "Vlog教程", "旅拍", "自由行"],
                "suggested_tags": ["旅行", "Vlog", "旅拍", "攻略", "自由行"],
                "suggested_platforms": ["bilibili", "douyin", "xiaohongshu"],
                "suggested_content_type": "video",
                "score": 87,
                "source_type": "manual",
                "reasoning": "旅行内容四季常青，Vlog形式粉丝粘性高，适合长期系列化运营",
            },
            {
                "topic": "数码产品选购攻略",
                "description": "帮助消费者选择合适的数码产品，涵盖手机、耳机、平板等热门品类的对比评测",
                "keywords": ["数码", "选购攻略", "手机推荐", "数码测评", "性价比"],
                "suggested_tags": ["数码", "测评", "科技", "选购指南", "性价比"],
                "suggested_platforms": ["bilibili", "douyin", "zhihu"],
                "suggested_content_type": "video",
                "score": 83,
                "source_type": "manual",
                "reasoning": "数码品类用户决策周期长，攻略型内容搜索流量大，广告价值高",
            },
            {
                "topic": "副业赚钱经验分享",
                "description": "分享真实可行的副业赚钱经验，包括自媒体、电商、技能变现等方向",
                "keywords": ["副业", "赚钱", "自媒体", "兼职", "技能变现"],
                "suggested_tags": ["副业", "赚钱", "自媒体", "经验分享", "个人成长"],
                "suggested_platforms": ["xiaohongshu", "douyin", "bilibili", "zhihu"],
                "suggested_content_type": "image_carousel",
                "score": 95,
                "source_type": "manual",
                "reasoning": "副业和赚钱话题永远有流量，用户互动意愿强，容易引发讨论和收藏",
            },
            {
                "topic": "职场沟通话术大全",
                "description": "整理职场中常见的沟通场景和高情商话术，帮助职场新人提升沟通能力",
                "keywords": ["职场", "沟通技巧", "话术", "职场新人", "高情商"],
                "suggested_tags": ["职场", "沟通", "话术", "职场成长", "干货"],
                "suggested_platforms": ["xiaohongshu", "douyin", "zhihu"],
                "suggested_content_type": "image_carousel",
                "score": 78,
                "source_type": "manual",
                "reasoning": "职场内容受众广泛，话术类内容收藏率高，适合图文形式呈现",
            },
            {
                "topic": "宠物日常记录与养护",
                "description": "记录宠物有趣日常，分享科学养宠知识，涵盖喂养、训练、健康护理",
                "keywords": ["宠物", "猫咪", "狗狗", "养宠", "萌宠日常"],
                "suggested_tags": ["宠物", "萌宠", "养猫", "养狗", "日常"],
                "suggested_platforms": ["douyin", "xiaohongshu", "bilibili"],
                "suggested_content_type": "video",
                "score": 86,
                "source_type": "manual",
                "reasoning": "萌宠内容完播率高、互动性强，容易获得平台推荐流量",
            },
        ]

        created_ids = []
        for item in seed_data:
            try:
                sid = topic_svc.create(item)
                created_ids.append(sid)
            except Exception as e:
                logger.warning("Failed to create seed topic: %s", e)

        return jsonify({
            "message": f"成功创建 {len(created_ids)} 条示例选题",
            "created_ids": created_ids,
            "count": len(created_ids),
        }), 201
    except Exception as e:
        logger.exception("Unexpected error in ai API")
        return jsonify({"error": "服务器内部错误，请稍后重试"}), 500


@ai_bp.route("/api/ai/topics/suggestions", methods=["POST"])
@require_auth
def create_suggestion():
    """Manually create a topic suggestion."""
    try:
        data = request.get_json(force=True)
        if not data or not data.get("topic"):
            return jsonify({"error": "topic is required"}), 400

        allowed_content_types = {"image_single", "image_carousel", "video"}
        content_type = data.get("suggested_content_type", "image_single")
        if content_type not in allowed_content_types:
            return jsonify({"error": f"suggested_content_type must be one of {sorted(allowed_content_types)}"}), 400

        score = data.get("score", 0)
        if not isinstance(score, (int, float)) or score < 0 or score > 100:
            return jsonify({"error": "score must be a number between 0 and 100"}), 400

        suggestion_data = {
            "topic": data["topic"],
            "description": data.get("description", ""),
            "keywords": data.get("keywords", []),
            "suggested_tags": data.get("suggested_tags", []),
            "suggested_platforms": data.get("suggested_platforms", []),
            "suggested_content_type": content_type,
            "score": score,
            "source_type": data.get("source_type", "manual"),
            "status": "pending",
        }

        sid = topic_svc.create(suggestion_data)
        created = topic_svc.get(sid)
        return jsonify(created), 201
    except Exception as e:
        logger.exception("Unexpected error in ai API")
        return jsonify({"error": "服务器内部错误，请稍后重试"}), 500


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
        logger.exception("Unexpected error in ai API")
        return jsonify({"error": "服务器内部错误，请稍后重试"}), 500


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
        logger.exception("Unexpected error in ai API")
        return jsonify({"error": "服务器内部错误，请稍后重试"}), 500


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
        logger.exception("Unexpected error in ai API")
        return jsonify({"error": "服务器内部错误，请稍后重试"}), 500


@ai_bp.route("/api/ai/topics/suggestions/<int:suggestion_id>", methods=["DELETE"])
@require_auth
def delete_suggestion(suggestion_id):
    """Delete a topic suggestion."""
    try:
        ok = topic_svc.delete(suggestion_id)
        if not ok:
            return jsonify({"error": "suggestion not found"}), 404
        return jsonify({"message": "deleted"}), 200
    except Exception as e:
        logger.exception("Unexpected error in ai API")
        return jsonify({"error": "服务器内部错误，请稍后重试"}), 500


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
        logger.exception("Unexpected error in ai API")
        return jsonify({"error": "服务器内部错误，请稍后重试"}), 500


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
        logger.exception("Unexpected error in ai API")
        return jsonify({"error": "服务器内部错误，请稍后重试"}), 500


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
        logger.exception("Unexpected error in ai API")
        return jsonify({"error": "服务器内部错误，请稍后重试"}), 500


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
        logger.exception("Unexpected error in ai API")
        return jsonify({"error": "服务器内部错误，请稍后重试"}), 500


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
        logger.exception("Unexpected error in ai API")
        return jsonify({"error": "服务器内部错误，请稍后重试"}), 500


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
        logger.exception("Unexpected error in ai API")
        return jsonify({"error": "服务器内部错误，请稍后重试"}), 500


@ai_bp.route("/api/ai/logs/stats", methods=["GET"])
@require_auth
def generation_log_stats():
    """Get generation log statistics (tokens, cost, call counts)."""
    try:
        stats = gen_svc.get_log_stats()
        return jsonify(stats), 200
    except Exception as e:
        logger.exception("Unexpected error in ai API")
        return jsonify({"error": "服务器内部错误，请稍后重试"}), 500


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
        logger.exception("Unexpected error in ai API")
        return jsonify({"error": "服务器内部错误，请稍后重试"}), 500


@ai_bp.route("/api/ai/pipelines", methods=["GET"])
@require_auth
def list_pipelines():
    """List all pipelines."""
    try:
        items = pipeline_svc.list_all()
        return jsonify(items), 200
    except Exception as e:
        logger.exception("Unexpected error in ai API")
        return jsonify({"error": "服务器内部错误，请稍后重试"}), 500


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
        logger.exception("Unexpected error in ai API")
        return jsonify({"error": "服务器内部错误，请稍后重试"}), 500


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
        logger.exception("Unexpected error in ai API")
        return jsonify({"error": "服务器内部错误，请稍后重试"}), 500


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
        logger.exception("Unexpected error in ai API")
        return jsonify({"error": "服务器内部错误，请稍后重试"}), 500


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
        logger.exception("Unexpected error in ai API")
        return jsonify({"error": "服务器内部错误，请稍后重试"}), 500


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
        logger.exception("Unexpected error in ai API")
        return jsonify({"error": "服务器内部错误，请稍后重试"}), 500


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
        logger.exception("Unexpected error in ai API")
        return jsonify({"error": "服务器内部错误，请稍后重试"}), 500


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
        logger.exception("Unexpected error in ai API")
        return jsonify({"error": "服务器内部错误，请稍后重试"}), 500


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
        logger.exception("Unexpected error in ai dashboard API")
        return jsonify({"error": "服务器内部错误，请稍后重试"}), 500


# ══════════════════════════════════════════════════════════════════════════
# Card Generation (图文卡片)
# ══════════════════════════════════════════════════════════════════════════


@ai_bp.route("/api/ai/cards/templates", methods=["GET"])
@require_auth
def list_card_templates():
    """Return available card templates with default colors."""
    from services.card_render_service import CardRenderService, PLATFORM_SIZES
    svc = CardRenderService()
    return jsonify({
        "templates": svc.list_templates(),
        "platform_sizes": {k: {"width": v[0], "height": v[1]} for k, v in PLATFORM_SIZES.items()},
    }), 200


@ai_bp.route("/api/ai/generate/cards", methods=["POST"])
@require_auth
def ai_generate_cards():
    """Generate AI content with structured slides, render to card images.

    Request: {config_key, topic, platform, language, content_type,
              style, slide_count, template, color_scheme}
    Response: {content_id, variant_id, slides, asset_ids, preview_urls, tokens}
    """
    try:
        data = request.get_json(force=True)
        topic = (data.get("topic") or "").strip()
        if not topic:
            return jsonify({"error": "topic 不能为空"}), 400

        config_key = data.get("config_key", "default")
        platform = data.get("platform", "xiaohongshu")
        language = data.get("language", "zh")
        content_type = data.get("content_type", "image_carousel")
        style = data.get("style", "")
        slide_count = min(max(int(data.get("slide_count", 6)), 3), 9)
        template = data.get("template", "minimal")
        color_scheme = data.get("color_scheme")

        # Resolve AI config
        config = ai_config_svc.get_by_key(config_key)
        if not config:
            configs = ai_config_svc.list_all()
            if not configs:
                return jsonify({"error": "请先配置 AI 提供商"}), 400
            config = configs[0]

        result = gen_svc.generate_card_content(
            ai_config=config,
            topic=topic,
            platform=platform,
            language=language,
            content_type=content_type,
            style=style,
            slide_count=slide_count,
            template=template,
            color_scheme=color_scheme,
        )

        return jsonify(result), 201

    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.exception("Card generation failed")
        return jsonify({"error": f"生成失败: {str(e)}"}), 500


@ai_bp.route("/api/ai/cards/rerender", methods=["POST"])
@require_auth
def rerender_cards():
    """Re-render cards with different template/colors (no AI call).

    Request: {variant_id, slides, template, platform, color_scheme}
    Response: {asset_ids, preview_urls}
    """
    try:
        data = request.get_json(force=True)
        variant_id = data.get("variant_id")
        slides = data.get("slides")

        if not variant_id or not slides:
            return jsonify({"error": "variant_id 和 slides 不能为空"}), 400

        template = data.get("template", "minimal")
        platform = data.get("platform", "xiaohongshu")
        color_scheme = data.get("color_scheme")

        from services.card_render_service import CardRenderService
        render_svc = CardRenderService()
        try:
            asset_ids = render_svc.rerender_and_replace(
                variant_id, slides, template, platform, color_scheme)
        finally:
            render_svc.close()

        # Build preview URLs
        from services.content_service import AssetService
        asset_svc = AssetService(DB_PATH)
        preview_urls = []
        for aid in asset_ids:
            asset = asset_svc.get(aid)
            if asset:
                preview_urls.append(f"/api/uploads/{asset['storage_url']}")

        return jsonify({
            "asset_ids": asset_ids,
            "preview_urls": preview_urls,
        }), 200

    except Exception as e:
        logger.exception("Card rerender failed")
        return jsonify({"error": f"重新渲染失败: {str(e)}"}), 500
