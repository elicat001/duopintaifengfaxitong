import json, hashlib, time, logging
from datetime import datetime
from typing import List, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from models.database import get_connection
from config import DB_PATH

logger = logging.getLogger(__name__)


def _resolve_api_key(raw_key: str) -> str:
    """Resolve API key -- try to decrypt, fall back to plaintext.

    The ai_configs.api_key_encrypted field may contain either:
    - An encrypted value (base64-encoded AES-256-GCM blob)
    - A plaintext API key (if entered directly without encryption)

    This helper attempts decryption first. If that fails (e.g. the value
    is already plaintext, or decryption key mismatch), it returns the
    raw value unchanged so the caller can still use it.
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

class AIGenerationService:
    def __init__(self, db_path: str):
        self.db_path = db_path

    # ── AI API 调用 ──────────────────────────────────────────

    def call_ai(self, provider: str, model: str, api_key: str,
                system_prompt: str, user_prompt: str,
                base_url: str = "",
                max_tokens: int = 4096, temperature: float = 0.7) -> dict:
        """
        统一调用 AI API。返回 {content: str, input_tokens: int, output_tokens: int, total_tokens: int}
        支持 anthropic、openai_compatible 和 google 三种 SDK 类型。
        """
        from services.ai_provider_registry import get_sdk_type, get_default_base_url

        start_ms = int(time.time() * 1000)
        sdk_type = get_sdk_type(provider)
        effective_url = base_url or get_default_base_url(provider)

        if sdk_type == 'anthropic':
            result = self._call_anthropic(api_key, model, system_prompt, user_prompt, max_tokens, temperature, effective_url)
        elif sdk_type == 'google':
            result = self._call_google(api_key, model, system_prompt, user_prompt, max_tokens, temperature)
        else:  # openai_compatible (default)
            result = self._call_openai(api_key, model, system_prompt, user_prompt, max_tokens, temperature, effective_url)

        result['latency_ms'] = int(time.time() * 1000) - start_ms
        result['provider'] = provider
        result['model'] = model
        return result

    def _call_anthropic(self, api_key, model, system_prompt, user_prompt, max_tokens, temperature, base_url=""):
        import anthropic
        kwargs = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        client = anthropic.Anthropic(**kwargs)
        msg = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}]
        )
        return {
            "content": msg.content[0].text,
            "input_tokens": msg.usage.input_tokens,
            "output_tokens": msg.usage.output_tokens,
            "total_tokens": msg.usage.input_tokens + msg.usage.output_tokens,
        }

    def _call_openai(self, api_key, model, system_prompt, user_prompt, max_tokens, temperature, base_url=""):
        from openai import OpenAI
        kwargs = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        client = OpenAI(**kwargs)
        resp = client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]
        )
        usage = resp.usage
        total = usage.total_tokens if usage.total_tokens else (usage.prompt_tokens + usage.completion_tokens)
        return {
            "content": resp.choices[0].message.content,
            "input_tokens": usage.prompt_tokens,
            "output_tokens": usage.completion_tokens,
            "total_tokens": total,
        }

    def _call_google(self, api_key, model, system_prompt, user_prompt, max_tokens, temperature):
        try:
            from google import genai
            from google.genai import types
        except ImportError:
            raise RuntimeError("Google Gemini SDK 未安装，请运行: pip install google-genai")

        client = genai.Client(api_key=api_key)
        config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            max_output_tokens=max_tokens,
            temperature=temperature,
        )
        response = client.models.generate_content(
            model=model,
            contents=user_prompt,
            config=config,
        )
        input_tokens = getattr(response.usage_metadata, 'prompt_token_count', 0) or 0
        output_tokens = getattr(response.usage_metadata, 'candidates_token_count', 0) or 0
        return {
            "content": response.text,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        }

    # ── Prompt 构造 ──────────────────────────────────────────

    def build_content_prompt(self, topic: str, platform: str, language: str,
                              content_type: str, style: str = "",
                              references: list = None) -> tuple:
        """返回 (system_prompt, user_prompt)"""
        # 平台字数限制
        platform_limits = {
            "instagram": 2200, "tiktok": 300, "youtube": 5000,
            "xiaohongshu": 1000, "weibo": 2000, "twitter": 280, "facebook": 5000,
        }
        max_chars = platform_limits.get(platform, 2000)
        lang_name = {"zh": "中文", "en": "English", "ja": "日本語"}.get(language, language)

        system_prompt = f"""你是一位专业的{platform}平台内容创作者，擅长{topic}领域的内容创作。
