from __future__ import annotations

import datetime as dt
import json
import math
import os
import re
import sqlite3
import zipfile
from collections import Counter, defaultdict
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo


PROJECT = Path(__file__).resolve().parents[1]
HOME = Path.home()
CHATGPT_EXPORT_INBOX = Path("D:/ChatGPT Export")
CHATGPT_EXPORT_DOWNLOADS = Path("D:/Downloads")
GEMINI_EXPORT_INBOX = Path("D:/Gemini Export")
TIMEZONE = ZoneInfo("America/New_York")
DATA_PATH = PROJECT / "data" / "daily-burn.sample.json"
STATUS_PATH = PROJECT / "data" / "source-status.json"
OVERRIDES_PATH = PROJECT / "data" / "driver-overrides.json"
MAX_CHATGPT_EXPORT_BYTES = 150 * 1024 * 1024
MAX_GEMINI_EXPORT_BYTES = 150 * 1024 * 1024
MAX_EXPORT_SEARCH_FILES = 25_000
CHATGPT_CONVERSATION_MEMBER_RE = re.compile(
    r"(?:^|/)conversations(?:-\d+)?\.json$",
    re.IGNORECASE,
)
GEMINI_ACTIVITY_MEMBER_RE = re.compile(
    r"(?:^|/)My Activity/Gemini Apps/MyActivity\.html$",
    re.IGNORECASE,
)
GEMINI_WORKSPACE_MEMBER_RE = re.compile(
    r"(?:^|/)Gemini in Workspace/Conversation History/conversation_(\d+)\.txt$",
    re.IGNORECASE,
)
GEMINI_ACTIVITY_TIMESTAMP_RE = re.compile(
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) "
    r"\d{1,2}, \d{4}, \d{1,2}:\d{2}:\d{2}\s+(?:AM|PM)(?:\s+[A-Z]{2,5})?"
)
SKIP_EXPORT_DIRS = {
    ".git",
    ".next",
    ".venv",
    "__pycache__",
    "node_modules",
}

DRIVER_RULES = {
    "video": ("video", "walkthrough", "recording", "youtube", "transcript"),
    "review": ("review", "audit", "qa", "critique", "inspect", "verify"),
    "research": ("research", "compare", "benchmark", "investigate", "look up", "guide"),
    "planning": ("plan", "strategy", "roadmap", "schedule", "architecture", "design"),
    "writing": ("write", "draft", "copy", "newsletter", "document", "proposal", "summary"),
    "support": ("support", "troubleshoot", "fix", "error", "broken", "debug", "repair"),
    "admin": ("automation", "admin", "email", "calendar", "triage", "refresh", "maintenance"),
    "shipping": ("build", "implement", "dashboard", "app", "deploy", "ship", "create", "add"),
}


