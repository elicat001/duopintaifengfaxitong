import sqlite3
import os


def get_connection(db_path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


_SAFE_ALTER_WHITELIST = {
    ("accounts", "proxy_id"), ("accounts", "login_status"), ("accounts", "last_login_at"),
    ("accounts", "last_login_check_at"), ("accounts", "login_fail_count"), ("accounts", "risk_score"),
    ("accounts", "fingerprint_config"), ("accounts", "notes"), ("accounts", "cookie_updated_at"),
    ("accounts", "warming_stage"), ("accounts", "warming_started_at"), ("contents", "body"),
}

def _safe_add_column(conn, table, column, column_def):
    if (table, column) not in _SAFE_ALTER_WHITELIST:
        raise ValueError(f"Disallowed ALTER TABLE: {table}.{column}")
    try:
        conn.execute(f"ALTER TABLE [{table}] ADD COLUMN [{column}] {column_def}")
    except Exception:
        pass  # Column already exists


def init_database(db_path: str) -> None:
    conn = get_connection(db_path)
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS account_groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT DEFAULT ''
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            platform TEXT NOT NULL,
            handle TEXT NOT NULL,
            display_name TEXT DEFAULT '',
            group_id INTEGER,
            status TEXT DEFAULT 'active',
            daily_limit INTEGER DEFAULT 10,
            hourly_limit INTEGER DEFAULT 3,
            last_success_at TEXT,
            executor_account_ref TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (group_id) REFERENCES account_groups(id)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS contents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            topic TEXT DEFAULT '',
            language TEXT DEFAULT 'zh',
            content_type TEXT DEFAULT 'image_single',
            status TEXT DEFAULT 'draft',
            tags TEXT DEFAULT '[]',
            copyright_flags TEXT DEFAULT '{}',
            dedupe_hash TEXT DEFAULT '',
            created_by INTEGER,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS assets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            asset_type TEXT DEFAULT 'image',
            storage_url TEXT DEFAULT '',
            sha256 TEXT DEFAULT '',
            width INTEGER DEFAULT 0,
            height INTEGER DEFAULT 0,
            duration_sec REAL,
            filesize_bytes INTEGER DEFAULT 0,
            meta TEXT DEFAULT '{}',
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS variants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content_id INTEGER NOT NULL,
            platform TEXT,
            caption TEXT DEFAULT '',
            headline TEXT DEFAULT '',
            hashtags TEXT DEFAULT '[]',
            cover_asset_id INTEGER,
            media_asset_ids TEXT DEFAULT '[]',
            variant_fingerprint TEXT DEFAULT '',
            status TEXT DEFAULT 'ready',
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (content_id) REFERENCES contents(id),
            FOREIGN KEY (cover_asset_id) REFERENCES assets(id)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS policies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            scope_type TEXT DEFAULT 'group',
            scope_id TEXT DEFAULT '',
            platform TEXT DEFAULT 'instagram',
            posting_windows TEXT DEFAULT '[]',
            max_per_day INTEGER DEFAULT 10,
            max_per_hour INTEGER DEFAULT 3,
            min_interval_minutes INTEGER DEFAULT 30,
            min_stagger_minutes INTEGER DEFAULT 5,
            cooldown_days INTEGER DEFAULT 7,
            topic_mix TEXT DEFAULT '{}',
            enabled INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER NOT NULL,
            content_id INTEGER NOT NULL,
            variant_id INTEGER,
            scheduled_at TEXT,
            state TEXT DEFAULT 'draft',
            attempt_count INTEGER DEFAULT 0,
            max_attempts INTEGER DEFAULT 5,
            next_run_at TEXT,
            platform_post_id TEXT DEFAULT '',
            platform_post_url TEXT DEFAULT '',
            idempotency_key TEXT UNIQUE,
            last_error_code TEXT DEFAULT '',
            last_error_message TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (account_id) REFERENCES accounts(id),
            FOREIGN KEY (content_id) REFERENCES contents(id),
            FOREIGN KEY (variant_id) REFERENCES variants(id)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS job_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER NOT NULL,
            step TEXT DEFAULT 'publish',
            status TEXT DEFAULT 'ok',
            error_code TEXT DEFAULT '',
            message TEXT DEFAULT '',
            raw TEXT DEFAULT '{}',
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (job_id) REFERENCES jobs(id)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER NOT NULL,
            platform_post_id TEXT DEFAULT '',
            captured_at TEXT DEFAULT (datetime('now')),
            views INTEGER DEFAULT 0,
            likes INTEGER DEFAULT 0,
            comments INTEGER DEFAULT 0,
            shares INTEGER DEFAULT 0,
            extra TEXT DEFAULT '{}',
            FOREIGN KEY (job_id) REFERENCES jobs(id)
        )
    """)

    # ── AI Module Tables ────────────────────────────────────────────

    c.execute("""
        CREATE TABLE IF NOT EXISTS ai_configs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            config_key TEXT NOT NULL UNIQUE,
            provider TEXT DEFAULT 'anthropic',
            model TEXT DEFAULT 'claude-sonnet-4-20250514',
            api_key_encrypted TEXT DEFAULT '',
            base_url TEXT DEFAULT '',
            max_tokens INTEGER DEFAULT 4096,
            temperature REAL DEFAULT 0.7,
            system_prompt TEXT DEFAULT '',
            prompt_templates TEXT DEFAULT '{}',
            rate_limit_rpm INTEGER DEFAULT 60,
            daily_token_budget INTEGER DEFAULT 500000,
            enabled INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS trends (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            source_url TEXT DEFAULT '',
            title TEXT NOT NULL,
            description TEXT DEFAULT '',
            keywords TEXT DEFAULT '[]',
            category TEXT DEFAULT '',
            region TEXT DEFAULT 'global',
            language TEXT DEFAULT 'zh',
            heat_score REAL DEFAULT 0.0,
            trend_status TEXT DEFAULT 'active',
            related_topics TEXT DEFAULT '[]',
            raw_data TEXT DEFAULT '{}',
            discovered_at TEXT DEFAULT (datetime('now')),
            expires_at TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS topic_suggestions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic TEXT NOT NULL,
            description TEXT DEFAULT '',
            reasoning TEXT DEFAULT '',
            source_type TEXT DEFAULT 'ai',
            source_trend_id INTEGER,
            keywords TEXT DEFAULT '[]',
            suggested_tags TEXT DEFAULT '[]',
            suggested_content_type TEXT DEFAULT 'image_single',
            suggested_platforms TEXT DEFAULT '[]',
            score REAL DEFAULT 0.0,
            historical_performance REAL DEFAULT 0.0,
            trend_relevance REAL DEFAULT 0.0,
            freshness_score REAL DEFAULT 0.0,
            status TEXT DEFAULT 'pending',
            used_content_id INTEGER,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (source_trend_id) REFERENCES trends(id),
            FOREIGN KEY (used_content_id) REFERENCES contents(id)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS generation_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_type TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            priority INTEGER DEFAULT 5,
            input_data TEXT DEFAULT '{}',
            output_data TEXT DEFAULT '{}',
            content_id INTEGER,
            suggestion_id INTEGER,
            pipeline_run_id INTEGER,
            provider TEXT DEFAULT 'anthropic',
            model TEXT DEFAULT '',
            prompt_used TEXT DEFAULT '',
            started_at TEXT,
            completed_at TEXT,
            error_message TEXT DEFAULT '',
            retry_count INTEGER DEFAULT 0,
            max_retries INTEGER DEFAULT 3,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (content_id) REFERENCES contents(id),
            FOREIGN KEY (suggestion_id) REFERENCES topic_suggestions(id)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS generation_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            generation_task_id INTEGER NOT NULL,
            input_tokens INTEGER DEFAULT 0,
            output_tokens INTEGER DEFAULT 0,
            total_tokens INTEGER DEFAULT 0,
            estimated_cost_usd REAL DEFAULT 0.0,
            latency_ms INTEGER DEFAULT 0,
            quality_score REAL,
            content_safety_flag INTEGER DEFAULT 0,
            safety_details TEXT DEFAULT '',
            raw_response TEXT DEFAULT '{}',
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (generation_task_id) REFERENCES generation_tasks(id)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS pipelines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            enabled INTEGER DEFAULT 0,
            mode TEXT DEFAULT 'semi_auto',
            auto_approve INTEGER DEFAULT 0,
            enabled_stages TEXT DEFAULT '["trend_scan","topic_select","content_gen","variant_gen","auto_review","job_dispatch"]',
            trigger_type TEXT DEFAULT 'scheduled',
            cron_expression TEXT DEFAULT '',
            trigger_config TEXT DEFAULT '{}',
            target_platforms TEXT DEFAULT '[]',
            target_account_group_ids TEXT DEFAULT '[]',
            target_topics TEXT DEFAULT '[]',
            target_languages TEXT DEFAULT '["zh"]',
            target_content_types TEXT DEFAULT '["image_single"]',
            max_daily_generations INTEGER DEFAULT 20,
            max_daily_tokens INTEGER DEFAULT 500000,
            max_daily_cost_usd REAL DEFAULT 10.0,
            ai_config_id INTEGER,
            total_runs INTEGER DEFAULT 0,
            last_run_at TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (ai_config_id) REFERENCES ai_configs(id)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS pipeline_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pipeline_id INTEGER NOT NULL,
            status TEXT DEFAULT 'running',
            current_stage TEXT DEFAULT '',
            triggered_by TEXT DEFAULT 'scheduled',
            trigger_detail TEXT DEFAULT '',
            trends_found INTEGER DEFAULT 0,
            topics_suggested INTEGER DEFAULT 0,
            contents_generated INTEGER DEFAULT 0,
            variants_generated INTEGER DEFAULT 0,
            jobs_created INTEGER DEFAULT 0,
            total_tokens_used INTEGER DEFAULT 0,
            total_cost_usd REAL DEFAULT 0.0,
            error_message TEXT DEFAULT '',
            stage_logs TEXT DEFAULT '[]',
            started_at TEXT DEFAULT (datetime('now')),
            completed_at TEXT,
            FOREIGN KEY (pipeline_id) REFERENCES pipelines(id)
        )
    """)

    # ── Account Management Tables ─────────────────────────────────────

    c.execute("""
        CREATE TABLE IF NOT EXISTS proxy_groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            rotation_strategy TEXT DEFAULT 'round_robin',
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS proxies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT DEFAULT '',
            proxy_type TEXT NOT NULL DEFAULT 'http',
            host TEXT NOT NULL,
            port INTEGER NOT NULL,
            username TEXT DEFAULT '',
            password_encrypted TEXT DEFAULT '',
            proxy_group_id INTEGER,
            region TEXT DEFAULT '',
            provider TEXT DEFAULT '',
            status TEXT DEFAULT 'active',
            is_sticky INTEGER DEFAULT 0,
            avg_latency_ms REAL DEFAULT 0.0,
            success_rate REAL DEFAULT 100.0,
            total_requests INTEGER DEFAULT 0,
            total_failures INTEGER DEFAULT 0,
            last_check_at TEXT,
            last_success_at TEXT,
            last_failure_at TEXT,
            last_failure_reason TEXT DEFAULT '',
            bandwidth_used_mb REAL DEFAULT 0.0,
            max_bandwidth_mb REAL DEFAULT 0.0,
            notes TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (proxy_group_id) REFERENCES proxy_groups(id)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS account_proxy_assignments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER NOT NULL,
            proxy_id INTEGER,
            proxy_group_id INTEGER,
            assignment_type TEXT DEFAULT 'direct',
            is_active INTEGER DEFAULT 1,
            last_rotation_at TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE,
            FOREIGN KEY (proxy_id) REFERENCES proxies(id) ON DELETE SET NULL,
            FOREIGN KEY (proxy_group_id) REFERENCES proxy_groups(id) ON DELETE SET NULL
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS account_credentials (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER NOT NULL,
            credential_type TEXT NOT NULL DEFAULT 'cookie',
            credential_data_encrypted TEXT DEFAULT '',
            is_active INTEGER DEFAULT 1,
            expires_at TEXT,
            last_refreshed_at TEXT,
            last_validated_at TEXT,
            validation_status TEXT DEFAULT 'unknown',
            notes TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS account_login_status (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER NOT NULL UNIQUE,
            login_state TEXT DEFAULT 'unknown',
            health_score REAL DEFAULT 0.0,
            consecutive_failures INTEGER DEFAULT 0,
            total_login_attempts INTEGER DEFAULT 0,
            total_login_successes INTEGER DEFAULT 0,
            last_login_at TEXT,
            last_login_check_at TEXT,
            last_failure_reason TEXT DEFAULT '',
            last_state_change_at TEXT,
            check_interval_minutes INTEGER DEFAULT 30,
            alert_sent INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS login_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER NOT NULL,
            action TEXT DEFAULT 'login_check',
            status TEXT DEFAULT 'success',
            previous_state TEXT DEFAULT '',
            new_state TEXT DEFAULT '',
            failure_reason TEXT DEFAULT '',
            ip_used TEXT DEFAULT '',
            response_code INTEGER,
            response_snippet TEXT DEFAULT '',
            duration_ms INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS proxy_check_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            proxy_id INTEGER NOT NULL,
            status TEXT DEFAULT 'success',
            latency_ms INTEGER DEFAULT 0,
            check_url TEXT DEFAULT '',
            error_message TEXT DEFAULT '',
            external_ip TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (proxy_id) REFERENCES proxies(id) ON DELETE CASCADE
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS browser_login_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER NOT NULL,
            login_method TEXT NOT NULL DEFAULT 'cookie_import',
            status TEXT NOT NULL DEFAULT 'pending',
            progress_message TEXT DEFAULT '',
            screenshot_path TEXT DEFAULT '',
            qr_code_path TEXT DEFAULT '',
            error_message TEXT DEFAULT '',
            platform TEXT DEFAULT '',
            started_at TEXT,
            completed_at TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
        )
    """)

    # Migrate accounts table with new columns
    _safe_add_column(conn, "accounts", "proxy_id", "INTEGER REFERENCES proxies(id)")
    _safe_add_column(conn, "accounts", "login_status", "TEXT DEFAULT 'unknown'")
    _safe_add_column(conn, "accounts", "last_login_at", "TEXT")
    _safe_add_column(conn, "accounts", "last_login_check_at", "TEXT")
    _safe_add_column(conn, "accounts", "login_fail_count", "INTEGER DEFAULT 0")
    _safe_add_column(conn, "accounts", "risk_score", "REAL DEFAULT 0.0")
    _safe_add_column(conn, "accounts", "fingerprint_config", "TEXT DEFAULT '{}'")
    _safe_add_column(conn, "accounts", "notes", "TEXT DEFAULT ''")
    _safe_add_column(conn, "accounts", "cookie_updated_at", "TEXT")
    _safe_add_column(conn, "accounts", "warming_stage", "INTEGER DEFAULT 0")
    _safe_add_column(conn, "accounts", "warming_started_at", "TEXT")

    # ── Agent tables (schedule_plans, performance_records) ──────────

    c.execute("""
        CREATE TABLE IF NOT EXISTS schedule_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content_id INTEGER NOT NULL REFERENCES contents(id) ON DELETE CASCADE,
            score REAL DEFAULT 0.0,
            frequency TEXT DEFAULT 'normal',
            next_publish_at TEXT,
            last_published_at TEXT,
            publish_count INTEGER DEFAULT 0,
            updated_at TEXT DEFAULT (datetime('now'))
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS performance_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content_id INTEGER NOT NULL REFERENCES contents(id) ON DELETE CASCADE,
            likes INTEGER DEFAULT 0,
            comments INTEGER DEFAULT 0,
            shares INTEGER DEFAULT 0,
            views INTEGER DEFAULT 0,
            recorded_at TEXT DEFAULT (datetime('now'))
        )
    """)

    # contents.body column used by agents/content_manager
    _safe_add_column(conn, "contents", "body", "TEXT DEFAULT ''")

    # ── Indexes ──────────────────────────────────────────────────────

    c.execute("CREATE INDEX IF NOT EXISTS idx_schedule_plans_content ON schedule_plans(content_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_schedule_plans_next ON schedule_plans(next_publish_at)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_perf_records_content ON performance_records(content_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_accounts_platform ON accounts(platform)")
    c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_accounts_platform_handle ON accounts(platform, handle)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_accounts_group ON accounts(group_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_contents_status ON contents(status)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_variants_content ON variants(content_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_jobs_state ON jobs(state)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_jobs_account ON jobs(account_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_jobs_scheduled ON jobs(scheduled_at)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_job_logs_job ON job_logs(job_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_metrics_job ON metrics(job_id)")

    c.execute("CREATE INDEX IF NOT EXISTS idx_trends_status ON trends(trend_status)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_trends_heat ON trends(heat_score)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_suggestions_status ON topic_suggestions(status)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_suggestions_score ON topic_suggestions(score)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_gen_tasks_status ON generation_tasks(status)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_gen_tasks_type ON generation_tasks(task_type)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_gen_logs_task ON generation_logs(generation_task_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_pipeline_runs_pipeline ON pipeline_runs(pipeline_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_pipeline_runs_status ON pipeline_runs(status)")

    c.execute("CREATE INDEX IF NOT EXISTS idx_accounts_login_status ON accounts(login_status)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_accounts_risk_score ON accounts(risk_score)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_accounts_proxy ON accounts(proxy_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_credentials_account ON account_credentials(account_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_credentials_type ON account_credentials(credential_type)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_credentials_active ON account_credentials(is_active)")
    c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_login_status_account ON account_login_status(account_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_login_status_state ON account_login_status(login_state)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_login_logs_account ON login_logs(account_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_login_logs_created ON login_logs(created_at)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_login_logs_status ON login_logs(status)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_proxies_status ON proxies(status)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_proxies_group ON proxies(proxy_group_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_proxies_region ON proxies(region)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_proxy_assign_account ON account_proxy_assignments(account_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_proxy_assign_proxy ON account_proxy_assignments(proxy_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_proxy_logs_proxy ON proxy_check_logs(proxy_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_proxy_logs_created ON proxy_check_logs(created_at)")

    c.execute("CREATE INDEX IF NOT EXISTS idx_browser_sessions_account ON browser_login_sessions(account_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_browser_sessions_status ON browser_login_sessions(status)")

    # Composite indexes for common multi-column queries
    c.execute("CREATE INDEX IF NOT EXISTS idx_login_logs_account_status ON login_logs(account_id, status)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_login_logs_account_created ON login_logs(account_id, created_at)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_credentials_account_active ON account_credentials(account_id, is_active)")

    # Job executor: find queued jobs and rate-limit checks
    c.execute("CREATE INDEX IF NOT EXISTS idx_jobs_state_updated ON jobs(state, updated_at)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_jobs_account_state ON jobs(account_id, state)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_jobs_content ON jobs(content_id)")
    # Content/variant lookups
    c.execute("CREATE INDEX IF NOT EXISTS idx_contents_type ON contents(content_type)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_variants_platform ON variants(platform)")
    # Proxy assignments
    c.execute("CREATE INDEX IF NOT EXISTS idx_proxy_assign_active ON account_proxy_assignments(is_active)")

    conn.commit()
    conn.close()
