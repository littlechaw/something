#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
钉钉聊天记录导出 —— 单文件独立版
用法: python3 export.py [日期]

依赖: Python 3 标准库 + openssl（macOS 内置）
配置: 项目根目录下的 client_config.json
"""

import datetime
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
from urllib.parse import urlsplit

# ── 路径 ──────────────────────────────────────────────────
# export.py 在 tools/ 下，项目根目录在上一级
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEC_DATA_DIR = os.path.join(PROJECT_ROOT, ".dec_data")
OUTPUT_BASE  = os.path.join(PROJECT_ROOT, "exports")
READER_INDEX_PATH = os.path.join(PROJECT_ROOT, "tools", "xianzhi-reader", "file-index.json")
THUMBNAIL_MAX_SIZE = 960


def _clean_dec_data():
    """清理本项目内的解密临时目录，避免旧文件残留影响本次导出。"""
    project_root = os.path.realpath(PROJECT_ROOT)
    dec_data_dir = os.path.realpath(DEC_DATA_DIR)
    if not dec_data_dir.startswith(project_root + os.sep):
        raise RuntimeError(f"拒绝清理项目目录外路径: {DEC_DATA_DIR}")

    os.makedirs(DEC_DATA_DIR, exist_ok=True)
    for name in os.listdir(DEC_DATA_DIR):
        path = os.path.join(DEC_DATA_DIR, name)
        if os.path.isdir(path) and not os.path.islink(path):
            shutil.rmtree(path)
        else:
            os.remove(path)


# ── 配置 ──────────────────────────────────────────────────

def _load_config():
    cfg_path = os.path.join(PROJECT_ROOT, "client_config.json")
    if not os.path.exists(cfg_path):
        print(f"❌ 未找到 client_config.json ({cfg_path})")
        sys.exit(1)
    with open(cfg_path, "r") as f:
        return json.load(f)

CONFIG = _load_config()
DT_PATH = CONFIG["dingtalk_path"]
GLOBAL_KEY = CONFIG["global_key"]
EXPORT_TARGETS = CONFIG.get("export_targets", [])

# ── AES-ECB 解密 ──────────────────────────────────────────

def _aes_ecb_decrypt(data, key_bytes):
    """AES-128-ECB 解密，优先用 pycryptodome，否则用 openssl"""
    try:
        from Crypto.Cipher import AES
        return AES.new(key_bytes, AES.MODE_ECB).decrypt(data)
    except ImportError:
        pass
    r = subprocess.run(
        ["openssl", "enc", "-d", "-aes-128-ecb", "-nopad", "-nosalt", "-K", key_bytes.hex()],
        input=data, capture_output=True,
    )
    if r.returncode != 0:
        raise RuntimeError(f"openssl 解密失败: {r.stderr.decode()}")
    return r.stdout


def _decrypt_file(enc_path, aes_key):
    with open(enc_path, "rb") as f:
        return bytearray(_aes_ecb_decrypt(f.read(), aes_key))


def _apply_encrypted_wal_file(wal_path, db_path, aes_key):
    """把钉钉加密 WAL 中已提交的页面解密后合并到解密 DB。"""
    if not os.path.exists(wal_path) or os.path.getsize(wal_path) <= 32:
        return 0

    with open(wal_path, "rb") as f:
        wal = f.read()

    if len(wal) < 32:
        return 0

    magic = int.from_bytes(wal[0:4], "big")
    if magic not in (0x377F0682, 0x377F0683):
        return 0

    page_size = int.from_bytes(wal[8:12], "big") or 65536
    if page_size <= 0 or page_size % 16 != 0:
        return 0

    salt = wal[16:24]
    frame_size = 24 + page_size
    frames = []
    last_commit_index = -1

    offset = 32
    while offset + frame_size <= len(wal):
        header = wal[offset:offset + 24]
        if header[8:16] != salt:
            break

        page_no = int.from_bytes(header[0:4], "big")
        db_size = int.from_bytes(header[4:8], "big")
        if page_no <= 0:
            break

        page = wal[offset + 24:offset + frame_size]
        frames.append((page_no, db_size, page))
        if db_size > 0:
            last_commit_index = len(frames) - 1
        offset += frame_size

    if last_commit_index < 0:
        return 0

    committed_frames = frames[:last_commit_index + 1]
    encrypted_pages = b"".join(page for _, _, page in committed_frames)
    decrypted_pages = _aes_ecb_decrypt(encrypted_pages, aes_key)

    with open(db_path, "r+b") as db:
        for idx, (page_no, _, _) in enumerate(committed_frames):
            start = idx * page_size
            end = start + page_size
            db.seek((page_no - 1) * page_size)
            db.write(decrypted_pages[start:end])

        final_db_size = committed_frames[-1][1]
        if final_db_size > 0:
            db.truncate(final_db_size * page_size)

    return len(committed_frames)


# ── 密钥推导 ──────────────────────────────────────────────

def _derive_global_key(raw):
    return raw[:16].encode("ascii")

def _derive_user_key_v2(uid):
    """钉钉 v8.x: 直接 MD5(UID)[:16]"""
    return hashlib.md5(uid.encode()).hexdigest()[:16].encode("ascii")


# ── storage.db 解密 → UID 提取 ───────────────────────────

def _decrypt_storage_and_get_uid():
    """解密 storage.db 主库，提取最后一个登录的 UID"""
    global_src = os.path.join(DT_PATH, "globalStorage", "storage.db")
    if not os.path.exists(global_src):
        raise FileNotFoundError(f"未找到 storage.db: {global_src}")

    aes_key = _derive_global_key(GLOBAL_KEY)
    storage_dec = _decrypt_file(global_src, aes_key)

    tmp = os.path.join(DEC_DATA_DIR, "__storage.db")
    os.makedirs(os.path.dirname(tmp), exist_ok=True)
    with open(tmp, "wb") as f:
        f.write(storage_dec)

    conn = sqlite3.connect(tmp)
    try:
        cur = conn.cursor()
        cur.execute("SELECT key, value FROM GlobalStorage")
        kv = {row[0]: row[1] for row in cur.fetchall()}
    finally:
        conn.close()

    uid = None
    for k, v in kv.items():
        if "uid" in str(k).lower() and v and re.match(r"^\d+$", str(v)):
            uid = str(v)
            break
    if not uid:
        raise RuntimeError(f"无法提取 UID，可用的键: {list(kv.keys())}")
    return uid


# ── dingtalk.db 解密 ──────────────────────────────────────

def _find_db_file(filename):
    for d in os.listdir(DT_PATH):
        if d == "globalStorage":
            continue
        candidate = os.path.join(DT_PATH, d, "DBFiles", filename)
        if os.path.exists(candidate):
            return candidate
    raise FileNotFoundError(f"未找到 {filename}")


def _decrypt_db_file(uid, filename, output_name):
    """解密钉钉用户库文件，返回解密后文件路径"""
    dingtalk_enc = _find_db_file(filename)
    user_key = _derive_user_key_v2(uid)
    dt_dec = _decrypt_file(dingtalk_enc, user_key)

    if dt_dec[:15] != b"SQLite format 3":
        raise RuntimeError(f"{filename} 解密失败，密钥不正确")

    db_path = os.path.join(DEC_DATA_DIR, output_name)
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    with open(db_path, "wb") as f:
        f.write(dt_dec)

    wal_frames = _apply_encrypted_wal_file(dingtalk_enc + "-wal", db_path, user_key)
    if wal_frames:
        print(f"  🔁 已合并 {filename}-wal ({wal_frames} 页)")

    return db_path


def _decrypt_dingtalk(uid):
    """解密 dingtalk.db，返回解密后文件路径"""
    return _decrypt_db_file(uid, "dingtalk.db", "dingtalk.db")


def _decrypt_dingtalk_fts(uid):
    """解密 dingtalk.db_fts，返回解密后文件路径；不存在时返回 None。"""
    try:
        return _decrypt_db_file(uid, "dingtalk.db_fts", "dingtalk_fts.db")
    except FileNotFoundError:
        return None


# ── Base64URL / MessagePack 图片解码 ──────────────────────

def parse_media_id(media_id):
    """解析钉钉 Media ID → {width, height, type, url}"""
    if not media_id:
        return None

    bare = media_id.strip().lstrip("@")
    if len(bare) < 5:
        return None

    prefix = bare[:4]
    payload = bare[4:]

    # base64url 解码
    import base64
    pad = (4 - len(payload) % 4) % 4
    try:
        decoded = base64.urlsafe_b64decode(payload + "=" * pad)
    except Exception:
        return None

    if not decoded:
        return None

    # 正向解析末尾的 MessagePack 整数（width 和 height）
    # 尝试所有可能的长度组合：uint32(5) / uint16(3) / uint8(2) / fixint(1)
    decoded_len = len(decoded)
    valid_lengths = [5, 3, 2, 1]
    width = height = None

    def _parse_msgpack_int(b):
        if len(b) == 1 and b[0] <= 0x7F:
            return b[0]
        elif len(b) == 2 and b[0] == 0xCC:
            return b[1]
        elif len(b) == 3 and b[0] == 0xCD:
            return (b[1] << 8) | b[2]
        elif len(b) == 5 and b[0] == 0xCE:
            return (b[1] << 24) | (b[2] << 16) | (b[3] << 8) | b[4]
        return None

    for len_w in valid_lengths:
        for len_h in valid_lengths:
            if len_w + len_h > decoded_len:
                continue
            pos_h = decoded_len - len_w - len_h
            pos_w = decoded_len - len_w
            h_val = _parse_msgpack_int(decoded[pos_h:pos_w])
            w_val = _parse_msgpack_int(decoded[pos_w:decoded_len])
            if h_val is not None and w_val is not None and h_val < 100000 and w_val < 100000:
                height = h_val
                width = w_val
                break
        if width is not None:
            break

    if width is None or height is None:
        return None

    ext_map = {"lALP": "png", "lADP": "jpg"}
    ext = ext_map.get(prefix, "png")
    url = f"https://static.dingtalk.com/media/{bare}_{width}_{height}.{ext}"
    return {"width": width, "height": height, "type": ext, "url": url}


# ── 消息文本提取 ──────────────────────────────────────────

EXTERNAL_IMAGE_URL_RE = re.compile(
    r"https?://[^\s<>'\"()]+\.(?:apng|avif|gif|jpe?g|png|webp)(?:\?[^\s<>'\"]*)?",
    re.IGNORECASE,
)
MARKDOWN_EXTERNAL_IMAGE_RE = re.compile(
    r"!\[[^\]]*\]\((?P<url>https?://[^\s<>'\"()]+\.(?:apng|avif|gif|jpe?g|png|webp)(?:\?[^\s<>'\"]*)?)\)",
    re.IGNORECASE,
)


def _is_external_image_url(value):
    return isinstance(value, str) and EXTERNAL_IMAGE_URL_RE.fullmatch(value.strip()) is not None


def _replace_external_image_markdown(text, add_image_placeholder):
    """将 Markdown 外链图片替换为可下载的占位符。"""
    def repl(match):
        url = match.group("url")
        add_image_placeholder(url)
        return f"[IMG_URL:{url}]"

    return MARKDOWN_EXTERNAL_IMAGE_RE.sub(repl, text)

def _decode_unicode(s):
    if not s:
        return s
    try:
        s = re.sub(r'\\u([0-9a-fA-F]{4})', lambda m: chr(int(m.group(1), 16)), s)
    except Exception:
        pass
    return s


def _extract_text(content_raw, content_type):
    if not content_raw:
        return "", []
    media_ids = []
    try:
        c = content_raw
        if isinstance(c, str):
            c = c.strip("'")
        j = json.loads(c)
    except Exception:
        ids = re.findall(r'(@l[A-Za-z][A-Za-z0-9_/+-]{8,})', str(content_raw))
        return "[无法解析消息]", list(set(ids))

    parts = []
    external_pic_urls = []

    def add_media_placeholder(media_id):
        if not isinstance(media_id, str) or not media_id.startswith("@"):
            return
        media_ids.append(media_id)
        placeholder = f"[IMG:{media_id}]"
        if placeholder not in parts:
            parts.append(placeholder)

    def add_external_image_placeholder(url, append_to_parts=True):
        if not _is_external_image_url(url):
            return
        url = url.strip()
        media_ids.append(url)
        placeholder = f"[IMG_URL:{url}]"
        if append_to_parts and placeholder not in parts:
            parts.append(placeholder)

    def is_default_dingtalk_url(url):
        return isinstance(url, str) and url.rstrip("/") == "https://www.dingtalk.com"

    if "picUrl" in j and isinstance(j["picUrl"], str):
        if j["picUrl"].startswith("@"):
            add_media_placeholder(j["picUrl"])
        else:
            add_external_image_placeholder(j["picUrl"], append_to_parts=False)
            external_pic_urls.append(j["picUrl"].strip())

    if "text" in j and j["text"]:
        parts.append(_replace_external_image_markdown(
            _decode_unicode(j["text"]),
            lambda url: add_external_image_placeholder(url, append_to_parts=False),
        ))

    if "attachments" in j:
        for att in j["attachments"]:
            ext_raw = att.get("extension", "{}")
            try:
                ext = json.loads(ext_raw) if isinstance(ext_raw, str) else ext_raw
            except Exception:
                ext = {}
            if isinstance(ext, dict):
                if "markdown" in ext:
                    md = _decode_unicode(ext["markdown"])
                    ids = re.findall(r'@l[A-Za-z][A-Za-z0-9_/+-]{8,}', md)
                    media_ids.extend(ids)
                    md = re.sub(
                        r'!\[.*?\]\((@l[A-Za-z][A-Za-z0-9_/+-]{8,})\)',
                        r'[IMG:\1]', md
                    )
                    parts.append(_replace_external_image_markdown(
                        md,
                        lambda url: add_external_image_placeholder(url, append_to_parts=False),
                    ))
                elif "text" in ext:
                    parts.append(_replace_external_image_markdown(
                        _decode_unicode(ext["text"]),
                        lambda url: add_external_image_placeholder(url, append_to_parts=False),
                    ))
                if "picUrl" in ext and isinstance(ext["picUrl"], str):
                    if ext["picUrl"].startswith("@"):
                        add_media_placeholder(ext["picUrl"])
                    else:
                        add_external_image_placeholder(ext["picUrl"], append_to_parts=False)
                        external_pic_urls.append(ext["picUrl"].strip())
                if "interactiveCardLastMessage" in ext:
                    parts.append(_decode_unicode(ext["interactiveCardLastMessage"]))
                if "messageUrl" in ext and not is_default_dingtalk_url(ext["messageUrl"]):
                    parts.append(f"[链接] {ext['messageUrl']}")

    for url in external_pic_urls:
        placeholder = f"[IMG_URL:{url}]"
        if not any(placeholder in part for part in parts):
            parts.append(placeholder)

    if not parts:
        ids = re.findall(r'(@l[A-Za-z][A-Za-z0-9_/+-]{8,})', str(content_raw))
        media_ids.extend(ids)
        ct_map = {102: "[图片]", 1200: "[富文本/机器人消息]", 1300: "[链接卡片]", 2950: "[互动卡片]"}
        parts.append(ct_map.get(content_type, f"[contentType={content_type}]"))

    return " ".join(parts), list(set(media_ids))


def _dedupe_repeated_fts_text(text):
    """FTS 中部分富文本会把正文重复写入两次，这里仅折叠完全重复的两段。"""
    text = (text or "").strip()
    for match in re.finditer(r"\n{2,}", text):
        left = text[:match.start()].strip()
        right = text[match.end():].strip()
        if left and left == right:
            return left
    return text


def _extract_fts_text(content_raw, content_type):
    if not content_raw:
        return "", []

    text = _decode_unicode(str(content_raw))
    media_ids = re.findall(r'@l[A-Za-z][A-Za-z0-9_/+-]{8,}', text)
    text = re.sub(
        r'!\[.*?\]\((@l[A-Za-z][A-Za-z0-9_/+-]{8,})\)',
        r'[IMG:\1]',
        text,
    )
    external_image_urls = []

    def add_external_image_placeholder(url):
        if _is_external_image_url(url):
            external_image_urls.append(url.strip())

    text = _replace_external_image_markdown(text, add_external_image_placeholder)
    media_ids.extend(external_image_urls)
    text = re.sub(r'\n{3,}', '\n\n', text).strip()
    text = _dedupe_repeated_fts_text(text)
    text = re.sub(r'\n\s*\n\s*【[^】]+】：\s*$', '', text).strip()

    if not text:
        ct_map = {102: "[图片]", 1200: "[富文本/机器人消息]", 1300: "[链接卡片]", 2950: "[互动卡片]"}
        text = ct_map.get(content_type, f"[contentType={content_type}]")

    return text, list(set(media_ids))


# ── 消息查询 ──────────────────────────────────────────────

def _date_range_ms(date_str):
    dt = datetime.datetime.strptime(date_str, "%Y-%m-%d")
    start_ms = int(dt.replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)
    end_ms = int(dt.replace(hour=23, minute=59, second=59, microsecond=999000).timestamp() * 1000)
    return start_ms, end_ms


def _load_profiles(db_path):
    conn = sqlite3.connect(db_path)
    profiles = {}
    try:
        cur = conn.cursor()
        cur.execute("SELECT uid, nick FROM tbuser_profile_v2")
        for uid, nick in cur.fetchall():
            profiles[str(uid)] = nick
    except Exception:
        pass
    conn.close()
    return profiles


def _safe_int(value, default=0):
    try:
        return int(value)
    except Exception:
        return default


def _message_identity(sender_id, created_at, content_type):
    return (str(sender_id), _safe_int(created_at), str(content_type))


def _message_from_row(row, profiles, source, text_extractor):
    msg_id, sender_id, created_at, ct, content = row
    created_at_int = _safe_int(created_at)
    try:
        ts = created_at_int / 1000
        time_str = datetime.datetime.fromtimestamp(ts).strftime("%H:%M:%S")
    except Exception:
        time_str = str(created_at)

    sender_name = profiles.get(str(sender_id), str(sender_id))
    text, media_ids = text_extractor(content, ct)

    return {
        "id": msg_id,
        "senderId": str(sender_id),
        "sender": sender_name,
        "createdAt": created_at_int,
        "time": time_str,
        "text": text,
        "contentType": ct,
        "mediaIds": media_ids,
        "source": source,
    }


def _get_messages_from_main_db(db_path, cid, date_str, profiles=None):
    if profiles is None:
        profiles = _load_profiles(db_path)

    start_ms, end_ms = _date_range_ms(date_str)

    conn = sqlite3.connect(db_path)

    cur = conn.cursor()
    all_msgs = []
    for i in range(128):
        table = f"tbmsg_{i:03d}"
        try:
            cur.execute(
                f"SELECT mid, senderId, createdAt, contentType, content "
                f"FROM [{table}] WHERE cid=? AND createdAt >= ? AND createdAt <= ? "
                f"ORDER BY createdAt",
                (cid, start_ms, end_ms),
            )
            all_msgs.extend(cur.fetchall())
        except Exception:
            pass
    conn.close()

    all_msgs.sort(key=lambda x: x[2] or 0)

    messages = []
    all_media_ids = set()
    for mid, sender_id, created_at, ct, content in all_msgs:
        msg = _message_from_row((mid, sender_id, created_at, ct, content), profiles, "main", _extract_text)
        all_media_ids.update(msg["mediaIds"])
        messages.append(msg)

    return messages, all_media_ids


def _has_table(conn, table_name):
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table_name,))
    return cur.fetchone() is not None


def _get_messages_from_fts_db(fts_db_path, cid, date_str, profiles=None, existing_keys=None):
    if not fts_db_path:
        return [], set()
    if profiles is None:
        profiles = {}
    if existing_keys is None:
        existing_keys = set()

    start_ms, end_ms = _date_range_ms(date_str)
    conn = sqlite3.connect(fts_db_path)
    cur = conn.cursor()

    try:
        if _has_table(conn, "search_chat_index_name_fts_content"):
            cur.execute(
                "SELECT id, c0, c7, c4, c2 "
                "FROM search_chat_index_name_fts_content "
                "WHERE c1=? AND CAST(c7 AS INTEGER) >= ? AND CAST(c7 AS INTEGER) <= ? "
                "ORDER BY CAST(c7 AS INTEGER), id",
                (cid, start_ms, end_ms),
            )
        else:
            cur.execute(
                "SELECT rowid, senderId, createdAt, contentType, content "
                "FROM search_chat_index_name_fts "
                "WHERE cid=? AND CAST(createdAt AS INTEGER) >= ? AND CAST(createdAt AS INTEGER) <= ? "
                "ORDER BY CAST(createdAt AS INTEGER), rowid",
                (cid, start_ms, end_ms),
            )
        rows = cur.fetchall()
    except Exception:
        rows = []
    finally:
        conn.close()

    messages = []
    all_media_ids = set()
    for row in rows:
        _, sender_id, created_at, ct, _ = row
        key = _message_identity(sender_id, created_at, ct)
        if key in existing_keys:
            continue
        existing_keys.add(key)

        msg = _message_from_row(row, profiles, "fts", _extract_fts_text)
        all_media_ids.update(msg["mediaIds"])
        messages.append(msg)

    return messages, all_media_ids


def _get_messages(db_path, cid, date_str, fts_db_path=None):
    profiles = _load_profiles(db_path)
    main_messages, main_media_ids = _get_messages_from_main_db(db_path, cid, date_str, profiles)
    existing_keys = {
        _message_identity(msg.get("senderId"), msg.get("createdAt"), msg.get("contentType"))
        for msg in main_messages
    }

    fts_messages, fts_media_ids = _get_messages_from_fts_db(
        fts_db_path, cid, date_str, profiles, existing_keys
    )

    messages = main_messages + fts_messages
    messages.sort(key=lambda msg: (msg.get("createdAt") or 0, msg.get("id") or 0))
    return messages, main_media_ids | fts_media_ids


def _has_nonempty_export(conv_dir):
    md_path = os.path.join(conv_dir, "messages.md")
    return os.path.exists(md_path) and os.path.getsize(md_path) > 0


# ── 图片下载 ──────────────────────────────────────────────

def _create_thumbnail(original_path, thumbnails_dir):
    """为原图生成 JPEG 缩略图，返回缩略图文件名。"""
    try:
        from PIL import Image, ImageOps
    except ImportError as error:
        raise RuntimeError("缺少 Pillow，无法生成图片缩略图") from error

    os.makedirs(thumbnails_dir, exist_ok=True)
    thumbnail_name = f"{os.path.basename(original_path)}.jpg"
    thumbnail_path = os.path.join(thumbnails_dir, thumbnail_name)
    if os.path.exists(thumbnail_path):
        return thumbnail_name

    temporary_path = f"{thumbnail_path}.tmp"
    try:
        with Image.open(original_path) as source:
            image = ImageOps.exif_transpose(source)
            if image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info):
                background = Image.new("RGB", image.size, "white")
                alpha = image.getchannel("A") if image.mode == "RGBA" else image.convert("RGBA").getchannel("A")
                background.paste(image, mask=alpha)
                image = background
            elif image.mode != "RGB":
                image = image.convert("RGB")

            image.thumbnail((THUMBNAIL_MAX_SIZE, THUMBNAIL_MAX_SIZE), Image.Resampling.LANCZOS)
            image.save(temporary_path, format="JPEG", quality=82, optimize=True, progressive=True)
        os.replace(temporary_path, thumbnail_path)
    except Exception:
        if os.path.exists(temporary_path):
            os.remove(temporary_path)
        raise

    return thumbnail_name


def _download_images(media_ids, images_dir):
    os.makedirs(images_dir, exist_ok=True)
    thumbnails_dir = os.path.join(images_dir, "thumbs")
    image_map = {}

    if not media_ids:
        return image_map

    downloaded, skipped, failed = 0, 0, 0
    thumbnailed, thumbnail_failed = 0, 0
    for media_id in media_ids:
        if _is_external_image_url(media_id):
            image_url = media_id.strip()
            extension = os.path.splitext(urlsplit(image_url).path)[1].lower() or ".img"
            filename = f"external_{hashlib.sha256(image_url.encode('utf-8')).hexdigest()[:16]}{extension}"
        else:
            parsed = parse_media_id(media_id)
            if not parsed or not parsed.get("url"):
                image_map[media_id] = None
                failed += 1
                continue
            image_url = parsed["url"]
            bare = media_id.strip().lstrip("@")
            filename = f"{bare}_{parsed['width']}_{parsed['height']}.{parsed['type']}"
        local_path = os.path.join(images_dir, filename)

        if os.path.exists(local_path):
            image_map[media_id] = filename
            skipped += 1
            continue

        try:
            # 使用 curl 下载，因为 Python urllib 走代理时会被拦截（403），
            # 不走代理又无法 DNS 解析。curl 在此环境下可以正常通过代理。
            r = subprocess.run(
                ["curl", "-fsSL", "--retry", "2", "--retry-delay", "1", "-o", local_path, "--max-time", "30", image_url],
                capture_output=True,
            )
            if r.returncode == 0 and os.path.exists(local_path):
                image_map[media_id] = filename
                downloaded += 1
                try:
                    _create_thumbnail(local_path, thumbnails_dir)
                    thumbnailed += 1
                except Exception as e:
                    print(f"  ⚠️  缩略图生成失败: {filename} - {e}")
                    thumbnail_failed += 1
            else:
                raise RuntimeError(r.stderr.decode() or f"curl exit={r.returncode}")
        except Exception as e:
            print(f"  ⚠️  图片下载失败: {media_id} - {e}")
            image_map[media_id] = None
            failed += 1

    if downloaded + skipped + failed > 0:
        print(f"  📷 图片: 下载 {downloaded}, 已存在 {skipped}, 失败 {failed}")
    if thumbnailed + thumbnail_failed > 0:
        print(f"  🖼️  缩略图: 生成 {thumbnailed}, 失败 {thumbnail_failed}")

    return image_map


# ── Markdown 生成 ─────────────────────────────────────────

def _format_quote_block(value):
    lines = str(value or "").strip().splitlines()
    return "\n".join(f"> {line}" if line else ">" for line in lines)


def _format_reply_references(text):
    """把钉钉回复引用导出为标准 Markdown 引用块。"""
    if not text:
        return text

    pattern = re.compile(
        r"(?:^|\n)-{5,}\n-\n+"
        r"(?P<time>\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\n+"
        r"(?P<body>.*?)(?=\n---\n+\s*###\s+|\n-{5,}\n-\n+\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\n+|\Z)",
        re.S,
    )

    def repl(match):
        quote_lines = [
            f"**回复引用**：{match.group('time')}",
            "",
            match.group("body").strip(),
        ]
        return "\n\n" + _format_quote_block("\n".join(quote_lines))

    return pattern.sub(repl, text)


def _format_markdown(messages, image_map, conv_title, date_str):
    lines = [
        f"# {conv_title}",
        "",
        f"**日期**: {date_str}  ",
        f"**消息总数**: {len(messages)}  ",
        "",
    ]

    if not messages:
        lines.append(f"> 该会话在 {date_str} 无消息记录。")
        return "\n".join(lines)

    for msg in messages:
        lines.append("---")
        lines.append("")
        lines.append(f"### {msg['time']} - {msg['sender']}")

        text = msg.get("text", "") or ""

        for media_id in msg.get("mediaIds", []):
            local_file = image_map.get(media_id)
            old = f"[IMG_URL:{media_id}]" if _is_external_image_url(media_id) else f"[IMG:{media_id}]"
            if old in text:
                if local_file:
                    text = text.replace(old, f"![图片](images/{local_file})")
                else:
                    text = text.replace(old, f"*[图片下载失败]*")

        text = _format_reply_references(text)
        text = re.sub(r'\n{3,}', '\n\n', text).strip()

        if text:
            lines.append("")
            lines.append(text)
        else:
            ct = msg.get("contentType", 0)
            ct_map = {102: "[图片]", 1200: "[富文本/机器人消息]", 1300: "[链接卡片]", 2950: "[互动卡片]"}
            lines.append("")
            lines.append(f"*{ct_map.get(ct, f'[消息类型={ct}]')}*")

        lines.append("")

    return "\n".join(lines)


def _update_reader_raw_index(md_path, conv_title, date_str):
    """导出先知消息后，增量更新阅读器的原始消息索引。"""
    if conv_title != "先知" or not os.path.exists(READER_INDEX_PATH):
        return

    try:
        with open(READER_INDEX_PATH, "r", encoding="utf-8") as f:
            index = json.load(f)
        modules = index.get("modules")
        if index.get("version") != 1 or not isinstance(modules, dict) or not isinstance(modules.get("raw"), list):
            raise ValueError("索引格式无效")

        relative_path = os.path.relpath(md_path, PROJECT_ROOT).replace(os.sep, "/")
        stat = os.stat(md_path)
        timestamp = datetime.datetime.fromtimestamp(stat.st_mtime, datetime.timezone.utc).isoformat().replace("+00:00", "Z")
        item = {
            "filename": "messages.md",
            "title": f"{date_str} 原始消息",
            "shortTitle": f"{date_str} 原始消息",
            "path": relative_path,
            "type": "md",
            "category": "raw",
            "moduleId": "raw",
            "moduleName": "原始消息",
            "categoryLabel": "原始消息",
            "categoryDescription": "钉钉原始导出",
            "startDate": date_str,
            "endDate": None,
            "displayDate": date_str,
            "createdAt": timestamp,
            "modifiedAt": timestamp,
            "monthKey": date_str[:7],
            "size": stat.st_size,
            "dated": True,
            "order": 0,
        }
        raw_files = [entry for entry in modules["raw"] if entry.get("path") != relative_path]
        raw_files.append(item)
        raw_files.sort(key=lambda entry: (entry.get("startDate") or "", entry.get("path") or ""), reverse=True)
        modules["raw"] = raw_files
        index["updatedAt"] = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")

        temporary_path = f"{READER_INDEX_PATH}.tmp"
        with open(temporary_path, "w", encoding="utf-8") as f:
            json.dump(index, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(temporary_path, READER_INDEX_PATH)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"  ⚠️  阅读器索引未更新: {error}")


# ── 主流程 ────────────────────────────────────────────────

def main():
    if not EXPORT_TARGETS:
        print("❌ 请在 client_config.json 中配置 export_targets，例如:")
        print('  "export_targets": ["71904007638"]')
        sys.exit(1)

    date_str = sys.argv[1] if len(sys.argv) > 1 else datetime.datetime.now().strftime("%Y-%m-%d")
    try:
        datetime.datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        print(f"❌ 日期格式错误: {date_str}，请使用 YYYY-MM-DD")
        sys.exit(1)

    print("\n  📦 钉钉聊天导出")
    print(f"  📅 日期: {date_str}\n")

    # 1. 解密
    print("  清理临时解密目录...")
    _clean_dec_data()
    print("  🔓 解密数据库...")
    uid = _decrypt_storage_and_get_uid()
    db_path = _decrypt_dingtalk(uid)
    fts_db_path = _decrypt_dingtalk_fts(uid)
    print(f"  ✅ 解密完成 (UID={uid})")
    if fts_db_path:
        print("  🔎 已启用 FTS 补充来源: dingtalk.db_fts")

    # 2. 导出
    for cid in EXPORT_TARGETS:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("SELECT title FROM tbconversation WHERE cid=?", (cid,))
        row = cur.fetchone()
        conn.close()
        if not row:
            print(f"\n  ❌ 未找到会话 CID: {cid}")
            continue
        title = row[0] or cid

        conv_dir = os.path.join(OUTPUT_BASE, date_str,
                                re.sub(r'[<>:"/\\|?*]', '_', title).rstrip('. '))
        images_dir = os.path.join(conv_dir, "images")

        print(f"\n  📝 {title} ({cid})")
        print(f"  📂 {conv_dir}")

        messages, all_media_ids = _get_messages(db_path, cid, date_str, fts_db_path)
        fts_count = sum(1 for msg in messages if msg.get("source") == "fts")
        fts_note = f"，FTS补充 {fts_count} 条" if fts_count else ""
        print(f"  💬 {len(messages)} 条消息{fts_note}, {len(all_media_ids)} 张图片")

        if not messages and _has_nonempty_export(conv_dir):
            print("  ⚠️  本次结果为空，保留已有非空 messages.md，不覆盖")
            continue

        if os.path.exists(conv_dir):
            shutil.rmtree(conv_dir)

        image_map = {}

        if not messages:
            os.makedirs(conv_dir, exist_ok=True)
            md = _format_markdown([], {}, title, date_str)
        else:
            image_map = _download_images(all_media_ids, images_dir)
            md = _format_markdown(messages, image_map, title, date_str)

        os.makedirs(conv_dir, exist_ok=True)
        md_path = os.path.join(conv_dir, "messages.md")
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(md)
        _update_reader_raw_index(md_path, title, date_str)

        img_count = sum(1 for v in image_map.values() if v is not None)
        print(f"  ✅ messages.md ({len(messages)} 条, {img_count} 张图片)")

    print(f"\n  ✅ 导出完成 → {OUTPUT_BASE}/{date_str}/\n")


if __name__ == "__main__":
    main()