def main() -> None:
    codex, driver_scores, codex_status = load_codex()
    gemini, gemini_status = load_openclaw()
    gemini_export, gemini_export_status = load_gemini_export()
    chatgpt, chatgpt_status = load_chatgpt()
    overrides = load_overrides()

    days = sorted(set(codex) | set(gemini) | set(gemini_export) | set(chatgpt))
    rows = []
    for day in days:
        driver = overrides.get(day) or dominant_driver(driver_scores.get(day, Counter()))
        codex_tokens = codex.get(day, 0)
        gemini_tokens = gemini.get(day, 0)
        gemini_export_est = gemini_export.get(day, 0)
        chatgpt_est = chatgpt.get(day, 0)
        rows.append(
            {
                "date": day,
                "codex_tokens": codex_tokens,
                "gemini_openclaw_tokens": gemini_tokens,
                "gemini_export_est": gemini_export_est,
                "chatgpt_est": chatgpt_est,
                "total": codex_tokens + gemini_tokens + gemini_export_est + chatgpt_est,
                "driver": driver,
                "evidence": build_evidence(
                    codex_tokens,
                    gemini_tokens,
                    gemini_export_est,
                    chatgpt_est,
                    driver,
                ),
            }
        )

    DATA_PATH.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
    status = {
        "refreshed_at": dt.datetime.now(TIMEZONE).isoformat(timespec="seconds"),
        "timezone": "America/New_York",
        "sources": {
            "codex": codex_status,
            "gemini_openclaw": gemini_status,
            "gemini_export": gemini_export_status,
            "chatgpt": chatgpt_status,
        },
        "rows": len(rows),
        "first_date": rows[0]["date"] if rows else None,
        "last_date": rows[-1]["date"] if rows else None,
        "totals": {
            "codex_tokens": sum(codex.values()),
            "gemini_openclaw_tokens": sum(gemini.values()),
            "gemini_export_est": sum(gemini_export.values()),
            "chatgpt_est": sum(chatgpt.values()),
        },
    }
    STATUS_PATH.write_text(json.dumps(status, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(status, indent=2))


def load_codex() -> tuple[Counter[str], dict[str, Counter[str]], dict[str, Any]]:
    candidates = [
        HOME / ".codex" / "sqlite" / "state_5.sqlite",
        HOME / ".codex" / "state_5.sqlite",
    ]
    database = next((path for path in candidates if path.exists()), None)
    if not database:
        return Counter(), {}, {"fidelity": "exact", "status": "missing", "records": 0}

    totals: Counter[str] = Counter()
    driver_scores: dict[str, Counter[str]] = defaultdict(Counter)
    connection = sqlite3.connect(database)
    try:
        records = connection.execute(
            """
            select updated_at_ms, tokens_used, title
            from threads
            where tokens_used is not null and tokens_used > 0 and updated_at_ms is not null
            """
        ).fetchall()
    finally:
        connection.close()

    for updated_at_ms, tokens, title in records:
        day = local_day(updated_at_ms)
        totals[day] += int(tokens)
        driver_scores[day][classify(title or "")] += int(tokens)

    return totals, driver_scores, {
        "fidelity": "exact",
        "status": "loaded",
        "records": len(records),
        "database": database.name,
        "date_allocation": "thread last-updated day",
    }


def load_openclaw() -> tuple[Counter[str], dict[str, Any]]:
    totals: Counter[str] = Counter()
    records = 0
    models: Counter[str] = Counter()
    session_paths = list((HOME / ".openclaw" / "agents").glob("*/sessions/*.jsonl"))

    for path in session_paths:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                message = item.get("message")
                usage = message.get("usage") if isinstance(message, dict) else None
                tokens = usage.get("totalTokens") if isinstance(usage, dict) else None
                if not isinstance(tokens, (int, float)) or tokens < 0:
                    continue
                day = timestamp_day(item.get("timestamp"))
                if not day:
                    continue
                model = str(item.get("modelId") or message.get("model") or "unknown")
                totals[day] += int(tokens)
                models[model] += int(tokens)
                records += 1

    return totals, {
        "fidelity": "exact",
        "status": "loaded" if records else "missing",
        "records": records,
        "models": dict(models),
    }


def load_gemini_export() -> tuple[Counter[str], dict[str, Any]]:
    export = find_gemini_export()
    if not export:
        return Counter(), {
            "fidelity": "estimated",
            "status": "waiting_for_export",
            "records": 0,
            "method": "visible exported conversation text characters / 4",
        }

    totals: Counter[str] = Counter()
    records = 0
    activity_records = 0
    workspace_records = 0

    try:
        if export.stat().st_size > MAX_GEMINI_EXPORT_BYTES:
            raise ValueError("Gemini export is too large for the local refresh script")

        with zipfile.ZipFile(export) as archive:
            members = gemini_export_members(archive)
            if not members:
                raise ValueError("No supported Gemini history files in export")
            if sum(member.file_size for member in members) > MAX_GEMINI_EXPORT_BYTES:
                raise ValueError("Gemini history is too large for the local refresh script")

            for member in members:
                normalized_name = member.filename.replace("\\", "/")
                content = archive.read(member).decode("utf-8", errors="replace")
                if GEMINI_ACTIVITY_MEMBER_RE.search(normalized_name):
                    parsed, parsed_records = parse_gemini_activity(content)
                    totals.update(parsed)
                    records += parsed_records
                    activity_records += parsed_records
                    continue

                workspace_match = GEMINI_WORKSPACE_MEMBER_RE.search(normalized_name)
                if workspace_match:
                    day = timestamp_day(int(workspace_match.group(1)))
                    visible_characters = len(" ".join(content.split()))
                    if day and visible_characters:
                        totals[day] += max(1, math.ceil(visible_characters / 4))
                        records += 1
                        workspace_records += 1
    except (OSError, ValueError, zipfile.BadZipFile) as error:
        return Counter(), {
            "fidelity": "estimated",
            "status": "export_error",
            "records": 0,
            "error": type(error).__name__,
        }

    return totals, {
        "fidelity": "estimated",
        "status": "loaded",
        "records": records,
        "activity_records": activity_records,
        "workspace_conversations": workspace_records,
        "method": "visible exported conversation text characters / 4",
        "export": export.name,
    }


def find_gemini_export() -> Path | None:
    explicit = os.environ.get("GEMINI_EXPORT_PATH")
    if explicit:
        path = Path(explicit).expanduser()
        return path if path.is_file() else None

    if not GEMINI_EXPORT_INBOX.exists():
        return None

    candidates = []
    for path in GEMINI_EXPORT_INBOX.glob("*.zip"):
        try:
            with zipfile.ZipFile(path) as archive:
                if gemini_export_members(archive):
                    candidates.append(path)
        except (OSError, zipfile.BadZipFile):
            continue
    return max(candidates, key=lambda path: path.stat().st_mtime, default=None)


def gemini_export_members(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    return [
        member
        for member in archive.infolist()
        if GEMINI_ACTIVITY_MEMBER_RE.search(member.filename.replace("\\", "/"))
        or GEMINI_WORKSPACE_MEMBER_RE.search(member.filename.replace("\\", "/"))
    ]


def parse_gemini_activity(content: str) -> tuple[Counter[str], int]:
    parser = GeminiActivityParser()
    parser.feed(content)
    parser.close()
    return parser.totals, parser.records


class GeminiActivityParser(HTMLParser):
    """Extract dated, visible conversation text from Google Takeout activity cards."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.totals: Counter[str] = Counter()
        self.records = 0
        self.outer_depth = 0
        self.main_content_depth: int | None = None
        self.all_parts: list[str] = []
        self.main_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        classes = set(dict(attrs).get("class", "").split())
        if tag == "div" and not self.outer_depth and "outer-cell" in classes:
            self.outer_depth = 1
            self.all_parts = []
            self.main_parts = []
            return
        if not self.outer_depth:
            return
        if tag == "div":
            self.outer_depth += 1
            if (
                "content-cell" in classes
                and "mdl-cell--6-col" in classes
                and "mdl-typography--text-right" not in classes
            ):
                self.main_content_depth = self.outer_depth

    def handle_endtag(self, tag: str) -> None:
        if tag != "div" or not self.outer_depth:
            return
        if self.main_content_depth == self.outer_depth:
            self.main_content_depth = None
        self.outer_depth -= 1
        if not self.outer_depth:
            self.finish_card()

    def handle_data(self, data: str) -> None:
        if not self.outer_depth:
            return
        self.all_parts.append(data)
        if self.main_content_depth is not None:
            self.main_parts.append(data)

    def finish_card(self) -> None:
        all_text = " ".join(" ".join(self.all_parts).replace("\u202f", " ").split())
        main_text = " ".join(" ".join(self.main_parts).split())
        timestamp_match = GEMINI_ACTIVITY_TIMESTAMP_RE.search(all_text)
        if not timestamp_match or not main_text:
            return
        day = gemini_activity_day(timestamp_match.group(0))
        if not day:
            return
        self.totals[day] += max(1, math.ceil(len(main_text) / 4))
        self.records += 1


def gemini_activity_day(value: str) -> str | None:
    normalized = " ".join(value.replace("\u202f", " ").split())
    normalized = re.sub(r"\s+[A-Z]{2,5}$", "", normalized)
    try:
        parsed = dt.datetime.strptime(normalized, "%b %d, %Y, %I:%M:%S %p")
        return parsed.replace(tzinfo=TIMEZONE).date().isoformat()
    except ValueError:
        return None


def load_chatgpt() -> tuple[Counter[str], dict[str, Any]]:
    export = find_chatgpt_export()
    if not export:
        return Counter(), {
            "fidelity": "estimated",
            "status": "waiting_for_export",
            "records": 0,
            "method": "message text characters / 4",
        }

    try:
        conversations = read_conversations(export)
    except (OSError, ValueError, json.JSONDecodeError, zipfile.BadZipFile) as error:
        return Counter(), {
            "fidelity": "estimated",
            "status": "export_error",
            "records": 0,
            "error": type(error).__name__,
        }

    totals: Counter[str] = Counter()
    messages = 0
    seen: set[str] = set()
    for conversation in conversations:
        for message in conversation_messages(conversation):
            message_id = str(message.get("id") or "")
            if message_id and message_id in seen:
                continue
            if message_id:
                seen.add(message_id)
            text = message_text(message)
            day = timestamp_day(message.get("create_time"))
            if not text or not day:
                continue
            totals[day] += max(1, math.ceil(len(text) / 4))
            messages += 1

    return totals, {
        "fidelity": "estimated",
        "status": "loaded",
        "records": messages,
        "method": "message text characters / 4",
    }


def find_chatgpt_export() -> Path | None:
    explicit = os.environ.get("CHATGPT_EXPORT_PATH")
    if explicit:
        path = Path(explicit).expanduser()
        return path if path.is_file() else None

    validated_candidates = [
        *iter_chatgpt_inbox_candidates(CHATGPT_EXPORT_INBOX),
        *iter_chatgpt_inbox_candidates(CHATGPT_EXPORT_DOWNLOADS),
    ]

    roots = [
        HOME / "Downloads",
        HOME / "Documents",
        HOME / "Desktop",
        HOME / "OneDrive" / "Downloads",
        HOME / "OneDrive" / "Documents",
        HOME / "OneDrive" / "Desktop",
    ]
    candidates = [*validated_candidates, *iter_chatgpt_export_candidates(roots)]
    return max(candidates, key=lambda path: path.stat().st_mtime, default=None)


def iter_chatgpt_inbox_candidates(inbox: Path) -> Iterable[Path]:
    """Find validated exports in the private D: drive inbox.

    Any ZIP filename is accepted here because OpenAI export filenames can vary.
    ZIPs are only returned when they actually contain conversations.json.
    """
    if not inbox.exists():
        return

    for path in inbox.rglob("*"):
        if not path.is_file():
            continue
        if path.name.lower() == "conversations.json":
            yield path
            continue
        if path.suffix.lower() != ".zip":
            continue
        try:
            with zipfile.ZipFile(path) as archive:
                if chatgpt_conversation_members(archive):
                    yield path
        except (OSError, zipfile.BadZipFile):
            continue


def read_conversations(path: Path) -> list[dict[str, Any]]:
    if path.stat().st_size > MAX_CHATGPT_EXPORT_BYTES:
        raise ValueError("ChatGPT export is too large for the local refresh script")

    if path.suffix.lower() == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
    else:
        with zipfile.ZipFile(path) as archive:
            members = chatgpt_conversation_members(archive)
            if not members:
                raise ValueError("No ChatGPT conversation history files in export")
            if sum(member.file_size for member in members) > MAX_CHATGPT_EXPORT_BYTES:
                raise ValueError("ChatGPT conversation history is too large for the local refresh script")
            payload = []
            for member in members:
                part = json.loads(archive.read(member))
                if not isinstance(part, list):
                    raise ValueError(f"Unexpected ChatGPT export payload in {member.filename}")
                payload.extend(part)
    return payload if isinstance(payload, list) else []


def chatgpt_conversation_members(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    """Return full conversation-history parts, excluding shared_conversations.json."""
    return sorted(
        (
            member
            for member in archive.infolist()
            if CHATGPT_CONVERSATION_MEMBER_RE.search(member.filename.replace("\\", "/"))
        ),
        key=lambda member: member.filename.lower(),
    )


def iter_chatgpt_export_candidates(roots: Iterable[Path]) -> Iterable[Path]:
    checked = 0
    seen: set[Path] = set()
    for root in roots:
        if not root.exists():
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [
                dirname
                for dirname in dirnames
                if dirname not in SKIP_EXPORT_DIRS and not dirname.startswith(".")
            ]
            for filename in filenames:
                checked += 1
                if checked > MAX_EXPORT_SEARCH_FILES:
                    return
                lower_name = filename.lower()
                if lower_name != "conversations.json" and not (
                    lower_name.endswith(".zip")
                    and re.search(r"(chatgpt|openai|data[_ -]?export|export)", lower_name, re.I)
                ):
                    continue
                path = Path(dirpath) / filename
                resolved = path.resolve()
                if resolved in seen:
                    continue
                seen.add(resolved)
                yield path


def conversation_messages(conversation: dict[str, Any]) -> Iterable[dict[str, Any]]:
    mapping = conversation.get("mapping")
    if not isinstance(mapping, dict):
        return []
    return [
        node["message"]
        for node in mapping.values()
        if isinstance(node, dict) and isinstance(node.get("message"), dict)
    ]


def message_text(message: dict[str, Any]) -> str:
    content = message.get("content")
    if not isinstance(content, dict):
        return ""
    parts = content.get("parts")
    if not isinstance(parts, list):
        return ""
    return "\n".join(part for part in parts if isinstance(part, str))


def classify(title: str) -> str:
    normalized = title.lower()
    scores = {
        driver: sum(1 for keyword in keywords if keyword in normalized)
        for driver, keywords in DRIVER_RULES.items()
    }
    best = max(scores, key=scores.get)
    return best if scores[best] else "shipping"


def dominant_driver(scores: Counter[str]) -> str:
    return scores.most_common(1)[0][0] if scores else "shipping"


def load_overrides() -> dict[str, str]:
    if not OVERRIDES_PATH.exists():
        return {}
    payload = json.loads(OVERRIDES_PATH.read_text(encoding="utf-8"))
    allowed = set(DRIVER_RULES)
    return {
        day: driver
        for day, driver in payload.items()
        if isinstance(day, str) and driver in allowed
    }


def build_evidence(
    codex: int,
    gemini: int,
    gemini_export: int,
    chatgpt: int,
    driver: str,
) -> str:
    sources = []
    if codex:
        sources.append("Codex exact")
    if gemini:
        sources.append("Gemini/Open Claw exact")
    if gemini_export:
        sources.append("Gemini export estimated")
    if chatgpt:
        sources.append("ChatGPT estimated")
    return f"{', '.join(sources) or 'No measured usage'}; scrubbed {driver} day"


def local_day(milliseconds: int | float) -> str:
    timestamp = float(milliseconds) / 1000
    return dt.datetime.fromtimestamp(timestamp, dt.timezone.utc).astimezone(TIMEZONE).date().isoformat()


def timestamp_day(value: Any) -> str | None:
    try:
        if isinstance(value, (int, float)):
            timestamp = float(value) / 1000 if value > 1_000_000_000_000 else float(value)
            parsed = dt.datetime.fromtimestamp(timestamp, dt.timezone.utc)
        else:
            parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=dt.timezone.utc)
        return parsed.astimezone(TIMEZONE).date().isoformat()
    except (ValueError, TypeError, OSError):
        return None


if __name__ == "__main__":
    main()
