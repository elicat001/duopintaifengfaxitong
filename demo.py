"""演示脚本：添加测试数据并运行一轮调度"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from config import DB_PATH
from models.database import init_database
from models.schemas import ContentItem, PerformanceRecord
from agents.content_manager import ContentManager
from agents.performance_tracker import PerformanceTracker
from agents.scheduler import Scheduler
from agents.scoring_engine import ScoringEngine

init_database(DB_PATH)

cm = ContentManager(DB_PATH)
pt = PerformanceTracker(DB_PATH)
engine = ScoringEngine()

# 添加测试内容
print("=" * 60)
print("  添加测试内容")
print("=" * 60)

contents = [
    ("爆款视频：猫咪搞笑合集", "超级搞笑的猫咪视频", "video"),
    ("普通文章：Python入门教程", "Python基础知识讲解", "article"),
    ("冷门帖子：量子力学笔记", "量子力学学习笔记", "article"),
    ("热门图片：旅行风景照", "云南大理洱海风景", "image"),
    ("低迷内容：旧闻翻炒", "一篇过时的新闻", "article"),
]

content_ids = []
for title, body, ctype in contents:
    cid = cm.add_content(ContentItem(title=title, body=body, content_type=ctype))
    content_ids.append(cid)
    print(f"  [+] ID={cid} {title}")

# 录入表现数据
print("\n" + "=" * 60)
print("  录入表现数据")
print("=" * 60)

performance_data = [
    # (content_id, likes, comments, shares, views)
    (content_ids[0], 5000, 800, 300, 100000),   # 爆款
    (content_ids[1], 120, 30, 10, 5000),         # 普通
    (content_ids[2], 5, 1, 0, 200),              # 冷门
    (content_ids[3], 2000, 200, 80, 50000),      # 热门
    (content_ids[4], 2, 0, 0, 50),               # 低迷
]

for cid, likes, comments, shares, views in performance_data:
    pt.record_performance(PerformanceRecord(
        content_id=cid, likes=likes, comments=comments,
        shares=shares, views=views,
    ))
    record = pt.get_latest_record(cid)
    score_result = engine.evaluate_content(record)
    print(f"  ID={cid} | 点赞={likes:>5} 评论={comments:>4} 转发={shares:>3} 浏览={views:>6} | 评分={score_result.score:>6.2f} → {score_result.recommended_frequency.value}")

# 执行一轮调度
print("\n" + "=" * 60)
print("  执行调度循环")
print("=" * 60)

scheduler = Scheduler(DB_PATH)
stats = scheduler.run_cycle()

print(f"\n  投放数: {stats['published']}")
print(f"  重新调度: {stats['rescheduled']}")
print(f"  暂停: {stats['paused']}")

# 查看最终调度计划
print("\n" + "=" * 60)
print("  最终调度计划")
print("=" * 60)

from models.database import get_connection
conn = get_connection(DB_PATH)
rows = conn.execute("""
    SELECT c.title, sp.score, sp.frequency, sp.next_publish_at, sp.publish_count
    FROM schedule_plans sp
    JOIN contents c ON c.id = sp.content_id
    ORDER BY sp.score DESC
""").fetchall()
conn.close()

freq_labels = {"high": "每天复投", "normal": "每3天", "low": "每7天", "paused": "已暂停"}

print(f"\n  {'内容':<25} {'评分':>6} {'频率':<10} {'下次投放':<20} {'已投放'}")
print("  " + "-" * 80)
for row in rows:
    freq = freq_labels.get(row["frequency"], row["frequency"])
    next_pub = row["next_publish_at"][:16] if row["next_publish_at"] else "无"
    print(f"  {row['title']:<25} {row['score']:>6.2f} {freq:<10} {next_pub:<20} {row['publish_count']}次")
