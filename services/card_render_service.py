"""Card Render Service - renders structured slide data into PNG card images.

Uses Playwright headless browser to screenshot HTML/CSS templates, then saves
images as assets and attaches them to variants for publishing.
"""

import hashlib
import json
import logging
import os
import uuid
from typing import List, Optional

from config import DB_PATH, CARD_TEMPLATES_DIR, UPLOAD_DIR
from models.database import get_connection

logger = logging.getLogger(__name__)


# Platform canvas sizes (width, height)
PLATFORM_SIZES = {
    "xiaohongshu": (1080, 1440),
    "instagram":   (1080, 1350),
    "douyin":      (1080, 1920),
    "tiktok":      (1080, 1920),
    "youtube":     (1280, 720),
    "weibo":       (1080, 1080),
    "twitter":     (1200, 675),
    "facebook":    (1080, 1080),
    "bilibili":    (1080, 1440),
}

# Template metadata
TEMPLATE_INFO = {
    "minimal": {
        "label": "简约",
        "description": "简约大留白，适合知识分享、干货类内容",
        "default_colors": {
            "primary": "#6c5ce7",
            "bg": "#FFFFFF",
            "text": "#1a1a2e",
            "accent": "#a29bfe",
            "muted": "#b2bec3",
        },
    },
    "fashion": {
        "label": "时尚",
        "description": "渐变色彩+几何装饰，适合潮流、美妆、穿搭内容",
        "default_colors": {
            "primary": "#FF6B9D",
            "bg": "#FFF5F8",
            "bg_end": "#FDF0F5",
            "text": "#2d3436",
            "accent": "#C44569",
            "muted": "#b2bec3",
        },
    },
    "business": {
        "label": "商务",
        "description": "深色底+序号编排，适合职场、财经、科技类内容",
        "default_colors": {
            "primary": "#1a2a3a",
            "bg": "#0a1628",
            "text": "#e0e6ed",
            "accent": "#f6b93b",
            "muted": "#8395a7",
        },
    },
    "fresh": {
        "label": "清新",
        "description": "圆角大间距+浅色底，适合生活、美食、旅行内容",
        "default_colors": {
            "primary": "#00b894",
            "bg": "#f0f5f3",
            "text": "#2d3436",
            "accent": "#00cec9",
            "muted": "#b2bec3",
        },
    },
}

AVAILABLE_TEMPLATES = list(TEMPLATE_INFO.keys())