你的文案风格独特、有感染力，善于引发用户互动。
所有输出必须使用{lang_name}。"""

        ref_text = ""
        if references:
            ref_text = "\n参考高表现内容:\n" + "\n".join(f"- {r}" for r in references[:5])

        user_prompt = f"""请为{platform}平台创作一条{topic}主题的{content_type}内容。

要求:
- 语言: {lang_name}
- 正文字数限制: {max_chars}字以内
- 内容类型: {content_type}
{f'- 风格要求: {style}' if style else ''}
{ref_text}

请严格按以下JSON格式输出（不要输出其他内容）:
{{
  "title": "标题（30字以内）",
  "headline": "钩子文案/封面标题（15字以内）",
  "caption": "正文描述（{max_chars}字以内）",
  "hashtags": ["话题标签1", "话题标签2", ...],
  "tags": ["分类标签1", "分类标签2", ...]
}}"""
        return system_prompt, user_prompt

    def build_variant_prompt(self, base_title: str, base_caption: str,
                              target_platform: str, language: str) -> tuple:
        """返回 (system_prompt, user_prompt) 用于生成平台变体"""
        platform_limits = {
            "instagram": 2200, "tiktok": 300, "youtube": 5000,
            "xiaohongshu": 1000, "weibo": 2000, "twitter": 280, "facebook": 5000,
        }
        max_chars = platform_limits.get(target_platform, 2000)
        platform_styles = {
            "instagram": "情感化，emoji丰富，适合视觉内容",
            "tiktok": "口语化，钩子开头，简短有力",
            "youtube": "专业详细，包含CTA",
            "xiaohongshu": "种草风格，分点列举，话题标签丰富",
            "weibo": "新闻/段子体，简洁有力",
            "twitter": "精炼，引发讨论",
            "facebook": "社区感，鼓励分享"
        }
        style = platform_styles.get(target_platform, "专业有吸引力")
        lang_name = {"zh": "中文", "en": "English", "ja": "日本語"}.get(language, language)

        system_prompt = f"你是专业的{target_platform}平台内容适配专家。请用{lang_name}输出。"
        user_prompt = f"""将以下内容适配为{target_platform}平台风格。

原始标题: {base_title}
原始正文: {base_caption[:500]}

{target_platform}平台要求:
- 字数限制: {max_chars}字
- 风格: {style}
- 话题标签数量: {"20-30个" if target_platform == "instagram" else "3-10个"}

