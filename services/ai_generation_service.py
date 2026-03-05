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

    # ── 图文卡片 Prompt ──────────────────────────────────────

    def build_card_content_prompt(self, topic: str, platform: str, language: str,
                                   content_type: str, style: str = "",
                                   slide_count: int = 6,
                                   references: list = None) -> tuple:
        """构造图文卡片 prompt，让 AI 返回带 slides 结构的 JSON。"""
        platform_limits = {
            "instagram": 2200, "tiktok": 300, "youtube": 5000,
            "xiaohongshu": 1000, "weibo": 2000, "twitter": 280, "facebook": 5000,
        }
        max_chars = platform_limits.get(platform, 2000)
        lang_name = {"zh": "中文", "en": "English", "ja": "日本語"}.get(language, language)

        # Platform-specific tone guidance
        platform_tone = {
            "xiaohongshu": "种草感、个人分享视角、像闺蜜聊天一样亲切真实，多用「我」「亲测」「真的会谢」等第一人称表达，营造真实体验感",
            "tiktok": "短平快、口语化、节奏感强，用短句制造冲击力，像在跟朋友面对面说话，适当用反问和感叹增加互动感",
            "weibo": "话题性强、紧跟热点、观点鲜明犀利，善用金句和反转，语言要有传播力和讨论价值",
            "instagram": "aesthetic、aspirational、storytelling风格，文案要有画面感和情绪共鸣，英文可混搭使用，注重lifestyle感",
            "youtube": "深度专业但不枯燥，像一个懂行的朋友在分享干货，逻辑清晰有层次，适当加入个人观点和见解",
            "twitter": "犀利简短、一针见血，每句话都要有信息密度，善用对比和转折制造记忆点",
            "facebook": "社区感、温暖真诚、鼓励互动分享，像在社群里发起一个有价值的讨论",
        }
        tone_guide = platform_tone.get(platform, "专业且有吸引力，兼顾信息价值和可读性")

        system_prompt = f"""你是{platform}平台TOP级别的图文内容创作者，在{topic}领域拥有百万级粉丝。
你深谙社交媒体传播规律，擅长用视觉化文案制造「停留感」和「收藏欲」。

【核心创作原则】
1. 钩子思维：每张卡片的前5个字必须抓住注意力，使用反问、数据冲击、反常识、痛点共鸣等手法
2. 情绪驱动：文案要触发具体情绪（好奇、焦虑、惊喜、认同、向往），而非平铺直叙
3. 信息密度：每句话都要有「获得感」，拒绝正确但无用的废话
4. 节奏变化：长短句交替使用，短句制造冲击（3-7字），长句提供深度（15-25字），避免所有句子都一样长
5. 具象表达：用具体数字、真实场景、对比案例代替抽象描述（「省了2小时」而非「提高效率」）

【{platform}平台调性】
{tone_guide}

【严格禁止使用的烂大街表达】
- 禁止：「干货满满」「建议收藏」「强烈推荐」「不看后悔」「全网最全」「满满的收获」
- 禁止：「你值得拥有」「赶紧行动吧」「一定要看完」「太绝了」「yyds」
- 禁止：所有不提供具体信息的空洞形容词和万能句式
- 替代策略：用具体场景和数据说话，让读者自己得出「值得收藏」的结论

【文案素材技巧】
- Power Words：使用有画面感和触发行动的动词（「拆解」「避坑」「翻倍」「逆袭」「碾压」）
- Curiosity Gap：制造信息缺口让人想继续看（「最后一条90%的人都不知道」→ 但要确保兑现承诺）
- Social Proof：巧妙植入可信度信号（具体数字、时间线、真实场景）
- Contrast：善用对比制造张力（做了vs没做、之前vs之后、外行vs内行）

所有输出必须使用{lang_name}。
每个要点控制在30字以内，但要在30字内塞入最大信息量。"""

        ref_text = ""
        if references:
            ref_text = "\n参考高表现内容（学习其结构和手法，但不要照搬）:\n" + "\n".join(f"- {r}" for r in references[:5])

        user_prompt = f"""请为{platform}平台创作一组{topic}主题的图文轮播内容（{slide_count}张卡片）。

【基本要求】
- 语言: {lang_name}
- 卡片数量: {slide_count}张（含封面和结尾页）
- 每个要点简洁有力，适合在图片上排版
{f'- 风格要求: {style}' if style else ''}
{ref_text}

【卡片编排策略】
按照以下节奏编排{slide_count}张卡片，制造「刷到停不下来」的体验：
1. Hook（封面）→ 用封面制造强烈好奇心，让人想右滑
2. Value（价值页）→ 交付核心干货，每页一个清晰观点
3. Evidence（证据页）→ 用数据/对比/案例增强说服力
4. Action（结尾页）→ 明确的下一步行动 + 互动引导

卡片类型不要全用content，至少混合使用3种以上类型，让视觉节奏有变化。

【卡片类型说明】

1. cover（封面页）：大标题要制造好奇心缺口，副标题补充价值承诺
2. content（内容页）：有小标题和要点列表（3-5个要点）或段落正文，可附带emoji装饰
3. quote（引用页）：一句有感染力的话，可以是金句、数据结论或反常识观点
4. summary（结尾总结页）：核心要点回顾 + 具体可执行的行动号召
5. data（数据页）：用大数字制造视觉冲击，配合简短解读让数据说话
6. steps（步骤页）：分步骤拆解，每步有明确动作指令，降低执行门槛
7. comparison（对比页）：before/after 或 pros/cons 对比，让差异一目了然
8. tip（技巧页）：一个实用技巧/窍门，配合具体操作说明

请严格按以下JSON格式输出（不要输出其他内容）:
{{
  "title": "整体标题（30字以内，要有信息增量）",
  "headline": "封面钩子文案（15字以内，制造好奇心缺口）",
  "caption": "配文描述（{max_chars}字以内）。结构要求：第一句用情绪钩子引发共鸣 → 中间段提炼核心价值点 → 最后用具体问题引导评论互动。不要用'建议收藏'等废话。",
  "hashtags": ["话题标签1", "话题标签2", ...],
  "tags": ["分类标签1", "分类标签2", ...],
  "slides": [
    {{
      "type": "cover",
      "title": "封面大标题（制造好奇心）",
      "subtitle": "副标题/价值承诺",
      "accent_text": "数据亮点或核心标签（可选）"
    }},
    {{
      "type": "content",
      "heading": "小标题",
      "points": ["要点1（30字以内，有具体信息）", "要点2", "要点3"],
      "highlight": "重点强调句（可选）",
      "emoji": "📌"
    }},
    {{
      "type": "data",
      "heading": "数据说话（可选标题）",
      "stats": [
        {{"value": "90%", "label": "指标名称", "description": "一句话解读这个数据意味着什么"}},
        {{"value": "3x", "label": "指标名称", "description": "对比说明"}}
      ],
      "source": "数据来源（可选，增加可信度）",
      "emoji": "📊"
    }},
    {{
      "type": "steps",
      "heading": "步骤标题（如：3步搞定xxx）",
      "items": [
        {{"step": 1, "title": "步骤名称", "description": "具体怎么做（15字以内）"}},
        {{"step": 2, "title": "步骤名称", "description": "具体怎么做"}},
        {{"step": 3, "title": "步骤名称", "description": "具体怎么做"}}
      ],
      "emoji": "🔢"
    }},
    {{
      "type": "comparison",
      "heading": "对比标题",
      "left_label": "Before/普通做法",
      "right_label": "After/高手做法",
      "left_points": ["对比项1", "对比项2", "对比项3"],
      "right_points": ["对比项1", "对比项2", "对比项3"],
      "emoji": "⚡"
    }},
    {{
      "type": "tip",
      "icon": "💡",
      "title": "技巧标题",
      "content": "具体技巧内容，要有可操作性",
      "note": "补充说明或注意事项（可选）",
      "emoji": "💡"
    }},
    {{
      "type": "quote",
      "quote": "一句有感染力的金句/数据结论/反常识观点",
      "emoji": "💬"
    }},
    {{
      "type": "summary",
      "heading": "总结",
      "points": ["核心要点1（回顾最有价值的信息）", "核心要点2"],
      "cta": "具体的行动号召（告诉读者下一步做什么，而不是'关注我'）"
    }}
  ]
}}

注意：以上slides示例展示了所有可用类型，实际输出请根据内容需要从中选择{slide_count}张，
不需要每种类型都用。确保类型多样（至少3种不同类型），节奏有变化。"""
        return system_prompt, user_prompt

    def generate_card_content(self, ai_config: dict, topic: str, platform: str,
                               language: str, content_type: str = "image_carousel",
                               style: str = "", slide_count: int = 6,
                               template: str = "minimal",
                               color_scheme: dict = None,
                               references: list = None,
                               suggestion_id: int = None,
                               pipeline_run_id: int = None) -> dict:
        """
        完整的图文卡片生成流程:
        1. 调用 AI 生成带 slides 的结构化内容
        2. 创建 content 记录
        3. 创建 variant 记录
        4. 调用 CardRenderService 渲染图片并关联
        5. 返回 {task_id, content_id, variant_id, asset_ids, preview_urls, slides, tokens}
        """
        # Step 1: 创建任务
        task_id = self._create_task('card_content', {
            'topic': topic, 'platform': platform, 'language': language,
            'content_type': content_type, 'style': style,
            'slide_count': slide_count, 'template': template,
        }, suggestion_id=suggestion_id, pipeline_run_id=pipeline_run_id)

        try:
            self._update_task(task_id, status='running', started_at=datetime.now().isoformat())

            # Step 2: 构造 prompt 并调用 AI
            sys_prompt, user_prompt = self.build_card_content_prompt(
                topic, platform, language, content_type, style,
                slide_count, references)
            self._update_task(task_id, prompt_used=user_prompt,
                             provider=ai_config.get('provider', 'anthropic'),
                             model=ai_config.get('model', ''))

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

            # Step 3: 解析 JSON（包含 slides）
            content_data = self._parse_json_response(result['content'])
            slides = content_data.get('slides', [])
            if not slides:
                raise ValueError("AI 未返回 slides 数据")

            # Step 4: 创建 content 记录
            from services.content_service import ContentService, VariantService
            cs = ContentService(self.db_path)
            content_id = cs.create({
                'title': content_data.get('title', topic),
                'topic': topic,
                'language': language,
                'content_type': content_type,
                'status': 'pending_review',
                'tags': content_data.get('tags', []),
                'body': content_data.get('caption', ''),
                'dedupe_hash': self._compute_hash(
                    content_data.get('title', ''), content_data.get('caption', ''))
            })

            # Step 5: 创建 variant 记录
            vs = VariantService(self.db_path)
            variant_id = vs.create({
                'content_id': content_id,
                'platform': platform,
                'headline': content_data.get('headline', ''),
                'caption': content_data.get('caption', ''),
                'hashtags': content_data.get('hashtags', []),
                'status': 'ready',
            })

            # Step 6: 渲染卡片并关联到 variant
            from services.card_render_service import CardRenderService
            render_svc = CardRenderService(self.db_path)
            try:
                asset_ids = render_svc.render_and_attach(
                    variant_id, slides, template, platform, color_scheme)
            finally:
                render_svc.close()

            # Step 7: 记录日志
            self._log_generation(task_id, result)
            self._update_task(task_id, status='completed',
                             completed_at=datetime.now().isoformat(),
                             content_id=content_id,
                             output_data=json.dumps(content_data))

            # Build preview URLs
            preview_urls = []
            from services.content_service import AssetService
            asset_svc = AssetService(self.db_path)
            for aid in asset_ids:
                asset = asset_svc.get(aid)
                if asset:
                    preview_urls.append(f"/api/uploads/{asset['storage_url']}")

            return {
                'task_id': task_id,
                'content_id': content_id,
                'variant_id': variant_id,
                'slides': slides,
                'asset_ids': asset_ids,
                'preview_urls': preview_urls,
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
