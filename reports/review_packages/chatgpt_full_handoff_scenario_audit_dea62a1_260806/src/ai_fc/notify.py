"""텔레그램 알림 — 선택 기능, fail-soft (실패해도 파이프라인 무영향)."""

from __future__ import annotations

import json
import urllib.request

from . import config
from .models import DueItem


def send_message(text: str) -> bool:
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        return False
    try:
        url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
        data = json.dumps({"chat_id": config.TELEGRAM_CHAT_ID, "text": text}).encode()
        req = urllib.request.Request(url, data=data,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except Exception:  # noqa: BLE001 — 알림 실패는 절대 파이프라인을 막지 않는다
        return False


def send_digest(due: list[DueItem]) -> bool:
    if not due:
        return send_message("✅ ai-fc: due 없음 — 모든 질문이 cadence 내")
    lines = ["📋 ai-fc due 다이제스트"]
    for kind, icon in (("resolve", "⚖️"), ("forecast", "🔮"), ("stale", "⚠️"), ("manual-review", "✋")):
        items = [d for d in due if d.kind == kind]
        if items:
            lines.append(f"\n{icon} {kind} ({len(items)})")
            lines += [f"· {d.question_id} — {d.reason}" for d in items[:10]]
    return send_message("\n".join(lines))