请严格按JSON格式输出:
{{
  "headline": "适配后的标题",
  "caption": "适配后的正文",
  "hashtags": ["标签1", "标签2", ...]
}}"""
        return system_prompt, user_prompt

    # ── 内容生成 ─────────────────────────────────────────────

    def generate_content(self, ai_config: dict, topic: str, platform: str,
                          language: str, content_type: str, style: str = "",
                          references: list = None, suggestion_id: int = None,
                          pipeline_run_id: int = None) -> dict:
        """
        完整的内容生成流程:
        1. 创建 generation_task
        2. 构造 prompt
        3. 调用 AI API
        4. 解析结果
        5. 创建 content 记录
        6. 记录 generation_log
        7. 返回 {task_id, content_id, content_data, tokens}
        """
        # Step 1: 创建任务记录
        task_id = self._create_task('content', {
            'topic': topic, 'platform': platform, 'language': language,
            'content_type': content_type, 'style': style
        }, suggestion_id=suggestion_id, pipeline_run_id=pipeline_run_id)

        try:
            self._update_task(task_id, status='running', started_at=datetime.now().isoformat())

            # Step 2: 构造 prompt
            sys_prompt, user_prompt = self.build_content_prompt(
                topic, platform, language, content_type, style, references)
            self._update_task(task_id, prompt_used=user_prompt,
                             provider=ai_config.get('provider','anthropic'),
                             model=ai_config.get('model',''))

            # Step 3: 调用 AI
            result = self.call_ai(
                provider=ai_config.get('provider', 'anthropic'),
                model=ai_config.get('model', 'claude-sonnet-4-20250514'),
                api_key=_resolve_api_key(ai_config.get('api_key_encrypted', '')),
                system_prompt=sys_prompt,
                user_prompt=user_prompt,
                base_url=ai_config.get('base_url', ''),
                max_tokens=ai_config.get('max_tokens', 4096),
                temperature=ai_config.get('temperature', 0.7),
            )

            # Step 4: 解析 JSON
            content_data = self._parse_json_response(result['content'])

            # Step 5: 创建 content 记录
            from services.content_service import ContentService
            cs = ContentService(self.db_path)
            content_id = cs.create({
                'title': content_data.get('title', topic),
                'topic': topic,
                'language': language,
                'content_type': content_type,
                'status': 'pending_review',  # AI 生成的默认待审核
                'tags': content_data.get('tags', []),
                'dedupe_hash': self._compute_hash(
                    content_data.get('title',''), content_data.get('caption',''))
            })

            # Step 6: 记录日志
            self._log_generation(task_id, result)

            # Step 7: 更新任务
            self._update_task(task_id, status='completed',
                             completed_at=datetime.now().isoformat(),
                             content_id=content_id,
                             output_data=json.dumps(content_data))

            return {
                'task_id': task_id,
                'content_id': content_id,
                'content_data': content_data,
                'tokens': {
                    'input': result['input_tokens'],
                    'output': result['output_tokens'],
                    'total': result['total_tokens']
                },
                'latency_ms': result['latency_ms']
            }

        except Exception as e:
            self._update_task(task_id, status='failed',
                             error_message=str(e),
                             completed_at=datetime.now().isoformat())
            raise

    def generate_variants(self, ai_config: dict, content_id: int,
                           target_platforms: list,
                           pipeline_run_id: int = None) -> List[dict]:
        """
        为指定内容自动生成多平台变体（并行调用 AI API）。
        返回 [{variant_id, platform, headline, caption, hashtags}, ...]
        """
        from services.content_service import ContentService, VariantService
        cs = ContentService(self.db_path)
        vs = VariantService(self.db_path)

        content = cs.get(content_id)
        if not content:
            raise ValueError(f"Content {content_id} not found")

        api_key = _resolve_api_key(ai_config.get('api_key_encrypted', ''))

        def _generate_one(platform: str) -> dict:
            """生成单个平台变体（在线程中执行）"""
            task_id = self._create_task('variant', {
                'content_id': content_id, 'platform': platform
            }, content_id=content_id, pipeline_run_id=pipeline_run_id)

            try:
                self._update_task(task_id, status='running', started_at=datetime.now().isoformat())

                sys_prompt, user_prompt = self.build_variant_prompt(
                    content['title'],
                    content.get('caption', content.get('title', '')),
                    platform, content.get('language', 'zh'))

                result = self.call_ai(
                    provider=ai_config.get('provider', 'anthropic'),
                    model=ai_config.get('model', 'claude-sonnet-4-20250514'),
                    api_key=api_key,
                    system_prompt=sys_prompt,
                    user_prompt=user_prompt,
                    base_url=ai_config.get('base_url', ''),
                    max_tokens=ai_config.get('max_tokens', 2048),
                    temperature=ai_config.get('temperature', 0.7),
                )

                variant_data = self._parse_json_response(result['content'])

                variant_id = vs.create({
                    'content_id': content_id,
                    'platform': platform,
                    'headline': variant_data.get('headline', ''),
                    'caption': variant_data.get('caption', ''),
                    'hashtags': variant_data.get('hashtags', []),
                    'status': 'ready',
                })

                self._log_generation(task_id, result)
                self._update_task(task_id, status='completed',
                                 completed_at=datetime.now().isoformat(),
                                 output_data=json.dumps(variant_data))

                return {
                    'variant_id': variant_id,
                    'platform': platform,
                    'task_id': task_id,
                    **variant_data,
                    'tokens': result['total_tokens']
                }

            except Exception as e:
                self._update_task(task_id, status='failed', error_message=str(e))
                logger.error(f"Variant generation failed for {platform}: {e}")
                return None

        # 并行调用所有平台，最多 7 个线程同时执行
        results = []
        with ThreadPoolExecutor(max_workers=min(len(target_platforms), 7)) as executor:
            futures = {executor.submit(_generate_one, p): p for p in target_platforms}
            for future in as_completed(futures):
                r = future.result()
                if r:
                    results.append(r)

        return results

    # ── 生成任务管理 ─────────────────────────────────────────

    def _create_task(self, task_type, input_data, content_id=None,
                      suggestion_id=None, pipeline_run_id=None) -> int:
        # 插入 generation_tasks 记录
        conn = get_connection(self.db_path)
        try:
            now = datetime.now().isoformat()
            cur = conn.execute("""
                INSERT INTO generation_tasks (task_type, status, input_data, content_id,
                    suggestion_id, pipeline_run_id, created_at, updated_at)
                VALUES (?, 'pending', ?, ?, ?, ?, ?, ?)
            """, (task_type, json.dumps(input_data), content_id, suggestion_id,
                  pipeline_run_id, now, now))
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()

    def _update_task(self, task_id, **fields):
        conn = get_connection(self.db_path)
        try:
            sets = []
            vals = []
            for k, v in fields.items():
                sets.append(f"{k} = ?")
                vals.append(v)
            sets.append("updated_at = ?")
            vals.append(datetime.now().isoformat())
            vals.append(task_id)
            conn.execute(f"UPDATE generation_tasks SET {', '.join(sets)} WHERE id = ?", vals)
            conn.commit()
        finally:
            conn.close()

    def _log_generation(self, task_id, result):
        conn = get_connection(self.db_path)
        try:
            from services.ai_provider_registry import estimate_cost
            cost = estimate_cost(
                result.get('provider', ''),
                result.get('model', ''),
                result['input_tokens'],
                result['output_tokens']
            )
            conn.execute("""
                INSERT INTO generation_logs (generation_task_id, input_tokens, output_tokens,
                    total_tokens, estimated_cost_usd, latency_ms, raw_response)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (task_id, result['input_tokens'], result['output_tokens'],
                  result['total_tokens'], cost, result.get('latency_ms', 0),
                  json.dumps({"content_preview": result['content'][:200]})))
            conn.commit()
        finally:
            conn.close()

    def list_tasks(self, status=None, task_type=None, limit=50) -> List[dict]:
        conn = get_connection(self.db_path)
        try:
            sql = "SELECT * FROM generation_tasks WHERE 1=1"
            params = []
            if status:
                sql += " AND status = ?"
                params.append(status)
            if task_type:
                sql += " AND task_type = ?"
                params.append(task_type)
            sql += " ORDER BY id DESC LIMIT ?"
            params.append(limit)
            rows = conn.execute(sql, params).fetchall()
            return [self._row_to_dict(r) for r in rows]
        finally:
            conn.close()

    def get_task(self, task_id: int) -> Optional[dict]:
        conn = get_connection(self.db_path)
        try:
            row = conn.execute("SELECT * FROM generation_tasks WHERE id=?", (task_id,)).fetchone()
            return self._row_to_dict(row) if row else None
        finally:
            conn.close()

    def get_log_stats(self) -> dict:
        """返回 token/成本统计"""
        conn = get_connection(self.db_path)
        try:
            row = conn.execute("""
                SELECT COALESCE(SUM(total_tokens),0) total_tokens,
                       COALESCE(SUM(estimated_cost_usd),0) total_cost,
                       COUNT(*) total_calls
                FROM generation_logs
            """).fetchone()
            today = datetime.now().strftime('%Y-%m-%d')
            today_row = conn.execute("""
                SELECT COALESCE(SUM(total_tokens),0) tokens, COUNT(*) calls
                FROM generation_logs WHERE created_at LIKE ?
            """, (f"{today}%",)).fetchone()
            return {
                'total_tokens': row['total_tokens'],
                'total_cost_usd': round(row['total_cost'], 4),
                'total_calls': row['total_calls'],
                'today_tokens': today_row['tokens'],
                'today_calls': today_row['calls'],
            }
        finally:
            conn.close()

    def list_logs(self, task_id=None, limit=50) -> List[dict]:
        conn = get_connection(self.db_path)
        try:
            sql = "SELECT * FROM generation_logs WHERE 1=1"
            params = []
            if task_id:
                sql += " AND generation_task_id = ?"
                params.append(task_id)
            sql += " ORDER BY id DESC LIMIT ?"
            params.append(limit)
            rows = conn.execute(sql, params).fetchall()
            return [self._row_to_dict(r) for r in rows]
        finally:
            conn.close()

    # ── 工具方法 ─────────────────────────────────────────────

    def _parse_json_response(self, text: str) -> dict:
        """从 AI 响应中提取 JSON"""
        text = text.strip()
        # 尝试找到 JSON 块
        if '```json' in text:
            text = text.split('```json')[1].split('```')[0].strip()
        elif '```' in text:
            text = text.split('```')[1].split('```')[0].strip()
        # 尝试找 { }
        start = text.find('{')
        end = text.rfind('}')
        if start != -1 and end != -1:
            text = text[start:end+1]
        return json.loads(text)

    def _compute_hash(self, title: str, caption: str) -> str:
        raw = (title + caption[:100]).strip().lower()
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    @staticmethod
    def _row_to_dict(row) -> dict:
        d = dict(row)
        for key in ('input_data', 'output_data', 'raw_response'):
            if key in d and isinstance(d[key], str):
                try:
                    d[key] = json.loads(d[key])
                except (json.JSONDecodeError, TypeError):
                    pass
        return d
