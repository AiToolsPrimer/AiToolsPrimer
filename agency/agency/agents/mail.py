"""Mail: reads the inbox (IMAP, read-only, never marks or moves anything), sorts messages,
pulls journalist requests out of digests, drafts replies and saves them as Gmail drafts.
It never sends."""
from __future__ import annotations

import datetime as dt
import email
import email.utils
import imaplib
import re
from email.header import decode_header
from email.message import EmailMessage
from typing import Any, Callable

from agency.agents.base import Agent
from agency.agents.factcheck import html_to_text
from agency.safety.policy import Action, ActionKind, Decision

DIGEST_SENDERS = ("sourceofsources", "featured.com", "sourcebottle", "qwoted", "helpab2bwriter", "haro", "connectively", "pressplugs", "journorequest")


class Mailbox:
    """Thin IMAP wrapper; ``connect`` is injectable so tests can pass a fake."""

    def __init__(self, host: str, user: str, password: str, connect: Callable[[str], Any] | None = None):
        self.host, self.user, self.password = host, user, password
        self._connect = connect or (lambda h: imaplib.IMAP4_SSL(h))

    def recent(self, days: int = 3, limit: int = 60) -> list[dict[str, Any]]:
        M = self._connect(self.host)
        try:
            M.login(self.user, self.password)
            M.select("INBOX", readonly=True)
            since = (dt.date.today() - dt.timedelta(days=days)).strftime("%d-%b-%Y")
            typ, data = M.search(None, f'(SINCE "{since}")')
            uids = (data[0].split() if typ == "OK" and data and data[0] else [])[-limit:]
            out = []
            for uid in uids:
                typ, msg_data = M.fetch(uid, "(BODY.PEEK[])")
                if typ != "OK" or not msg_data or not msg_data[0]:
                    continue
                raw = msg_data[0][1]
                msg = email.message_from_bytes(raw)
                out.append(_parse(uid.decode() if isinstance(uid, bytes) else str(uid), msg))
            return out
        finally:
            try:
                M.logout()
            except Exception:  # noqa: BLE001
                pass

    def save_draft(self, to: str, subject: str, body: str, from_addr: str) -> bool:
        msg = EmailMessage()
        msg["To"], msg["From"], msg["Subject"] = to, from_addr, subject
        msg["Date"] = email.utils.formatdate(localtime=True)
        msg.set_content(body)
        M = self._connect(self.host)
        try:
            M.login(self.user, self.password)
            for folder in ('"[Gmail]/Drafts"', "Drafts", "INBOX.Drafts"):
                typ, _ = M.append(folder, "\\Draft", imaplib.Time2Internaldate(dt.datetime.now().timestamp()), msg.as_bytes())
                if typ == "OK":
                    return True
            return False
        finally:
            try:
                M.logout()
            except Exception:  # noqa: BLE001
                pass


def _decode(value: str | None) -> str:
    if not value:
        return ""
    parts = decode_header(value)
    out = []
    for text, enc in parts:
        out.append(text.decode(enc or "utf-8", "ignore") if isinstance(text, bytes) else text)
    return "".join(out)


def _parse(uid: str, msg) -> dict[str, Any]:
    body = ""
    if msg.is_multipart():
        plain, html_part = "", ""
        for part in msg.walk():
            ctype = part.get_content_type()
            if ctype == "text/plain" and not plain:
                plain = part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", "ignore")
            elif ctype == "text/html" and not html_part:
                html_part = part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", "ignore")
        body = plain or html_to_text(html_part)
    else:
        payload = msg.get_payload(decode=True)
        text = payload.decode(msg.get_content_charset() or "utf-8", "ignore") if payload else ""
        body = html_to_text(text) if msg.get_content_type() == "text/html" else text
    name, addr = email.utils.parseaddr(_decode(msg.get("From")))
    date = msg.get("Date", "")
    try:
        when = email.utils.parsedate_to_datetime(date).isoformat(timespec="seconds")
    except Exception:  # noqa: BLE001
        when = date
    return {"uid": uid, "from": addr, "from_name": name, "subject": _decode(msg.get("Subject")), "date": when, "body": body[:20000]}


