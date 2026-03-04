"""Service for Proxy Pool management: groups, proxies, assignments, health checks."""

import json
import logging
import random
import time
from datetime import datetime
from typing import Optional, List

from models.database import get_connection

logger = logging.getLogger(__name__)


def _row_to_dict(row) -> dict:
    return dict(row) if row else {}


def _now() -> str:
    return datetime.now().isoformat()


class ProxyGroupService:
    """CRUD for proxy_groups table."""

    def __init__(self, db_path: str):
        self.db_path = db_path

    def create(self, data: dict) -> int:
        conn = get_connection(self.db_path)
        try:
            cur = conn.execute(
                """INSERT INTO proxy_groups (name, description, rotation_strategy)
                   VALUES (?, ?, ?)""",
                (data.get("name", ""), data.get("description", ""),
                 data.get("rotation_strategy", "round_robin")),
            )
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()

    def get(self, group_id: int) -> Optional[dict]:
        conn = get_connection(self.db_path)
        try:
            row = conn.execute(
                "SELECT * FROM proxy_groups WHERE id = ?", (group_id,)
            ).fetchone()
            return _row_to_dict(row) if row else None
        finally:
            conn.close()

    def list_all(self) -> List[dict]:
        conn = get_connection(self.db_path)
        try:
            rows = conn.execute(
                "SELECT * FROM proxy_groups ORDER BY id DESC"
            ).fetchall()
            return [_row_to_dict(r) for r in rows]
        finally:
            conn.close()

    def update(self, group_id: int, data: dict) -> bool:
        conn = get_connection(self.db_path)
        try:
            sets, params = [], []
            for f in ["name", "description", "rotation_strategy"]:
                if f in data:
                    sets.append(f"{f} = ?")
                    params.append(data[f])
            if not sets:
                return False
            params.append(group_id)
            cur = conn.execute(
                f"UPDATE proxy_groups SET {', '.join(sets)} WHERE id = ?", params
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def delete(self, group_id: int) -> bool:
        conn = get_connection(self.db_path)
        try:
            conn.execute("UPDATE proxies SET proxy_group_id = NULL WHERE proxy_group_id = ?", (group_id,))
            cur = conn.execute("DELETE FROM proxy_groups WHERE id = ?", (group_id,))
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def get_proxy_count(self, group_id: int) -> int:
        conn = get_connection(self.db_path)
        try:
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM proxies WHERE proxy_group_id = ?",
                (group_id,),
            ).fetchone()
            return row["cnt"] if row else 0
        finally:
            conn.close()


