"""Generic Task Engine - unified browser automation task execution.

Supports pluggable task handlers: publish, reply, scrape, video_gen, etc.
Each handler implements BaseTaskHandler interface.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
import json
import logging
import threading
import time
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class TaskStep:
    """A single step in task execution."""
    name: str
    status: str = "pending"  # pending/running/success/failed/skipped
    message: str = ""
    screenshot_path: str = ""
    duration_ms: int = 0
    data: dict = field(default_factory=dict)


@dataclass
class TaskContext:
    """Execution context passed to handlers."""
    task_id: int
    task_type: str
    account_id: int
    platform: str
    params: dict = field(default_factory=dict)
    page: Any = None  # Playwright page
    browser_instance: Any = None
    steps: List[TaskStep] = field(default_factory=list)
    result: dict = field(default_factory=dict)
    start_time: float = 0.0

    def add_step(self, name: str, status: str = "running", message: str = "") -> TaskStep:
        step = TaskStep(name=name, status=status, message=message)
        self.steps.append(step)
        return step

    def complete_step(self, step: TaskStep, status: str = "success", message: str = ""):
        step.status = status
        step.message = message

    @property
    def elapsed_ms(self) -> int:
        return int((time.time() - self.start_time) * 1000) if self.start_time else 0


class BaseTaskHandler(ABC):
    """Interface for task type handlers."""

    TASK_TYPE: str = ""  # e.g. "publish", "reply", "video_gen"
    DESCRIPTION: str = ""

    @abstractmethod
    async def validate(self, ctx: TaskContext) -> bool:
        """Validate task parameters before execution. Return True if valid."""
        pass

    @abstractmethod
    async def execute(self, ctx: TaskContext) -> bool:
        """Execute the task. Return True on success."""
        pass

    async def on_success(self, ctx: TaskContext):
        """Called after successful execution. Override for cleanup/logging."""
        pass

    async def on_failure(self, ctx: TaskContext, error: str):
        """Called after failed execution. Override for error handling."""
        pass


class TaskHandlerRegistry:
    """Registry for task type handlers."""

    _handlers: Dict[str, type] = {}

    @classmethod
    def register(cls, handler_class: type):
        """Register a handler class."""
        if not handler_class.TASK_TYPE:
            raise ValueError(f"Handler {handler_class.__name__} has no TASK_TYPE")
        cls._handlers[handler_class.TASK_TYPE] = handler_class
        logger.info("Registered task handler: %s -> %s",
                     handler_class.TASK_TYPE, handler_class.__name__)

    @classmethod
    def get(cls, task_type: str) -> Optional[type]:
        return cls._handlers.get(task_type)

    @classmethod
    def list_types(cls) -> list:
        return [{"type": k, "description": v.DESCRIPTION}
                for k, v in cls._handlers.items()]


class GenericTaskEngine:
    """Executes tasks using registered handlers and browser pool."""

    def __init__(self, db_path: str, browser_pool=None):
        """
        Args:
            db_path: SQLite database path
            browser_pool: BrowserPool instance (shared)
        """
        self.db_path = db_path
        self.browser_pool = browser_pool
        self._lock = threading.Lock()

    def submit_task(self, task_type: str, account_id: int, platform: str,
                    params: dict = None, scheduled_at: str = None) -> int:
        """Submit a new task. Returns task ID from generic_tasks table."""
        from models.database import get_connection
        conn = get_connection(self.db_path)
        try:
            now = datetime.now().isoformat()
            cur = conn.execute("""
                INSERT INTO generic_tasks
                    (task_type, account_id, platform, params, scheduled_at,
                     state, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (task_type, account_id, platform,
                  json.dumps(params or {}, ensure_ascii=False),
                  scheduled_at or now, "pending", now, now))
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()

    def execute_task(self, task_id: int) -> bool:
        """Execute a task by ID. Called by executor or directly."""
        from models.database import get_connection

        conn = get_connection(self.db_path)
        try:
            row = conn.execute("SELECT * FROM generic_tasks WHERE id = ?",
                              (task_id,)).fetchone()
            if not row:
                return False
            task = dict(row)
        finally:
            conn.close()

        task_type = task["task_type"]
        handler_cls = TaskHandlerRegistry.get(task_type)
        if not handler_cls:
            self._update_task(task_id, "failed", error=f"Unknown handler: {task_type}")
            return False

        handler = handler_cls()
        params = task.get("params", "{}")
        if isinstance(params, str):
            params = json.loads(params)

        ctx = TaskContext(
            task_id=task_id,
            task_type=task_type,
            account_id=task["account_id"],
            platform=task["platform"],
            params=params,
            start_time=time.time(),
        )

        # Transition to executing
        self._update_task(task_id, "executing")

        try:
            # Acquire browser
            if self.browser_pool:
                from services.credential_service import CredentialService
                from services.crypto_service import CryptoService
                from config import CREDENTIAL_ENCRYPTION_KEY

                crypto = CryptoService(CREDENTIAL_ENCRYPTION_KEY)
                cred_svc = CredentialService(self.db_path, crypto)
                cookies = cred_svc.get_cookies(ctx.account_id)

                # Get replier/publisher HOME_URL for cookie injection
                home_url = params.get("home_url", "")

                instance = self.browser_pool.acquire(
                    ctx.account_id, cookies=cookies, home_url=home_url
                )
                ctx.browser_instance = instance
                ctx.page = self.browser_pool.get_page(ctx.account_id)

            # Validate
            valid = self.browser_pool._run_async(handler.validate(ctx)) if self.browser_pool else True
            if not valid:
                self._update_task(task_id, "failed", error="Validation failed")
                return False

            # Execute
            success = self.browser_pool._run_async(handler.execute(ctx))

            if success:
                if self.browser_pool:
                    self.browser_pool._run_async(handler.on_success(ctx))
                self._update_task(task_id, "success", result=ctx.result, steps=ctx.steps)
                return True
            else:
                error = ctx.result.get("error", "Execution failed")
                if self.browser_pool:
                    self.browser_pool._run_async(handler.on_failure(ctx, error))
                self._update_task(task_id, "failed", error=error, steps=ctx.steps)
                return False

        except Exception as e:
            logger.exception("Task #%d failed", task_id)
            self._update_task(task_id, "failed", error=str(e), steps=ctx.steps)
            return False
        finally:
            if self.browser_pool and ctx.account_id:
                self.browser_pool.release(ctx.account_id)

    def get_task(self, task_id: int) -> Optional[dict]:
        from models.database import get_connection
        conn = get_connection(self.db_path)
        try:
            row = conn.execute("SELECT * FROM generic_tasks WHERE id = ?",
                              (task_id,)).fetchone()
            if not row:
                return None
            d = dict(row)
            for key in ("params", "result", "steps"):
                if isinstance(d.get(key), str):
                    try:
                        d[key] = json.loads(d[key])
                    except Exception:
                        pass
            return d
        finally:
            conn.close()

    def list_tasks(self, task_type=None, state=None, account_id=None,
                   limit=50, offset=0) -> list:
        from models.database import get_connection
        conn = get_connection(self.db_path)
        try:
            query = "SELECT * FROM generic_tasks WHERE 1=1"
            params_list = []
            if task_type:
                query += " AND task_type = ?"
                params_list.append(task_type)
            if state:
                query += " AND state = ?"
                params_list.append(state)
            if account_id:
                query += " AND account_id = ?"
                params_list.append(account_id)
            query += " ORDER BY id DESC LIMIT ? OFFSET ?"
            params_list.extend([limit, offset])
            rows = conn.execute(query, params_list).fetchall()
            results = []
            for row in rows:
                d = dict(row)
                for key in ("params", "result", "steps"):
                    if isinstance(d.get(key), str):
                        try:
                            d[key] = json.loads(d[key])
                        except Exception:
                            pass
                results.append(d)
            return results
        finally:
            conn.close()

    def cancel_task(self, task_id: int) -> bool:
        return self._update_task(task_id, "cancelled")

    def _update_task(self, task_id: int, state: str, error: str = "",
                     result: dict = None, steps: list = None) -> bool:
        from models.database import get_connection
        conn = get_connection(self.db_path)
        try:
            now = datetime.now().isoformat()
            sets = ["state = ?", "updated_at = ?"]
            params_list = [state, now]
            if error:
                sets.append("error_message = ?")
                params_list.append(error)
            if result is not None:
                sets.append("result = ?")
                params_list.append(json.dumps(result, ensure_ascii=False))
            if steps is not None:
                step_data = [{"name": s.name, "status": s.status, "message": s.message,
                              "duration_ms": s.duration_ms} for s in steps]
                sets.append("steps = ?")
                params_list.append(json.dumps(step_data, ensure_ascii=False))
            if state == "success" or state == "failed":
                sets.append("completed_at = ?")
                params_list.append(now)
            params_list.append(task_id)
            conn.execute(f"UPDATE generic_tasks SET {', '.join(sets)} WHERE id = ?",
                        params_list)
            conn.commit()
            return True
        finally:
            conn.close()
