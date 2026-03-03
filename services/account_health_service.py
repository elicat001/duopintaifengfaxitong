"""Service for account health monitoring, risk scoring, and warming workflow."""

import logging
from datetime import datetime, timedelta
from typing import Optional, List

from models.database import get_connection
from config import RISK_SCORE_HIGH, RISK_SCORE_MEDIUM, WARMING_STAGES

logger = logging.getLogger(__name__)


def _row_to_dict(row) -> dict:
    return dict(row) if row else {}


def _now() -> str:
    return datetime.now().isoformat()


class AccountHealthService:
    """Account risk scoring, health dashboard, and warming workflow."""

    def __init__(self, db_path: str):
        self.db_path = db_path

    def compute_risk_score(self, account_id: int) -> float:
        """Compute 0-100 risk score from login failures, rate limits, ban history, posting failures."""
        conn = get_connection(self.db_path)
        try:
            risk = 0.0

            # Factor 1: Login failure rate (0-30 points)
            ls = conn.execute(
                "SELECT * FROM account_login_status WHERE account_id = ?",
                (account_id,),
            ).fetchone()
            if ls:
                ls = _row_to_dict(ls)
                cf = ls.get("consecutive_failures") or 0
                risk += min(30, cf * 6)  # 5 consecutive failures = 30 risk
                # Low health score adds risk
                hs = ls.get("health_score") or 0
                if hs < 50:
                    risk += (50 - hs) * 0.3  # Up to 15 points

            # Factor 2: Recent login failures (0-20 points)
            recent_fails = conn.execute(
                """SELECT COUNT(*) as cnt FROM login_logs
                   WHERE account_id = ? AND status = 'failure'
                   AND created_at > datetime('now', '-7 days')""",
                (account_id,),
            ).fetchone()["cnt"]
            risk += min(20, recent_fails * 2)

            # Factor 3: Job failure rate (0-20 points)
            job_stats = conn.execute(
                """SELECT COUNT(*) as total,
                   SUM(CASE WHEN state IN ('failed_final', 'failed_retryable') THEN 1 ELSE 0 END) as fails
                   FROM jobs WHERE account_id = ? AND created_at > datetime('now', '-30 days')""",
                (account_id,),
            ).fetchone()
            if job_stats and job_stats["total"] > 0:
                fail_rate = (job_stats["fails"] or 0) / job_stats["total"]
                risk += fail_rate * 20

            # Factor 4: Account status penalty (0-30 points)
            acct = conn.execute(
                "SELECT status, login_status FROM accounts WHERE id = ?",
                (account_id,),
            ).fetchone()
            if acct:
                if acct["status"] == "banned" or acct["login_status"] == "banned":
                    risk += 30
                elif acct["login_status"] in ("expired", "need_captcha", "need_verify"):
                    risk += 15
                elif acct["login_status"] == "rate_limited":
                    risk += 20

            risk = round(min(100.0, max(0.0, risk)), 2)

            # Store the score
            now = _now()
            conn.execute(
                "UPDATE accounts SET risk_score = ?, updated_at = ? WHERE id = ?",
                (risk, now, account_id),
            )
            conn.commit()
            return risk
        finally:
            conn.close()

    def get_health_dashboard(self, account_id: int) -> dict:
        """Return combined health data for a single account."""
        conn = get_connection(self.db_path)
        try:
            acct = conn.execute(
                "SELECT * FROM accounts WHERE id = ?", (account_id,)
            ).fetchone()
            if not acct:
                return {"error": "account not found"}
            acct = _row_to_dict(acct)

            login_status = conn.execute(
                "SELECT * FROM account_login_status WHERE account_id = ?",
                (account_id,),
            ).fetchone()
            login_status = _row_to_dict(login_status) if login_status else {}

            proxy_assign = conn.execute(
                """SELECT apa.*, p.host, p.port, p.status as proxy_status
                   FROM account_proxy_assignments apa
                   LEFT JOIN proxies p ON apa.proxy_id = p.id
                   WHERE apa.account_id = ? AND apa.is_active = 1
                   LIMIT 1""",
                (account_id,),
            ).fetchone()
            proxy_info = _row_to_dict(proxy_assign) if proxy_assign else {}

            cred_count = conn.execute(
                "SELECT COUNT(*) as cnt FROM account_credentials WHERE account_id = ? AND is_active = 1",
                (account_id,),
            ).fetchone()["cnt"]

            recent_jobs = conn.execute(
                """SELECT state, COUNT(*) as cnt FROM jobs
                   WHERE account_id = ? AND created_at > datetime('now', '-7 days')
                   GROUP BY state""",
                (account_id,),
            ).fetchall()
            job_summary = {r["state"]: r["cnt"] for r in recent_jobs}

            recent_login_logs = conn.execute(
                "SELECT * FROM login_logs WHERE account_id = ? ORDER BY created_at DESC LIMIT 10",
                (account_id,),
            ).fetchall()

            return {
                "account": {k: acct[k] for k in ["id", "handle", "platform", "display_name",
                            "status", "login_status", "risk_score", "daily_limit",
                            "hourly_limit", "warming_stage", "warming_started_at"] if k in acct},
                "login_status": login_status,
                "proxy": proxy_info,
                "credential_count": cred_count,
                "job_summary_7d": job_summary,
                "recent_login_logs": [_row_to_dict(r) for r in recent_login_logs],
            }
        finally:
            conn.close()

    def list_at_risk(self, threshold: float = None) -> List[dict]:
        """List accounts with risk_score above threshold."""
        if threshold is None:
            threshold = RISK_SCORE_HIGH
        conn = get_connection(self.db_path)
        try:
            rows = conn.execute(
                """SELECT a.id, a.handle, a.platform, a.display_name, a.status,
                          a.login_status, a.risk_score, a.login_fail_count,
                          als.health_score, als.consecutive_failures
                   FROM accounts a
                   LEFT JOIN account_login_status als ON a.id = als.account_id
                   WHERE a.risk_score >= ?
                   ORDER BY a.risk_score DESC""",
                (threshold,),
            ).fetchall()
            return [_row_to_dict(r) for r in rows]
        finally:
            conn.close()

    def get_warming_status(self, account_id: int) -> dict:
        """Get warming workflow status for an account."""
        conn = get_connection(self.db_path)
        try:
            acct = conn.execute(
                "SELECT id, handle, platform, status, warming_stage, warming_started_at, daily_limit, hourly_limit FROM accounts WHERE id = ?",
                (account_id,),
            ).fetchone()
            if not acct:
                return {"error": "account not found"}
            acct = _row_to_dict(acct)
            stage = acct.get("warming_stage") or 0
            stage_config = WARMING_STAGES.get(stage, {})
            return {
                "account_id": account_id,
                "warming_stage": stage,
                "warming_started_at": acct.get("warming_started_at"),
                "current_limits": {
                    "daily_limit": acct.get("daily_limit"),
                    "hourly_limit": acct.get("hourly_limit"),
                },
                "stage_config": stage_config,
                "total_stages": len(WARMING_STAGES),
                "is_warming": stage > 0,
            }
        finally:
            conn.close()

    def advance_warming(self, account_id: int) -> dict:
        """Move to next warming stage, updating daily/hourly limits."""
        conn = get_connection(self.db_path)
        try:
            acct = conn.execute(
                "SELECT warming_stage, status FROM accounts WHERE id = ?",
                (account_id,),
            ).fetchone()
            if not acct:
                return {"error": "account not found"}
            current = acct["warming_stage"] or 0
            now = _now()

            if current == 0:
                # Start warming
                next_stage = 1
                conn.execute(
                    "UPDATE accounts SET status = 'warming', warming_stage = ?, warming_started_at = ?, updated_at = ? WHERE id = ?",
                    (next_stage, now, now, account_id),
                )
            elif current >= len(WARMING_STAGES):
                # Warming complete
                conn.execute(
                    "UPDATE accounts SET status = 'active', warming_stage = 0, updated_at = ? WHERE id = ?",
                    (now, account_id),
                )
                conn.commit()
                return {"account_id": account_id, "status": "warming_complete",
                        "new_status": "active"}
            else:
                next_stage = current + 1
                conn.execute(
                    "UPDATE accounts SET warming_stage = ?, updated_at = ? WHERE id = ?",
                    (next_stage, now, account_id),
                )

            # Apply stage limits
            stage_config = WARMING_STAGES.get(next_stage if current < len(WARMING_STAGES) else current, {})
            if stage_config:
                conn.execute(
                    "UPDATE accounts SET daily_limit = ?, hourly_limit = ?, updated_at = ? WHERE id = ?",
                    (stage_config["daily_limit"], stage_config["hourly_limit"], now, account_id),
                )

            conn.commit()
            return {
                "account_id": account_id,
                "previous_stage": current,
                "new_stage": next_stage if current < len(WARMING_STAGES) else 0,
                "stage_config": stage_config,
            }
        finally:
            conn.close()

    def compute_all_risk_scores(self) -> dict:
        """Batch recompute risk scores for all accounts."""
        conn = get_connection(self.db_path)
        try:
            rows = conn.execute("SELECT id FROM accounts").fetchall()
        finally:
            conn.close()

        updated = 0
        errors = 0
        for r in rows:
            try:
                self.compute_risk_score(r["id"])
                updated += 1
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning("Risk score compute failed for account %d: %s", r["id"], e)
                errors += 1
        return {"updated": updated, "errors": errors}

    def get_overview_stats(self) -> dict:
        """Dashboard stats: accounts by login_status, avg risk, proxy coverage, etc."""
        conn = get_connection(self.db_path)
        try:
            total = conn.execute("SELECT COUNT(*) as cnt FROM accounts").fetchone()["cnt"]

            by_login = {}
            for row in conn.execute(
                "SELECT login_status, COUNT(*) as cnt FROM accounts GROUP BY login_status"
            ).fetchall():
                by_login[row["login_status"] or "unknown"] = row["cnt"]

            avg_risk = conn.execute(
                "SELECT AVG(risk_score) as avg_r FROM accounts"
            ).fetchone()["avg_r"] or 0

            at_risk = conn.execute(
                "SELECT COUNT(*) as cnt FROM accounts WHERE risk_score >= ?",
                (RISK_SCORE_HIGH,),
            ).fetchone()["cnt"]

            with_proxy = conn.execute(
                "SELECT COUNT(DISTINCT account_id) as cnt FROM account_proxy_assignments WHERE is_active = 1"
            ).fetchone()["cnt"]

            with_cred = conn.execute(
                "SELECT COUNT(DISTINCT account_id) as cnt FROM account_credentials WHERE is_active = 1"
            ).fetchone()["cnt"]

            warming = conn.execute(
                "SELECT COUNT(*) as cnt FROM accounts WHERE warming_stage > 0"
            ).fetchone()["cnt"]

            return {
                "total_accounts": total,
                "by_login_status": by_login,
                "avg_risk_score": round(avg_risk, 2),
                "at_risk_count": at_risk,
                "proxy_coverage": with_proxy,
                "credential_coverage": with_cred,
                "warming_count": warming,
                "proxy_coverage_pct": round((with_proxy / total * 100) if total > 0 else 0, 1),
                "credential_coverage_pct": round((with_cred / total * 100) if total > 0 else 0, 1),
            }
        finally:
            conn.close()
