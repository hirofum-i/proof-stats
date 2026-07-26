# -*- coding: utf-8 -*-
"""Systeme.io → stats.json（広告LPソーシャルプルーフ用・集計値のみ）

⚠ ルール:
  - GET のみ（Systemeへの書き込みは実装しない = feedback_systeme_owner_only）
  - 出力は集計値と最新イベント時刻のみ。メール・名前など個人情報は一切含めない
  - 数える基準は「新規コンタクトのcreatedAt × タグ」= 保守的（既存リストの
    再オプトインは総数(total)にのみ反映）→ 表示が実態を上回ることは構造的にない

実行: SYSTEME_API_KEY を環境変数に置いて `python build_proof_stats.py`
出力: ./stats.json
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

BASE = os.environ.get("SYSTEME_API_BASE", "https://api.systeme.io/api")
JST = timezone(timedelta(hours=9))

# ファネル開始日（これ以前のcreatedAtは「新規」扱いにしない）
LAUNCH = datetime(2026, 7, 23, 0, 0, tzinfo=JST)

# Systemeが自動付与している実タグ名（2026-07-26 実測で確認）
LEAD_TAG = os.environ.get("PROOF_LEAD_TAG", "Lead: 老けない食事術オプトイン")
FE_TAG = os.environ.get("PROOF_FE_TAG", "Buyer: FE 10日間リセット")

MAX_PAGES = 60  # 100件/頁 × 60 = 6,000件で打ち切り（暴走防止）


def api_get(path, key, params=None):
    r = requests.get(f"{BASE}{path}", headers={"X-API-Key": key, "Accept": "application/json"},
                     params=params or {}, timeout=30)
    r.raise_for_status()
    return r.json()


def parse_dt(s):
    if not s:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%d %H:%M:%S"):
        try:
            d = datetime.strptime(s.replace("Z", "+0000"), fmt)
            return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def tag_names(c):
    out = []
    for t in c.get("tags", []) or []:
        out.append(t.get("name") if isinstance(t, dict) else str(t))
    return [n for n in out if n]


def fetch_all_contacts(key):
    """全コンタクトを新しい順に取得（タグ保持者の累計を数えるため全走査）"""
    out, cursor = [], None
    for _ in range(MAX_PAGES):
        params = {"limit": 100, "order": "desc"}
        if cursor:
            params["startingAfter"] = cursor
        j = api_get("/contacts", key, params)
        items = j.get("items", j if isinstance(j, list) else j.get("data", []))
        if not items:
            break
        out.extend(items)
        cursor = items[-1].get("id")
        if not cursor:
            break
    return out


def agg(contacts, tag, now):
    """タグ保持者の {h24, d7, total, latest_at} を返す。
    h24/d7/latest_at = 新規コンタクト（createdAt >= LAUNCH）ベース＝保守的。
    total = 全コンタクト中のタグ保持者数（既存リストの再オプトイン含む＝真の累計）。
    """
    h24 = d7 = total = 0
    latest = None
    for c in contacts:
        if tag not in tag_names(c):
            continue
        total += 1
        dt = parse_dt(c.get("createdAt") or c.get("registeredAt") or "")
        if dt is None or dt < LAUNCH:
            continue
        if latest is None or dt > latest:
            latest = dt
        if dt >= now - timedelta(hours=24):
            h24 += 1
        if dt >= now - timedelta(days=7):
            d7 += 1
    return {"h24": h24, "d7": d7, "total": total,
            "latest_at": latest.astimezone(JST).isoformat(timespec="seconds") if latest else None}


def main():
    key = os.environ.get("SYSTEME_API_KEY")
    if not key:
        sys.exit("環境変数 SYSTEME_API_KEY が未設定です")

    now = datetime.now(JST)
    contacts = fetch_all_contacts(key)

    stats = {
        "updated": now.isoformat(timespec="seconds"),
        "optin": agg(contacts, LEAD_TAG, now),
        "fe": agg(contacts, FE_TAG, now),
    }

    out = Path(__file__).parent / "stats.json"
    out.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"contacts走査: {len(contacts)}件")
    print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
