"""
Service for Trend CRUD, RSS scanning, and expiry management.
"""

import json
from datetime import datetime, timedelta
from typing import Optional, List

from models.database import get_connection


# ── helpers ──────────────────────────────────────────────────────────────

def _row_to_dict(row) -> dict:
    """Convert a sqlite3.Row to a plain dict, deserialising JSON fields."""
    if row is None:
        return {}
    d = dict(row)
    for field in ("keywords", "related_topics", "raw_data"):
        if field in d and isinstance(d[field], str):
            try:
                d[field] = json.loads(d[field])
            except (json.JSONDecodeError, TypeError):
                pass
    return d


def _now() -> str:
    return datetime.now().isoformat()


# ── TrendService ───────────────────────────────────────────────────────

class TrendService:
    """CRUD + RSS scanning + expiry for the `trends` table."""

    def __init__(self, db_path: str):
        self.db_path = db_path

    # -- create ----------------------------------------------------------------

    def create(self, data: dict) -> int:
        """Insert a new trend and return its id."""
        conn = get_connection(self.db_path)
        try:
            now = _now()

            keywords = data.get("keywords", [])
            if not isinstance(keywords, str):
                keywords = json.dumps(keywords, ensure_ascii=False)

            related_topics = data.get("related_topics", [])
            if not isinstance(related_topics, str):
                related_topics = json.dumps(related_topics, ensure_ascii=False)

            raw_data = data.get("raw_data", {})
            if not isinstance(raw_data, str):
                raw_data = json.dumps(raw_data, ensure_ascii=False)

            cur = conn.execute(
                """
                INSERT INTO trends
                    (source, source_url, title, description,
                     keywords, category, region, language,
                     heat_score, trend_status, related_topics,
                     raw_data, discovered_at, expires_at, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    data.get("source", ""),
                    data.get("source_url", ""),
                    data.get("title", ""),
                    data.get("description", ""),
                    keywords,
                    data.get("category", ""),
                    data.get("region", "global"),
                    data.get("language", "zh"),
                    data.get("heat_score", 0.0),
                    data.get("trend_status", "active"),
                    related_topics,
                    raw_data,
                    data.get("discovered_at", now),
                    data.get("expires_at"),
                    now,
                ),
            )
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()

    # -- get -------------------------------------------------------------------

    def get(self, trend_id: int) -> Optional[dict]:
        """Return a single trend dict or None."""
        conn = get_connection(self.db_path)
        try:
            row = conn.execute(
                "SELECT * FROM trends WHERE id = ?", (trend_id,)
            ).fetchone()
            if row is None:
                return None
            return _row_to_dict(row)
        finally:
            conn.close()

    # -- list_all --------------------------------------------------------------

    def list_all(
        self,
        status: Optional[str] = None,
        source: Optional[str] = None,
        limit: int = 50,
    ) -> List[dict]:
        """Return trends, optionally filtered by status / source."""
        conn = get_connection(self.db_path)
        try:
            query = "SELECT * FROM trends WHERE 1=1"
            params: list = []

            if status is not None:
                query += " AND trend_status = ?"
                params.append(status)
            if source is not None:
                query += " AND source = ?"
                params.append(source)

            query += " ORDER BY id DESC LIMIT ?"
            params.append(limit)

            rows = conn.execute(query, params).fetchall()
            return [_row_to_dict(row) for row in rows]
        finally:
            conn.close()

    # -- update_status ---------------------------------------------------------

    def update_status(self, trend_id: int, status: str) -> bool:
        """Update the trend_status of a trend. Returns True if a row was updated."""
        conn = get_connection(self.db_path)
        try:
            cur = conn.execute(
                "UPDATE trends SET trend_status = ? WHERE id = ?",
                (status, trend_id),
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    # -- delete ----------------------------------------------------------------

    def delete(self, trend_id: int) -> bool:
        """Delete a trend. Returns True if deleted."""
        conn = get_connection(self.db_path)
        try:
            cur = conn.execute(
                "DELETE FROM trends WHERE id = ?", (trend_id,)
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    # -- scan_rss --------------------------------------------------------------

    @staticmethod
    def _parse_traffic(raw: str) -> float:
        """Convert ht_approx_traffic like '2,000+' / '500+' to a 0-100 heat score."""
        if not raw:
            return 0.0
        num_str = raw.replace(",", "").replace("+", "").strip()
        try:
            n = int(num_str)
        except (ValueError, TypeError):
            return 0.0
        # Map: 100→10, 500→30, 1000→45, 5000→65, 10000→75, 50000→90, 100000+→100
        import math
        if n <= 0:
            return 0.0
        return min(round(math.log10(max(n, 1)) * 20), 100)

    @staticmethod
    def _extract_geo(feed_url: str) -> tuple:
        """Extract region and language from feed URL geo param."""
        from urllib.parse import urlparse, parse_qs
        try:
            qs = parse_qs(urlparse(feed_url).query)
            geo = qs.get("geo", ["US"])[0].upper()
        except Exception:
            geo = "US"
        lang = "zh" if geo in ("CN", "TW", "HK") else "en"
        return geo, lang

    def scan_rss(self, feed_urls: list) -> List[int]:
        """Parse RSS feeds and create trend records for new entries.

        Extracts all available Google Trends metadata (traffic, news,
        picture, etc.) instead of only the title.
        De-duplication: entries with the same title are skipped.
        Returns a list of newly created trend ids.
        """
        import feedparser
        import logging
        logger = logging.getLogger(__name__)

        new_ids: List[int] = []
        conn = get_connection(self.db_path)
        try:
            for url in feed_urls:
                try:
                    feed = feedparser.parse(url)
                except Exception as exc:
                    logger.warning("Failed to parse RSS feed %s: %s", url, exc)
                    continue

                if feed.bozo and not feed.entries:
                    logger.warning("RSS feed returned no entries: %s (bozo: %s)",
                                   url, feed.bozo_exception)
                    continue

                geo, lang = self._extract_geo(url)

                for entry in feed.entries:
                    title = getattr(entry, "title", "")
                    if not title:
                        continue

                    # De-duplicate by title (regardless of source)
                    existing = conn.execute(
                        "SELECT id FROM trends WHERE title = ?",
                        (title,),
                    ).fetchone()
                    if existing:
                        continue

                    # Extract rich metadata from Google Trends RSS
                    traffic_str = entry.get("ht_approx_traffic", "")
                    heat_score = self._parse_traffic(traffic_str)

                    news_title = entry.get("ht_news_item_title", "")
                    news_snippet = entry.get("ht_news_item_snippet", "")
                    news_source = entry.get("ht_news_item_source", "")
                    news_url = entry.get("ht_news_item_url", "")
                    picture = entry.get("ht_picture", "")

                    description = news_title or news_snippet or entry.get("summary", "")

                    # Build source_url: prefer news URL, fall back to trend search
                    source_url = news_url or f"https://trends.google.com/trends/explore?q={title}&geo={geo}"

                    # Extract keywords from title
                    keywords = [w.strip() for w in title.split() if len(w.strip()) > 1]

                    # Use published time if available
                    published = entry.get("published", "")
                    discovered = published if published else _now()

                    now = _now()
                    cur = conn.execute(
                        """
                        INSERT INTO trends
                            (source, source_url, title, description,
                             keywords, category, region, language,
                             heat_score, trend_status, related_topics,
                             raw_data, discovered_at, expires_at, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            f"Google Trends ({geo})",
                            source_url,
                            title,
                            description,
                            json.dumps(keywords, ensure_ascii=False),
                            "",
                            geo,
                            lang,
                            heat_score,
                            "active",
                            "[]",
                            json.dumps({
                                "traffic": traffic_str,
                                "news_source": news_source,
                                "news_url": news_url,
                                "picture": picture,
                            }, ensure_ascii=False),
                            discovered,
                            None,
                            now,
                        ),
                    )
                    new_ids.append(cur.lastrowid)

            conn.commit()
            return new_ids
        finally:
            conn.close()

    # -- expire_old ------------------------------------------------------------

    def expire_old(self, days: int = 7) -> int:
        """Mark active trends older than *days* days as expired.

        Returns the number of rows updated.
        """
        conn = get_connection(self.db_path)
        try:
            cutoff = (datetime.now() - timedelta(days=days)).isoformat()
            cur = conn.execute(
                """
                UPDATE trends
                SET trend_status = 'expired'
                WHERE trend_status = 'active' AND created_at < ?
                """,
                (cutoff,),
            )
            conn.commit()
            return cur.rowcount
        finally:
            conn.close()