class MailAgent(Agent):
    role = "inbox assistant"
    desk = "mail"
    temperature = 0.3

    def __init__(self, llm, store, brand, mailbox: Mailbox | None, submit: Callable[[Action, dict[str, Any]], Decision], from_addr: str = ""):
        super().__init__(llm, store, brand)
        self.mailbox, self.submit, self.from_addr = mailbox, submit, from_addr

    def run(self, days: int = 3) -> dict[str, Any]:
        if self.mailbox is None:
            return {"skipped": "mail not configured"}
        if not self.submit(Action(ActionKind.READ_MAIL, "mail"), {}).allowed:
            return {"skipped": "read_mail switch is off"}
        with self.report("reading the inbox (read-only)"):
            messages = self.mailbox.recent(days=days)
            new = [m for m in messages if self.store.mail_is_new(m["uid"])]
            self.progress(f"{len(new)} new message(s)", 0, len(new))
            results = {"new": len(new), "journalist_requests": 0, "drafts": 0}
            for i, m in enumerate(new, 1):
                self.progress(m["subject"][:50], i, len(new))
                results["journalist_requests"] += self._handle(m)
            return results

    def _handle(self, m: dict[str, Any]) -> int:
        sender = (m["from"] + " " + m["subject"]).lower()
        if any(k in sender for k in DIGEST_SENDERS):
            reqs = self.extract_requests(m)
            self.store.add_mail(m, category="journalist_digest", summary=f"{len(reqs)} request(s)")
            return len(reqs)
        data = self.ask_json(
            f"Classify this email for {self.brand.name}.\nFrom: {m['from_name']} <{m['from']}>\nSubject: {m['subject']}\nBody:\n{m['body'][:6000]}\n\n"
            "Categories: journalist (a reporter asking for input), collaboration (partnership, guest post, podcast invite), reader (a question or thanks from a reader), "
            "platform (notices from social platforms or tools), newsletter, spam, other. If it deserves an answer, draft a short, warm, specific reply in English signed by the owner; "
            "never promise anything that costs money, never accept paid placements, never invent facts.\n"
            'Return JSON: {"category": "...", "summary": "one line", "urgent": false, "reply": "" }'
        )
        cat = str(data.get("category", "other"))
        mid = self.store.add_mail(m, category=cat, summary=str(data.get("summary", ""))[:300], urgent=bool(data.get("urgent")))
        reply = str(data.get("reply", "") or "").strip()
        if reply and cat in ("journalist", "collaboration", "reader"):
            self.store.add_mail_draft(mid, m["from"], f"Re: {m['subject']}", reply)
        return 0

    def extract_requests(self, m: dict[str, Any]) -> list[dict[str, Any]]:
        data = self.ask_json(
            f"This is a digest of journalist requests. Extract each request.\n{m['body'][:12000]}\n\n"
            f"Keep only requests a site about these pillars could answer with real expertise: {self.brand.pillars}. For each, the journalist's email appears in the text or not: "
            "copy it ONLY if it literally appears; never guess an address. Deadline as written.\n"
            'Return JSON: {"requests": [{"outlet": "...", "topic": "...", "query": "the full ask", "email": "", "deadline": "", "fit": 0.0-1.0, "guide_hint": "which of our guides answers it"}]}'
        )
        out = []
        for r in (data.get("requests", []) if isinstance(data, dict) else []):
            if not r.get("query") or float(r.get("fit", 0) or 0) < 0.4:
                continue   # not our field: no pitch, no noise
            addr = str(r.get("email", "") or "")
            if addr and addr.lower() not in m["body"].lower():
                addr = ""
            pid = self.store.add_pr_opportunity("journalist_request", m["subject"], contact=addr, summary=f"{r.get('outlet','')}: {r.get('topic','')}", detail=r.get("query", ""), deadline=str(r.get("deadline", "")), fit=float(r.get("fit", 0) or 0), extra={"guide_hint": r.get("guide_hint", ""), "mail_uid": m["uid"]})
            if pid:
                out.append({"id": pid, **r})
        return out

    def save_drafts_to_gmail(self) -> int:
        if self.mailbox is None or not self.from_addr:
            return 0
        n = 0
        for d in self.store.list_mail_drafts(status="drafted"):
            if self.mailbox.save_draft(d["to_addr"], d["subject"], d["body"], self.from_addr):
                self.store.set_mail_draft_status(d["id"], "in_gmail_drafts")
                n += 1
        return n