class CardRenderService:
    """Renders structured slide data into PNG card images using Playwright."""

    def __init__(self, db_path: str = None, templates_dir: str = None,
                 upload_dir: str = None):
        self.db_path = db_path or DB_PATH
        self.templates_dir = templates_dir or CARD_TEMPLATES_DIR
        self.upload_dir = upload_dir or UPLOAD_DIR
        self._browser = None
        self._pw = None

    def _ensure_browser(self):
        """Lazy-init a persistent headless Chromium for rendering."""
        if self._browser and self._browser.is_connected():
            return
        try:
            from playwright.sync_api import sync_playwright
            self._pw = sync_playwright().start()
            self._browser = self._pw.chromium.launch(headless=True)
            logger.info("CardRenderService: headless browser started")
        except Exception as e:
            logger.error(f"Failed to start headless browser: {e}")
            raise

    def close(self):
        """Clean up browser resources."""
        if self._browser:
            try:
                self._browser.close()
            except Exception:
                pass
            self._browser = None
        if self._pw:
            try:
                self._pw.stop()
            except Exception:
                pass
            self._pw = None

    # ── Public API ────────────────────────────────────────────

    def list_templates(self) -> list:
        """Return available template metadata."""
        result = []
        for name, info in TEMPLATE_INFO.items():
            result.append({
                "name": name,
                "label": info["label"],
                "description": info["description"],
                "default_colors": info["default_colors"],
            })
        return result

    def render_cards(self, slides: list, template: str = "minimal",
                     platform: str = "xiaohongshu",
                     color_scheme: dict = None) -> list:
        """Render all slides to PNG images.

        Returns list of dicts: [{"slide_index": 0, "file_path": "...", "asset_id": 1}, ...]
        """
        template = template if template in AVAILABLE_TEMPLATES else "minimal"
        width, height = PLATFORM_SIZES.get(platform, (1080, 1440))
        colors = self._resolve_colors(template, color_scheme)

        results = []
        card_group_id = uuid.uuid4().hex[:12]

        for i, slide in enumerate(slides):
            try:
                png_bytes = self._render_single(
                    slide, i, len(slides), template, width, height, colors)
                asset_id, file_path = self._save_and_create_asset(
                    png_bytes, width, height, {
                        "source": "card_render",
                        "slide_index": i,
                        "slide_type": slide.get("type", ""),
                        "template": template,
                        "platform": platform,
                        "card_group_id": card_group_id,
                    })
                results.append({
                    "slide_index": i,
                    "file_path": file_path,
                    "asset_id": asset_id,
                })
            except Exception as e:
                logger.error(f"Failed to render slide {i}: {e}")
                continue

        return results

    def render_and_attach(self, variant_id: int, slides: list,
                          template: str = "minimal",
                          platform: str = "xiaohongshu",
                          color_scheme: dict = None) -> list:
        """Full workflow: render all slides → save as assets → update variant.media_asset_ids.

        Returns list of asset_ids.
        """
        rendered = self.render_cards(slides, template, platform, color_scheme)
        asset_ids = [r["asset_id"] for r in rendered]

        if not asset_ids:
            logger.warning(f"No cards rendered for variant {variant_id}")
            return []

        # Update variant with rendered asset IDs
        conn = get_connection(self.db_path)
        try:
            conn.execute(
                "UPDATE variants SET media_asset_ids = ?, cover_asset_id = ? WHERE id = ?",
                (json.dumps(asset_ids), asset_ids[0], variant_id)
            )
            conn.commit()
            logger.info(f"Attached {len(asset_ids)} cards to variant {variant_id}")
        finally:
            conn.close()

        return asset_ids

    def rerender_and_replace(self, variant_id: int, slides: list,
                             template: str = "minimal",
                             platform: str = "xiaohongshu",
                             color_scheme: dict = None) -> list:
        """Re-render with different template/colors, replacing old assets.

        Deletes old card_render assets, then renders and attaches new ones.
        """
        # Get current asset IDs from variant
        conn = get_connection(self.db_path)
        try:
            row = conn.execute(
                "SELECT media_asset_ids FROM variants WHERE id = ?",
                (variant_id,)
            ).fetchone()
            if row and row["media_asset_ids"]:
                old_ids = row["media_asset_ids"]
                if isinstance(old_ids, str):
                    try:
                        old_ids = json.loads(old_ids)
                    except Exception:
                        old_ids = []
                # Clear variant FK references before deleting assets
                conn.execute(
                    "UPDATE variants SET cover_asset_id = NULL, media_asset_ids = '[]' WHERE id = ?",
                    (variant_id,)
                )
                # Delete old card_render assets
                for aid in old_ids:
                    asset = conn.execute(
                        "SELECT storage_url, meta FROM assets WHERE id = ?",
                        (aid,)
                    ).fetchone()
                    if asset:
                        meta = asset["meta"]
                        if isinstance(meta, str):
                            try:
                                meta = json.loads(meta)
                            except Exception:
                                meta = {}
                        if isinstance(meta, dict) and meta.get("source") == "card_render":
                            fpath = os.path.join(self.upload_dir, asset["storage_url"])
                            if os.path.exists(fpath):
                                os.remove(fpath)
                            conn.execute("DELETE FROM assets WHERE id = ?", (aid,))
                conn.commit()
        finally:
            conn.close()

        return self.render_and_attach(variant_id, slides, template, platform, color_scheme)

    # ── Internal methods ──────────────────────────────────────

    def _resolve_colors(self, template: str, override: dict = None) -> dict:
        """Merge default template colors with user overrides."""
        defaults = TEMPLATE_INFO.get(template, TEMPLATE_INFO["minimal"])["default_colors"].copy()
        if override:
            defaults.update(override)
        # Ensure bg_end exists for fashion template
        if "bg_end" not in defaults:
            defaults["bg_end"] = defaults.get("bg", "#FFFFFF")
        return defaults

    def _render_single(self, slide: dict, index: int, total: int,
                       template: str, width: int, height: int,
                       colors: dict) -> bytes:
        """Render a single slide to PNG bytes."""
        html = self._build_html(slide, index, total, template, width, height, colors)
        return self._screenshot_html(html, width, height)

    def _build_html(self, slide: dict, index: int, total: int,
                    template: str, width: int, height: int,
                    colors: dict) -> str:
        """Fill Jinja2 template with slide data → HTML string."""
        from jinja2 import Environment, FileSystemLoader, select_autoescape

        env = Environment(
            loader=FileSystemLoader(self.templates_dir),
            autoescape=select_autoescape([]),
        )
        tmpl = env.get_template(f"{template}.html")

        return tmpl.render(
            slide=slide,
            slide_index=index,
            total_slides=total,
            width=width,
            height=height,
            colors=colors,
        )

    def _screenshot_html(self, html: str, width: int, height: int) -> bytes:
        """Use Playwright to render HTML string to PNG bytes."""
        self._ensure_browser()

        page = self._browser.new_page(viewport={"width": width, "height": height})
        try:
            page.set_content(html, wait_until="load")
            # Wait for fonts to load
            page.wait_for_timeout(400)
            return page.screenshot(type="png", full_page=False)
        finally:
            page.close()

    def _save_and_create_asset(self, png_bytes: bytes, width: int, height: int,
                               meta: dict) -> tuple:
        """Save PNG to disk and create asset record. Returns (asset_id, relative_path)."""
        from services.content_service import AssetService

        sha = hashlib.sha256(png_bytes).hexdigest()
        filename = f"{uuid.uuid4().hex}.png"
        filepath = os.path.join(self.upload_dir, filename)

        os.makedirs(self.upload_dir, exist_ok=True)
        with open(filepath, "wb") as f:
            f.write(png_bytes)

        asset_svc = AssetService(self.db_path)
        asset_id = asset_svc.create({
            "asset_type": "image",
            "storage_url": filename,
            "sha256": sha,
            "width": width,
            "height": height,
            "filesize_bytes": len(png_bytes),
            "meta": meta,
        })

        return asset_id, filename
