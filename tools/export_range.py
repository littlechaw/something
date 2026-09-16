#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
钉钉聊天记录批量导出 —— 按日期范围自动遍历
用法: python3 export_range.py <开始日期> <结束日期>

示例:
  python3 tools/export_range.py 2025-12-01 2026-07-02   # 导出整个范围
  python3 tools/export_range.py 2026-06-01 2026-06-30   # 导出 6 月
"""

import datetime
import os
import re
import shutil
import sqlite3
import sys

# 把项目根目录加入 sys.path，以便复用 export.py 中的工具函数
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "tools"))

from export import (
    CONFIG, OUTPUT_BASE,
    _decrypt_storage_and_get_uid, _decrypt_dingtalk, _decrypt_dingtalk_fts,
    _get_messages, _download_images, _format_markdown,
    _has_nonempty_export, _clean_dec_data, _update_reader_raw_index,
)


def export_one_day(db_path, fts_db_path, cid, title, date_str, skip_empty=False):
    """导出单个会话某一天的消息，返回 (消息数, 图片数)"""
    conv_dir = os.path.join(
        OUTPUT_BASE, date_str,
        re.sub(r'[<>:"/\\|?*]', '_', title).rstrip('. ')
    )
    images_dir = os.path.join(conv_dir, "images")

    messages, all_media_ids = _get_messages(db_path, cid, date_str, fts_db_path)

    if skip_empty and not messages:
        return 0, 0

    if not messages and _has_nonempty_export(conv_dir):
        print(f"  ⚠️  {date_str} {title}: 本次结果为空，保留已有非空 messages.md")
        return 0, 0

    if os.path.exists(conv_dir):
        shutil.rmtree(conv_dir)

    os.makedirs(conv_dir, exist_ok=True)

    if not messages:
        md = _format_markdown([], {}, title, date_str)
        image_map = {}
    else:
        image_map = _download_images(all_media_ids, images_dir)
        md = _format_markdown(messages, image_map, title, date_str)

    md_path = os.path.join(conv_dir, "messages.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md)
    _update_reader_raw_index(md_path, title, date_str)

    img_count = sum(1 for v in image_map.values() if v is not None)
    return len(messages), img_count


def main():
    export_targets = CONFIG.get("export_targets", [])
    if not export_targets:
        print("❌ 请在 client_config.json 中配置 export_targets")
        sys.exit(1)

    if len(sys.argv) < 3:
        print("用法: python3 export_range.py <开始日期> <结束日期> [--skip-empty]")
        print("示例: python3 tools/export_range.py 2025-12-01 2026-07-02")
        sys.exit(1)

    start_str = sys.argv[1]
    end_str = sys.argv[2]
    skip_empty = "--skip-empty" in sys.argv

    try:
        start_date = datetime.datetime.strptime(start_str, "%Y-%m-%d").date()
        end_date = datetime.datetime.strptime(end_str, "%Y-%m-%d").date()
    except ValueError:
        print("❌ 日期格式错误，请使用 YYYY-MM-DD")
        sys.exit(1)

    if start_date > end_date:
        print("❌ 开始日期不能晚于结束日期")
        sys.exit(1)

    # 计算日期列表
    dates = []
    current = start_date
    while current <= end_date:
        dates.append(current.strftime("%Y-%m-%d"))
        current += datetime.timedelta(days=1)

    print(f"\n  📦 钉钉批量导出")
    print(f"  📅 {start_str} → {end_str}，共 {len(dates)} 天\n")

    # 解密一次
    print("  清理临时解密目录...")
    _clean_dec_data()
    print("  🔓 解密数据库...")
    uid = _decrypt_storage_and_get_uid()
    db_path = _decrypt_dingtalk(uid)
    fts_db_path = _decrypt_dingtalk_fts(uid)
    print(f"  ✅ 解密完成 (UID={uid})")
    if fts_db_path:
        print("  🔎 已启用 FTS 补充来源: dingtalk.db_fts")

    # 获取会话名称
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    targets = []
    for cid in export_targets:
        cur.execute("SELECT title FROM tbconversation WHERE cid=?", (cid,))
        row = cur.fetchone()
        if row:
            targets.append((cid, row[0]))
        else:
            print(f"  ⚠️  未找到会话 CID: {cid}")
    conn.close()

    if not targets:
        print("❌ 没有可导出的会话")
        sys.exit(1)

    # 逐天导出
    total_msgs, total_imgs, days_with_data = 0, 0, 0
    for i, date_str in enumerate(dates):
        day_msgs, day_imgs = 0, 0
        for cid, title in targets:
            msgs, imgs = export_one_day(db_path, fts_db_path, cid, title, date_str, skip_empty)
            day_msgs += msgs
            day_imgs += imgs

        total_msgs += day_msgs
        total_imgs += day_imgs
        if day_msgs > 0:
            days_with_data += 1

        progress = f"[{i+1}/{len(dates)}]"
        print(f"  {progress} {date_str}  💬 {day_msgs:>4} 条  📷 {day_imgs:>3} 张")

    print(f"\n  ✅ 导出完成")
    print(f"  📊 {days_with_data}/{len(dates)} 天有数据，共 {total_msgs} 条消息，{total_imgs} 张图片")
    print(f"  📂 {OUTPUT_BASE}/\n")


if __name__ == "__main__":
    main()
