"""
AIPipelineExecutor -- orchestrates the 7 stages of an automated content pipeline.

Stages (in order):
    1. trend_scan      - Scan RSS feeds for trending topics
    2. topic_select    - Select / generate content topics from trends
    3. content_gen     - Generate content for each selected topic
    4. variant_gen     - Create platform-specific variants
    5. card_render     - Render card images for variants
    6. auto_review     - Optionally auto-approve generated content
    7. job_dispatch    - Create distribution jobs for target accounts
"""

import json
import logging
from datetime import datetime
from typing import List, Optional

from config import DB_PATH, DEFAULT_RSS_FEEDS
from models.database import get_connection
from services.pipeline_service import PipelineService, PipelineRunService
from services.trend_service import TrendService
from services.topic_suggestion_service import TopicSuggestionService
from services.ai_generation_service import AIGenerationService
from services.ai_config_service import AIConfigService
from services.content_service import ContentService
from services.job_service import JobService

logger = logging.getLogger(__name__)


def _resolve_api_key(raw_key: str) -> str:
    """Resolve API key -- try to decrypt, fall back to plaintext.

    The ai_configs.api_key_encrypted field may contain either an encrypted
    value or a plaintext API key. This helper attempts decryption first;
    if that fails it returns the raw value unchanged.
    """
    if not raw_key:
        return ""
    try:
        from config import CREDENTIAL_ENCRYPTION_KEY
        from services.crypto_service import CryptoService
        crypto = CryptoService(CREDENTIAL_ENCRYPTION_KEY)
        return crypto.decrypt(raw_key)
    except Exception:
        return raw_key  # Already plaintext


def _now() -> str:
    return datetime.now().isoformat()


