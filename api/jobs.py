"""
Blueprint for Job, JobLog, and Metric REST APIs.
"""

from flask import Blueprint, request, jsonify
from config import DB_PATH
from services.job_service import JobService, JobLogService, MetricService
from api.auth import require_auth

jobs_bp = Blueprint("jobs", __name__)
job_svc = JobService(DB_PATH)
log_svc = JobLogService(DB_PATH)
metric_svc = MetricService(DB_PATH)


# ── Job CRUD ─────────────────────────────────────────────────────────────


@jobs_bp.route("/api/jobs", methods=["POST"])
@require_auth
def create_job():
    """Create a single job."""
    try:
        data = request.get_json(force=True)
        if not data or not data.get("account_id") or not data.get("content_id"):
            return jsonify({"error": "account_id and content_id are required"}), 400

        if not isinstance(data["account_id"], int) or data["account_id"] < 1:
            return jsonify({"error": "account_id must be a positive integer"}), 400
        if not isinstance(data["content_id"], int) or data["content_id"] < 1:
            return jsonify({"error": "content_id must be a positive integer"}), 400

        job_id = job_svc.create(data)
        job = job_svc.get(job_id)
        return jsonify(job), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@jobs_bp.route("/api/jobs/batch", methods=["POST"])
@require_auth
def batch_create_jobs():
    """Batch-create jobs: one job per account_id for a given content_id."""
    try:
        data = request.get_json(force=True)
        if not data or not data.get("content_id") or not data.get("account_ids"):
            return jsonify({"error": "content_id and account_ids are required"}), 400

        account_ids = data["account_ids"]
        if not isinstance(account_ids, list) or len(account_ids) == 0:
            return jsonify({"error": "account_ids must be a non-empty list"}), 400

        created_ids = job_svc.batch_create(
            content_id=data["content_id"],
            account_ids=account_ids,
            variant_id=data.get("variant_id"),
            scheduled_at=data.get("scheduled_at"),
        )
        return jsonify({"created_ids": created_ids, "count": len(created_ids)}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@jobs_bp.route("/api/jobs", methods=["GET"])
@require_auth
def list_jobs():
    """List jobs with optional filters: state, account_id, content_id, limit."""
    try:
        state = request.args.get("state")
        account_id = request.args.get("account_id", type=int)
        content_id = request.args.get("content_id", type=int)
        limit = request.args.get("limit", 100, type=int)
        limit = min(limit, 500)  # Cap at 500
        offset = request.args.get("offset", 0, type=int)

        items = job_svc.list_all(
            state=state,
            account_id=account_id,
            content_id=content_id,
            limit=limit,
            offset=offset,
        )
        return jsonify(items), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@jobs_bp.route("/api/jobs/<int:job_id>", methods=["GET"])
@require_auth
def get_job(job_id):
    """Get a single job with its logs and latest metrics."""
    try:
        job = job_svc.get(job_id)
        if job is None:
            return jsonify({"error": "job not found"}), 404

        logs = log_svc.list_by_job(job_id)
        latest_metric = metric_svc.get_latest(job_id)

        job["logs"] = logs
        job["latest_metric"] = latest_metric
        return jsonify(job), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── State transitions ────────────────────────────────────────────────────


@jobs_bp.route("/api/jobs/<int:job_id>/transition", methods=["POST"])
@require_auth
def transition_job(job_id):
    """Transition a job to a new state."""
    try:
        data = request.get_json(force=True)
        if not data or not data.get("state"):
            return jsonify({"error": "state is required"}), 400

        new_state = data["state"]
        ok = job_svc.transition(job_id, new_state)
        if not ok:
            return jsonify({"error": "invalid transition or job not found"}), 400

        updated = job_svc.get(job_id)
        return jsonify(updated), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@jobs_bp.route("/api/jobs/<int:job_id>/cancel", methods=["POST"])
@require_auth
def cancel_job(job_id):
    """Cancel a job."""
    try:
        ok = job_svc.cancel(job_id)
        if not ok:
            return jsonify({"error": "cannot cancel job (invalid state or not found)"}), 400

        updated = job_svc.get(job_id)
        return jsonify(updated), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@jobs_bp.route("/api/jobs/<int:job_id>/retry", methods=["POST"])
@require_auth
def retry_job(job_id):
    """Retry a failed job (failed_retryable -> queued)."""
    try:
        ok = job_svc.retry(job_id)
        if not ok:
            return jsonify({"error": "cannot retry job (invalid state, max attempts reached, or not found)"}), 400

        updated = job_svc.get(job_id)
        return jsonify(updated), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@jobs_bp.route("/api/jobs/<int:job_id>", methods=["DELETE"])
@require_auth
def delete_job(job_id):
    """Delete a job."""
    try:
        ok = job_svc.delete(job_id)
        if not ok:
            return jsonify({"error": "job not found"}), 404
        return jsonify({"message": "deleted"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Job Logs ─────────────────────────────────────────────────────────────


@jobs_bp.route("/api/jobs/<int:job_id>/logs", methods=["POST"])
@require_auth
def add_job_log(job_id):
    """Add a log entry for a job."""
    try:
        # Verify the job exists
        job = job_svc.get(job_id)
        if job is None:
            return jsonify({"error": "job not found"}), 404

        data = request.get_json(force=True)
        if not data or not data.get("step"):
            return jsonify({"error": "step is required"}), 400

        data["job_id"] = job_id
        log_id = log_svc.add(data)
        return jsonify({"id": log_id, "job_id": job_id}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@jobs_bp.route("/api/jobs/<int:job_id>/logs", methods=["GET"])
@require_auth
def get_job_logs(job_id):
    """Get all log entries for a job."""
    try:
        job = job_svc.get(job_id)
        if job is None:
            return jsonify({"error": "job not found"}), 404

        logs = log_svc.list_by_job(job_id)
        return jsonify(logs), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Metrics ──────────────────────────────────────────────────────────────


@jobs_bp.route("/api/jobs/<int:job_id>/metrics", methods=["POST"])
@require_auth
def record_metric(job_id):
    """Record a metrics snapshot for a job."""
    try:
        job = job_svc.get(job_id)
        if job is None:
            return jsonify({"error": "job not found"}), 404

        data = request.get_json(force=True)
        if not data:
            return jsonify({"error": "request body is required"}), 400

        data["job_id"] = job_id
        metric_id = metric_svc.record(data)
        return jsonify({"id": metric_id, "job_id": job_id}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@jobs_bp.route("/api/jobs/<int:job_id>/metrics", methods=["GET"])
@require_auth
def get_job_metrics(job_id):
    """Get all metrics snapshots for a job."""
    try:
        job = job_svc.get(job_id)
        if job is None:
            return jsonify({"error": "job not found"}), 404

        metrics = metric_svc.list_by_job(job_id)
        return jsonify(metrics), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
