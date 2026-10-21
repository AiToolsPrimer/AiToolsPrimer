from __future__ import annotations

import os

from agency.platforms.base import Metrics, Platform, PublishItem, PublishResult


class Telegram(Platform):
    name = "telegram"
    label = "Telegram channel"
    kinds = {"post", "image", "video"}
    char_limit = 4096
    env = ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHANNEL")
    signup_url = "https://t.me/BotFather"
    api_docs = "https://core.telegram.org/bots/api"
    free_tier_note = "Free. Create a bot with @BotFather and make it an admin of your channel."

    @property
    def base(self) -> str:
        return f"https://api.telegram.org/bot{os.environ['TELEGRAM_BOT_TOKEN']}"

    def _publish(self, item: PublishItem) -> PublishResult:
        chat = os.environ["TELEGRAM_CHANNEL"]
        text = item.text if not item.link or item.link in item.text else f"{item.text}\n\n{item.link}"
        if item.media and item.media[0].suffix.lower() in {".mp4", ".mov"}:
            r = self.http.post(f"{self.base}/sendVideo", data={"chat_id": chat, "caption": text[:1024]}, files={"video": (item.media[0].name, item.media[0].read_bytes())})
        elif item.media:
            r = self.http.post(f"{self.base}/sendPhoto", data={"chat_id": chat, "caption": text[:1024]}, files={"photo": (item.media[0].name, item.media[0].read_bytes())})
        else:
            r = self.http.post(f"{self.base}/sendMessage", json={"chat_id": chat, "text": text, "disable_web_page_preview": False})
        out = self._json(r)
        if not out.get("ok"):
            return PublishResult(False, error=str(out))
        mid = out["result"]["message_id"]
        handle = chat.lstrip("@")
        return PublishResult(True, remote_id=str(mid), url=f"https://t.me/{handle}/{mid}" if not chat.startswith("-") else "")

    def _fetch_metrics(self, remote_id: str) -> Metrics:
        out = self._json(self.http.get(f"{self.base}/getChatMemberCount", params={"chat_id": os.environ["TELEGRAM_CHANNEL"]}))
        return Metrics(followers=out.get("result"))