class AIPipelineExecutor:
    """Automated pipeline executor -- orchestrates 7 stages."""

    # Canonical stage order
    ALL_STAGES = [
        "trend_scan",
        "topic_select",
        "content_gen",
        "variant_gen",
        "card_render",
        "auto_review",
        "job_dispatch",
    ]

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.pipeline_svc = PipelineService(db_path)
        self.run_svc = PipelineRunService(db_path)
        self.trend_svc = TrendService(db_path)
        self.topic_svc = TopicSuggestionService(db_path)
        self.gen_svc = AIGenerationService(db_path)
        self.ai_config_svc = AIConfigService(db_path)
        self.content_svc = ContentService(db_path)
        self.job_svc = JobService(db_path)

    # ── public entry point ──────────────────────────────────────────────

    def execute(self, pipeline_id: int, triggered_by: str = "manual") -> dict:
        """Execute a complete pipeline and return run statistics."""

        # 1. Read pipeline configuration
        pipeline = self.pipeline_svc.get(pipeline_id)
        if not pipeline:
            raise ValueError(f"Pipeline {pipeline_id} not found")

        # 2. Create pipeline_run record
        run_id = self.run_svc.create_run(pipeline_id, triggered_by)
        logger.info("Pipeline %d run %d started (triggered_by=%s)",
                     pipeline_id, run_id, triggered_by)

        enabled_stages = pipeline.get("enabled_stages", self.ALL_STAGES)
        if isinstance(enabled_stages, str):
            enabled_stages = json.loads(enabled_stages)

        stage_logs: list = []
        stats = {
            "trends_found": 0,
            "topics_suggested": 0,
            "contents_generated": 0,
            "variants_generated": 0,
            "jobs_created": 0,
            "total_tokens_used": 0,
            "total_cost_usd": 0.0,
        }

        # Intermediate data flowing between stages
        trends: list = []
        topics: list = []
        content_ids: list = []

        # 3. Execute each enabled stage in order
        for stage_name in self.ALL_STAGES:
            if stage_name not in enabled_stages:
                continue

            self.run_svc.update_run(run_id, {"current_stage": stage_name})
            stage_start = _now()

            try:
                if stage_name == "trend_scan":
                    trends = self._stage_trend_scan(pipeline, run_id)
                    stats["trends_found"] = len(trends)

                elif stage_name == "topic_select":
                    topics = self._stage_topic_select(pipeline, run_id, trends)
                    stats["topics_suggested"] = len(topics)

                elif stage_name == "content_gen":
                    content_ids = self._stage_content_gen(pipeline, run_id, topics)
                    stats["contents_generated"] = len(content_ids)

                elif stage_name == "variant_gen":
                    variant_count = self._stage_variant_gen(pipeline, run_id, content_ids)
                    stats["variants_generated"] = len(variant_count)

                elif stage_name == "card_render":
                    cards_rendered = self._stage_card_render(pipeline, run_id, content_ids)
                    stats["cards_rendered"] = cards_rendered

                elif stage_name == "auto_review":
                    self._stage_auto_review(pipeline, run_id, content_ids)

                elif stage_name == "job_dispatch":
                    job_ids = self._stage_job_dispatch(pipeline, run_id, content_ids)
                    stats["jobs_created"] = len(job_ids)

                stage_logs.append({
                    "stage": stage_name,
                    "status": "success",
                    "started_at": stage_start,
                    "completed_at": _now(),
                    "message": "",
                })
                logger.info("Pipeline %d run %d stage [%s] succeeded",
                            pipeline_id, run_id, stage_name)

            except Exception as exc:
                error_msg = str(exc)
                stage_logs.append({
                    "stage": stage_name,
                    "status": "error",
                    "started_at": stage_start,
                    "completed_at": _now(),
                    "message": error_msg,
                })
                logger.error("Pipeline %d run %d stage [%s] failed: %s",
                             pipeline_id, run_id, stage_name, error_msg)
                # Continue to the next stage even on error

            # Update run statistics after each stage
            self.run_svc.update_run(run_id, {
                **stats,
                "stage_logs": stage_logs,
            })

        # 4. Finalise the run
        self.run_svc.update_run(run_id, {
            "status": "completed",
            "current_stage": "",
            "completed_at": _now(),
            **stats,
            "stage_logs": stage_logs,
        })

        # Update pipeline metadata
        self.pipeline_svc.update(pipeline_id, {
            "total_runs": (pipeline.get("total_runs", 0) or 0) + 1,
            "last_run_at": _now(),
        })

        logger.info("Pipeline %d run %d completed: %s",
                     pipeline_id, run_id, stats)

        return {"run_id": run_id, **stats, "stage_logs": stage_logs}

    # ── stage implementations ───────────────────────────────────────────

    def _stage_trend_scan(self, pipeline: dict, run_id: int) -> list:
        """Stage 1: Scan RSS feeds for new trends.

        Uses DEFAULT_RSS_FEEDS from config.py.
        Returns list of new trend ids.
        """
        feed_urls = DEFAULT_RSS_FEEDS
        new_ids = self.trend_svc.scan_rss(feed_urls)
        logger.info("trend_scan: discovered %d new trends", len(new_ids))
        return new_ids

    def _stage_topic_select(self, pipeline: dict, run_id: int,
                            trends: list) -> list:
        """Stage 2: Select or generate content topics from trends.

        If the pipeline has an ai_config, use AI to analyse trends and
        generate topic suggestions.  Otherwise fall back to
        analyze_top_topics (historical performance based).
        Returns list of topic suggestion dicts.
        """
        ai_config = self._resolve_ai_config(pipeline)

        if ai_config and trends:
            # Use AI to generate topic suggestions from trends
            topics = self._ai_generate_topics(ai_config, pipeline, run_id, trends)
        else:
            # Fallback: historical performance analysis
            top_topics = self.topic_svc.analyze_top_topics()
            topics = []
            for t in top_topics[:10]:
                sid = self.topic_svc.create({
                    "topic": t.get("topic", ""),
                    "description": f"Based on historical performance (avg likes: {t.get('avg_likes', 0):.0f})",
                    "reasoning": "Selected from top-performing historical topics",
                    "source_type": "analytics",
                    "score": float(t.get("avg_likes", 0)),
                    "suggested_platforms": pipeline.get("target_platforms", []),
                    "suggested_content_type": (pipeline.get("target_content_types", ["image_single"]) or ["image_single"])[0],
                    "status": "pending",
                })
                suggestion = self.topic_svc.get(sid)
                if suggestion:
                    topics.append(suggestion)

        logger.info("topic_select: %d topics selected", len(topics))
        return topics

    def _stage_content_gen(self, pipeline: dict, run_id: int,
                           topics: list) -> list:
        """Stage 3: Generate content for each selected topic.

        Returns list of newly created content ids.
        """
        ai_config = self._resolve_ai_config(pipeline)
        if not ai_config:
            logger.warning("content_gen: no AI config available, skipping")
            return []

        target_languages = pipeline.get("target_languages", ["zh"]) or ["zh"]
        target_content_types = pipeline.get("target_content_types", ["image_single"]) or ["image_single"]
        target_platforms = pipeline.get("target_platforms", []) or []

        language = target_languages[0] if target_languages else "zh"
        content_type = target_content_types[0] if target_content_types else "image_single"
        platform = target_platforms[0] if target_platforms else "instagram"

        content_ids = []
        for topic_item in topics:
            topic_text = topic_item.get("topic", "") if isinstance(topic_item, dict) else str(topic_item)
            suggestion_id = topic_item.get("id") if isinstance(topic_item, dict) else None

            try:
                result = self.gen_svc.generate_content(
                    ai_config=ai_config,
                    topic=topic_text,
                    platform=platform,
                    language=language,
                    content_type=content_type,
                    suggestion_id=suggestion_id,
                    pipeline_run_id=run_id,
                )
                cid = result.get("content_id")
                if cid:
                    content_ids.append(cid)
                    # Mark suggestion as used
                    if suggestion_id:
                        self.topic_svc.mark_used(suggestion_id, cid)
            except Exception as exc:
                logger.error("content_gen failed for topic '%s': %s",
                             topic_text, exc)

        logger.info("content_gen: generated %d contents", len(content_ids))
        return content_ids

    def _stage_variant_gen(self, pipeline: dict, run_id: int,
                           content_ids: list) -> list:
        """Stage 4: Generate platform-specific variants for each content.

        Returns list of variant result dicts.
        """
        ai_config = self._resolve_ai_config(pipeline)
        if not ai_config:
            logger.warning("variant_gen: no AI config available, skipping")
            return []

        target_platforms = pipeline.get("target_platforms", []) or []
        if not target_platforms:
            logger.info("variant_gen: no target platforms configured, skipping")
            return []

        all_variants = []
        for cid in content_ids:
            try:
                variants = self.gen_svc.generate_variants(
                    ai_config=ai_config,
                    content_id=cid,
                    target_platforms=target_platforms,
                    pipeline_run_id=run_id,
                )
                all_variants.extend(variants)
            except Exception as exc:
                logger.error("variant_gen failed for content %d: %s", cid, exc)

        logger.info("variant_gen: generated %d variants", len(all_variants))
        return all_variants

    def _stage_auto_review(self, pipeline: dict, run_id: int,
                           content_ids: list) -> list:
        """Stage 5: Auto-approve content if pipeline.auto_approve is True.

        Returns list of approved content ids.
        """
        approved = []
        if not pipeline.get("auto_approve"):
            logger.info("auto_review: auto_approve is off, skipping")
            return approved

        for cid in content_ids:
            try:
                ok = self.content_svc.review(cid, "approved",
                                             notes="Auto-approved by pipeline")
                if ok:
                    approved.append(cid)
            except Exception as exc:
                logger.error("auto_review failed for content %d: %s", cid, exc)

        logger.info("auto_review: approved %d contents", len(approved))
        return approved

    def _stage_job_dispatch(self, pipeline: dict, run_id: int,
                            content_ids: list) -> list:
        """Stage 6: Create distribution jobs for target account groups.

        Looks up accounts belonging to target_account_group_ids and
        creates a job for each content x account combination.
        Returns list of created job ids.
        """
        group_ids = pipeline.get("target_account_group_ids", []) or []
        if not group_ids:
            logger.info("job_dispatch: no target account groups, skipping")
            return []

        # Resolve account ids from groups
        account_ids = self._resolve_account_ids(group_ids)
        if not account_ids:
            logger.info("job_dispatch: no active accounts found in groups %s",
                        group_ids)
            return []

        all_job_ids = []
        for cid in content_ids:
            try:
                job_ids = self.job_svc.batch_create(
                    content_id=cid,
                    account_ids=account_ids,
                )
                all_job_ids.extend(job_ids)
            except Exception as exc:
                logger.error("job_dispatch failed for content %d: %s", cid, exc)

        logger.info("job_dispatch: created %d jobs", len(all_job_ids))
        return all_job_ids

    def _stage_card_render(self, pipeline: dict, run_id: int,
                           content_ids: list) -> int:
        """Stage 5: Render card images for variants that lack media.

        Reads slides data from generation_task output_data and renders
        them as PNG card images using CardRenderService.
        Returns count of variants that received card images.
        """
        from services.card_render_service import CardRenderService
        from services.content_service import VariantService
        from config import CARD_TEMPLATES_DIR, UPLOAD_DIR

        vs = VariantService(self.db_path)

        # Pipeline-level card settings (stored in trigger_config or defaults)
        trigger_config = pipeline.get("trigger_config", {}) or {}
        if isinstance(trigger_config, str):
            try:
                trigger_config = json.loads(trigger_config)
            except Exception:
                trigger_config = {}
        template = trigger_config.get("card_template", "minimal")
        color_scheme = trigger_config.get("card_color_scheme")

        render_svc = CardRenderService(self.db_path, CARD_TEMPLATES_DIR, UPLOAD_DIR)
        rendered_count = 0

        try:
            for cid in content_ids:
                variants = vs.list_by_content(cid)
                for variant in variants:
                    # Skip variants that already have media
                    existing_media = variant.get("media_asset_ids")
                    if existing_media:
                        if isinstance(existing_media, str):
                            try:
                                existing_media = json.loads(existing_media)
                            except Exception:
                                existing_media = []
                        if existing_media:
                            continue

                    platform = variant.get("platform", "xiaohongshu")

                    # Find slides from generation_task output_data
                    slides = self._get_slides_for_content(cid)
                    if not slides:
                        continue

                    try:
                        render_svc.render_and_attach(
                            variant["id"], slides, template, platform, color_scheme)
                        rendered_count += 1
                    except Exception as exc:
                        logger.error("card_render failed for variant %d: %s",
                                     variant["id"], exc)
        finally:
            render_svc.close()

        logger.info("card_render: rendered cards for %d variants", rendered_count)
        return rendered_count

    def _get_slides_for_content(self, content_id: int) -> list:
        """Retrieve slides data from generation_task output_data for a content."""
        conn = get_connection(self.db_path)
        try:
            row = conn.execute("""
                SELECT output_data FROM generation_tasks
                WHERE content_id = ? AND task_type IN ('card_content', 'content')
                  AND status = 'completed'
                ORDER BY id DESC LIMIT 1
            """, (content_id,)).fetchone()
            if not row or not row["output_data"]:
                return []
            output = row["output_data"]
            if isinstance(output, str):
                output = json.loads(output)
            return output.get("slides", [])
        except Exception:
            return []
        finally:
            conn.close()

    # ── private helpers ─────────────────────────────────────────────────

    def _resolve_ai_config(self, pipeline: dict) -> Optional[dict]:
        """Resolve the AI config for a pipeline.

        Uses pipeline.ai_config_id if set, otherwise falls back to the
        'default' config key.
        """
        ai_config_id = pipeline.get("ai_config_id")
        if ai_config_id:
            config = self.ai_config_svc.get(ai_config_id)
            if config:
                return config

        # Fallback: try 'default' key
        config = self.ai_config_svc.get_by_key("default")
        return config

    def _resolve_account_ids(self, group_ids: list) -> list:
        """Look up active account ids belonging to the given group ids."""
        conn = get_connection(self.db_path)
        try:
            placeholders = ",".join("?" for _ in group_ids)
            rows = conn.execute(
                f"""
                SELECT id FROM accounts
                WHERE group_id IN ({placeholders})
                  AND status = 'active'
                """,
                group_ids,
            ).fetchall()
            return [row["id"] for row in rows]
        finally:
            conn.close()

    def _ai_generate_topics(self, ai_config: dict, pipeline: dict,
                            run_id: int, trend_ids: list) -> list:
        """Use AI to generate topic suggestions from a list of trend ids."""
        # Fetch trend details
        trend_details = []
        for tid in trend_ids[:20]:  # cap to avoid overly long prompts
            trend = self.trend_svc.get(tid)
            if trend:
                trend_details.append(trend)

        if not trend_details:
            return []

        # Build a summary of trends for the AI prompt
        trend_summaries = []
        for t in trend_details:
            trend_summaries.append(
                f"- {t.get('title', '')} ({t.get('source', '')}): "
                f"{t.get('description', '')[:200]}"
            )
        trend_text = "\n".join(trend_summaries)

        target_platforms = pipeline.get("target_platforms", []) or []
        platform_text = ", ".join(target_platforms) if target_platforms else "all platforms"

        system_prompt = "You are a content strategist. Analyze the following trends and suggest content topics."
        user_prompt = f"""Based on the following trending topics, suggest 5 content ideas suitable for {platform_text}.

Trends:
{trend_text}

For each suggestion, output a JSON array. Each element:
{{
  "topic": "topic title",
  "description": "brief description of the content angle",
  "reasoning": "why this topic is good now",
  "keywords": ["kw1", "kw2"],
  "suggested_content_type": "image_single",
  "score": 0.8
}}

Output ONLY the JSON array, nothing else."""

        try:
            result = self.gen_svc.call_ai(
                provider=ai_config.get("provider", "anthropic"),
                model=ai_config.get("model", "claude-sonnet-4-20250514"),
                api_key=_resolve_api_key(ai_config.get("api_key_encrypted", "")),
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=ai_config.get("max_tokens", 4096),
                temperature=ai_config.get("temperature", 0.7),
                base_url=ai_config.get("base_url", ""),
            )

            raw = result.get("content", "")
            suggestions_data = self._parse_json_array(raw)

            created_topics = []
            for s in suggestions_data:
                sid = self.topic_svc.create({
                    "topic": s.get("topic", ""),
                    "description": s.get("description", ""),
                    "reasoning": s.get("reasoning", ""),
                    "source_type": "ai",
                    "keywords": s.get("keywords", []),
                    "suggested_content_type": s.get("suggested_content_type", "image_single"),
                    "suggested_platforms": target_platforms,
                    "score": float(s.get("score", 0.5)),
                    "status": "pending",
                })
                suggestion = self.topic_svc.get(sid)
                if suggestion:
                    created_topics.append(suggestion)

            return created_topics

        except Exception as exc:
            logger.error("AI topic generation failed: %s", exc)
            return []

    @staticmethod
    def _parse_json_array(text: str) -> list:
        """Extract a JSON array from AI response text."""
        text = text.strip()
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()
        start = text.find("[")
        end = text.rfind("]")
        if start != -1 and end != -1:
            text = text[start:end + 1]
        try:
            return json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return []