class ProxyService:
    """CRUD + health check + assignment for proxies and account_proxy_assignments."""

    def __init__(self, db_path: str, crypto=None):
        self.db_path = db_path
        self.crypto = crypto  # optional CryptoService for password encryption

    def create(self, data: dict) -> int:
        conn = get_connection(self.db_path)
        try:
            now = _now()
            password = data.get("password", "")
            if password and self.crypto:
                password = self.crypto.encrypt(password)
            cur = conn.execute(
                """INSERT INTO proxies
                   (name, proxy_type, host, port, username, password_encrypted,
                    proxy_group_id, region, provider, status, is_sticky,
                    notes, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (data.get("name", ""), data.get("proxy_type", "http"),
                 data.get("host", ""), data.get("port", 0),
                 data.get("username", ""), password,
                 data.get("proxy_group_id"), data.get("region", ""),
                 data.get("provider", ""), data.get("status", "active"),
                 1 if data.get("is_sticky") else 0,
                 data.get("notes", ""), now, now),
            )
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()

    def get(self, proxy_id: int) -> Optional[dict]:
        conn = get_connection(self.db_path)
        try:
            row = conn.execute(
                "SELECT * FROM proxies WHERE id = ?", (proxy_id,)
            ).fetchone()
            if row is None:
                return None
            d = _row_to_dict(row)
            # Mask password in output
            if d.get("password_encrypted"):
                d["has_password"] = True
                d.pop("password_encrypted", None)
            else:
                d["has_password"] = False
                d.pop("password_encrypted", None)
            d["is_sticky"] = bool(d.get("is_sticky", 0))
            return d
        finally:
            conn.close()

    def list_all(self, status: str = None, proxy_type: str = None,
                 region: str = None, group_id: int = None,
                 limit: int = 50, offset: int = 0) -> List[dict]:
        conn = get_connection(self.db_path)
        try:
            query = "SELECT * FROM proxies WHERE 1=1"
            params = []
            if status:
                query += " AND status = ?"
                params.append(status)
            if proxy_type:
                query += " AND proxy_type = ?"
                params.append(proxy_type)
            if region:
                query += " AND region = ?"
                params.append(region)
            if group_id is not None:
                query += " AND proxy_group_id = ?"
                params.append(group_id)
            query += " ORDER BY id DESC"
            query += " LIMIT ? OFFSET ?"
            params.extend([limit, offset])
            rows = conn.execute(query, params).fetchall()
            results = []
            for row in rows:
                d = _row_to_dict(row)
                d["has_password"] = bool(d.get("password_encrypted"))
                d.pop("password_encrypted", None)
                d["is_sticky"] = bool(d.get("is_sticky", 0))
                results.append(d)
            return results
        finally:
            conn.close()

    def update(self, proxy_id: int, data: dict) -> bool:
        conn = get_connection(self.db_path)
        try:
            sets, params = [], []
            simple_fields = [
                "name", "proxy_type", "host", "port", "username",
                "proxy_group_id", "region", "provider", "status",
                "notes", "max_bandwidth_mb",
            ]
            for f in simple_fields:
                if f in data:
                    sets.append(f"{f} = ?")
                    params.append(data[f])
            if "is_sticky" in data:
                sets.append("is_sticky = ?")
                params.append(1 if data["is_sticky"] else 0)
            if "password" in data:
                pwd = data["password"]
                if pwd and self.crypto:
                    pwd = self.crypto.encrypt(pwd)
                sets.append("password_encrypted = ?")
                params.append(pwd)
            if not sets:
                return False
            sets.append("updated_at = ?")
            params.append(_now())
            params.append(proxy_id)
            cur = conn.execute(
                f"UPDATE proxies SET {', '.join(sets)} WHERE id = ?", params
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def delete(self, proxy_id: int) -> bool:
        conn = get_connection(self.db_path)
        try:
            conn.execute("DELETE FROM account_proxy_assignments WHERE proxy_id = ?", (proxy_id,))
            conn.execute("DELETE FROM proxy_check_logs WHERE proxy_id = ?", (proxy_id,))
            cur = conn.execute("DELETE FROM proxies WHERE id = ?", (proxy_id,))
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def check_health(self, proxy_id: int) -> dict:
        """Test proxy connectivity by making a simple HTTP request.
        Updates proxy stats and logs the result."""
        conn = get_connection(self.db_path)
        try:
            row = conn.execute(
                "SELECT * FROM proxies WHERE id = ?", (proxy_id,)
            ).fetchone()
            if row is None:
                return {"error": "proxy not found"}
            proxy = _row_to_dict(row)

            # Build proxy URL
            auth = ""
            if proxy["username"]:
                pwd = ""
                if proxy["password_encrypted"] and self.crypto:
                    try:
                        pwd = self.crypto.decrypt(proxy["password_encrypted"])
                    except Exception:
                        pwd = ""
                        logger.warning("Failed to decrypt proxy password for proxy %d", proxy_id)
                auth = f"{proxy['username']}:{pwd}@" if pwd else f"{proxy['username']}@"
            proxy_url = f"{proxy['proxy_type']}://{auth}{proxy['host']}:{proxy['port']}"

            # Attempt health check
            check_url = "https://httpbin.org/ip"
            start = time.time()
            status = "success"
            error_msg = ""
            external_ip = ""
            latency = 0

            try:
                import httpx
                with httpx.Client(proxy=proxy_url, timeout=10) as client:
                    resp = client.get(check_url)
                    latency = int((time.time() - start) * 1000)
                    if resp.status_code == 200:
                        try:
                            external_ip = resp.json().get("origin", "")
                        except Exception:
                            external_ip = ""
                    else:
                        status = "failure"
                        error_msg = f"HTTP {resp.status_code}"
            except Exception as e:
                latency = int((time.time() - start) * 1000)
                status = "failure"
                error_msg = str(e)[:500]

            now = _now()

            # Log the check
            conn.execute(
                """INSERT INTO proxy_check_logs
                   (proxy_id, status, latency_ms, check_url, error_message, external_ip, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (proxy_id, status, latency, check_url, error_msg, external_ip, now),
            )

            # Update proxy stats
            total_req = proxy["total_requests"] + 1
            total_fail = proxy["total_failures"] + (1 if status == "failure" else 0)
            new_success_rate = round(((total_req - total_fail) / total_req) * 100, 2)
            # Running average for latency
            old_avg = proxy["avg_latency_ms"] or 0
            new_avg = round((old_avg * proxy["total_requests"] + latency) / total_req, 2) if status == "success" else old_avg

            updates = {
                "total_requests": total_req,
                "total_failures": total_fail,
                "success_rate": new_success_rate,
                "avg_latency_ms": new_avg,
                "last_check_at": now,
            }
            if status == "success":
                updates["last_success_at"] = now
                updates["status"] = "active"
            else:
                updates["last_failure_at"] = now
                updates["last_failure_reason"] = error_msg
                # Mark as failed if success rate drops below 50%
                if new_success_rate < 50:
                    updates["status"] = "failed"

            set_parts = [f"{k} = ?" for k in updates.keys()]
            set_parts.append("updated_at = ?")
            vals = list(updates.values()) + [now, proxy_id]
            conn.execute(
                f"UPDATE proxies SET {', '.join(set_parts)} WHERE id = ?", vals
            )
            conn.commit()

            return {
                "proxy_id": proxy_id,
                "status": status,
                "latency_ms": latency,
                "external_ip": external_ip,
                "error": error_msg,
                "success_rate": new_success_rate,
            }
        finally:
            conn.close()

    def check_all_health(self) -> List[dict]:
        """Health check all active proxies in parallel."""
        conn = get_connection(self.db_path)
        try:
            rows = conn.execute(
                "SELECT id FROM proxies WHERE status IN ('active', 'testing')"
            ).fetchall()
            proxy_ids = [r["id"] for r in rows]
        finally:
            conn.close()

        if not proxy_ids:
            return []

        from concurrent.futures import ThreadPoolExecutor, as_completed
        results = []
        with ThreadPoolExecutor(max_workers=min(len(proxy_ids), 10)) as executor:
            futures = {executor.submit(self.check_health, pid): pid for pid in proxy_ids}
            for future in as_completed(futures):
                try:
                    results.append(future.result())
                except Exception:
                    pass
        return results

    # ── Assignment methods ──

    def assign_to_account(self, account_id: int, proxy_id: int = None,
                          proxy_group_id: int = None,
                          assignment_type: str = "direct") -> int:
        """Create or update proxy assignment for an account."""
        conn = get_connection(self.db_path)
        try:
            now = _now()
            # Deactivate existing assignments
            conn.execute(
                "UPDATE account_proxy_assignments SET is_active = 0, updated_at = ? WHERE account_id = ?",
                (now, account_id),
            )
            # Create new assignment
            cur = conn.execute(
                """INSERT INTO account_proxy_assignments
                   (account_id, proxy_id, proxy_group_id, assignment_type,
                    is_active, created_at, updated_at)
                   VALUES (?, ?, ?, ?, 1, ?, ?)""",
                (account_id, proxy_id, proxy_group_id, assignment_type, now, now),
            )
            # Update accounts.proxy_id for direct assignments
            if assignment_type == "direct" and proxy_id:
                conn.execute(
                    "UPDATE accounts SET proxy_id = ?, updated_at = ? WHERE id = ?",
                    (proxy_id, now, account_id),
                )
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()

    def get_assignment(self, account_id: int) -> Optional[dict]:
        """Get current active proxy assignment for an account."""
        conn = get_connection(self.db_path)
        try:
            row = conn.execute(
                """SELECT apa.*, p.host, p.port, p.proxy_type, p.status as proxy_status,
                          pg.name as group_name, pg.rotation_strategy
                   FROM account_proxy_assignments apa
                   LEFT JOIN proxies p ON apa.proxy_id = p.id
                   LEFT JOIN proxy_groups pg ON apa.proxy_group_id = pg.id
                   WHERE apa.account_id = ? AND apa.is_active = 1
                   ORDER BY apa.created_at DESC LIMIT 1""",
                (account_id,),
            ).fetchone()
            return _row_to_dict(row) if row else None
        finally:
            conn.close()

    def remove_assignment(self, account_id: int) -> bool:
        """Deactivate all proxy assignments for an account."""
        conn = get_connection(self.db_path)
        try:
            now = _now()
            cur = conn.execute(
                "UPDATE account_proxy_assignments SET is_active = 0, updated_at = ? WHERE account_id = ? AND is_active = 1",
                (now, account_id),
            )
            conn.execute(
                "UPDATE accounts SET proxy_id = NULL, updated_at = ? WHERE id = ?",
                (now, account_id),
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def get_next_proxy(self, proxy_group_id: int) -> Optional[dict]:
        """Get next proxy from a group based on its rotation strategy."""
        conn = get_connection(self.db_path)
        try:
            # Get group strategy
            group = conn.execute(
                "SELECT * FROM proxy_groups WHERE id = ?", (proxy_group_id,)
            ).fetchone()
            if group is None:
                return None
            strategy = group["rotation_strategy"]

            # Get active proxies in group
            rows = conn.execute(
                "SELECT * FROM proxies WHERE proxy_group_id = ? AND status = 'active' ORDER BY id",
                (proxy_group_id,),
            ).fetchall()
            if not rows:
                return None

            proxies = [_row_to_dict(r) for r in rows]

            if strategy == "random":
                chosen = random.choice(proxies)
            elif strategy == "least_used":
                chosen = min(proxies, key=lambda p: p["total_requests"])
            elif strategy == "sticky":
                chosen = proxies[0]  # Always the first active one
            else:  # round_robin
                # Least-used round-robin: pick proxy with fewest total_requests
                # This achieves fair distribution equivalent to true round-robin
                chosen = min(proxies, key=lambda p: p["total_requests"])

            chosen["has_password"] = bool(chosen.get("password_encrypted"))
            chosen.pop("password_encrypted", None)
            chosen["is_sticky"] = bool(chosen.get("is_sticky", 0))
            return chosen
        finally:
            conn.close()

    def record_usage(self, proxy_id: int, success: bool, latency_ms: int = 0) -> bool:
        """Update proxy usage statistics after a request."""
        conn = get_connection(self.db_path)
        try:
            now = _now()
            row = conn.execute("SELECT * FROM proxies WHERE id = ?", (proxy_id,)).fetchone()
            if row is None:
                return False
            p = _row_to_dict(row)
            total_req = p["total_requests"] + 1
            total_fail = p["total_failures"] + (0 if success else 1)
            rate = round(((total_req - total_fail) / total_req) * 100, 2)
            old_avg = p["avg_latency_ms"] or 0
            new_avg = round((old_avg * p["total_requests"] + latency_ms) / total_req, 2) if success else old_avg

            sets = "total_requests=?, total_failures=?, success_rate=?, avg_latency_ms=?, updated_at=?"
            params = [total_req, total_fail, rate, new_avg, now]
            if success:
                sets += ", last_success_at=?"
                params.append(now)
            else:
                sets += ", last_failure_at=?"
                params.append(now)
            params.append(proxy_id)
            conn.execute(f"UPDATE proxies SET {sets} WHERE id = ?", params)
            conn.commit()
            return True
        finally:
            conn.close()

    def get_stats(self) -> dict:
        """Get proxy pool summary statistics."""
        conn = get_connection(self.db_path)
        try:
            total = conn.execute("SELECT COUNT(*) as cnt FROM proxies").fetchone()["cnt"]
            by_status = {}
            for row in conn.execute("SELECT status, COUNT(*) as cnt FROM proxies GROUP BY status").fetchall():
                by_status[row["status"]] = row["cnt"]
            by_type = {}
            for row in conn.execute("SELECT proxy_type, COUNT(*) as cnt FROM proxies GROUP BY proxy_type").fetchall():
                by_type[row["proxy_type"]] = row["cnt"]
            by_region = {}
            for row in conn.execute("SELECT region, COUNT(*) as cnt FROM proxies WHERE region != '' GROUP BY region").fetchall():
                by_region[row["region"]] = row["cnt"]
            avg_latency = conn.execute(
                "SELECT AVG(avg_latency_ms) as avg_lat FROM proxies WHERE status = 'active'"
            ).fetchone()["avg_lat"] or 0
            avg_success = conn.execute(
                "SELECT AVG(success_rate) as avg_sr FROM proxies WHERE total_requests > 0"
            ).fetchone()["avg_sr"] or 0
            assigned = conn.execute(
                "SELECT COUNT(DISTINCT account_id) as cnt FROM account_proxy_assignments WHERE is_active = 1"
            ).fetchone()["cnt"]
            total_groups = conn.execute("SELECT COUNT(*) as cnt FROM proxy_groups").fetchone()["cnt"]

            return {
                "total_proxies": total,
                "total_groups": total_groups,
                "by_status": by_status,
                "by_type": by_type,
                "by_region": by_region,
                "avg_latency_ms": round(avg_latency, 2),
                "avg_success_rate": round(avg_success, 2),
                "assigned_accounts": assigned,
            }
        finally:
            conn.close()

    def get_check_logs(self, proxy_id: int, limit: int = 20) -> List[dict]:
        """Get recent health check logs for a proxy."""
        conn = get_connection(self.db_path)
        try:
            rows = conn.execute(
                "SELECT * FROM proxy_check_logs WHERE proxy_id = ? ORDER BY created_at DESC LIMIT ?",
                (proxy_id, limit),
            ).fetchall()
            return [_row_to_dict(r) for r in rows]
        finally:
            conn.close()

    def import_bulk(self, proxies_list: list) -> dict:
        """Bulk import proxies from list of dicts.
        Each dict should have: proxy_type, host, port, and optionally username, password, region, etc.
        Also supports string format: type://user:pass@host:port"""
        created = 0
        errors = []
        for i, item in enumerate(proxies_list):
            try:
                if isinstance(item, str):
                    item = self._parse_proxy_string(item)
                if not item.get("host") or not item.get("port"):
                    errors.append({"index": i, "error": "host and port required"})
                    continue
                self.create(item)
                created += 1
            except Exception as e:
                errors.append({"index": i, "error": str(e)})
        return {"created": created, "errors": errors, "total": len(proxies_list)}

    def _parse_proxy_string(self, s: str) -> dict:
        """Parse proxy string format: type://user:pass@host:port"""
        result = {"proxy_type": "http"}
        s = s.strip()
        if "://" in s:
            result["proxy_type"], s = s.split("://", 1)
        if "@" in s:
            auth, s = s.rsplit("@", 1)
            if ":" in auth:
                result["username"], result["password"] = auth.split(":", 1)
            else:
                result["username"] = auth
        if ":" in s:
            host, port = s.rsplit(":", 1)
            result["host"] = host
            result["port"] = int(port)
        else:
            result["host"] = s
            result["port"] = 0
        return result
