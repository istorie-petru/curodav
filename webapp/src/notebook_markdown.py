"""Notes as Markdown: Editor.js blocks to and from Markdown text, with a small YAML-style frontmatter header.

Endnotes become Markdown footnotes ([^1] with definitions at the end). Inline formatting that Markdown cannot hold (colours, wikilink markers) is dropped to plain text.
"""

from __future__ import annotations

import html
import json
import re

HEADING = re.compile(r"^(#{1,5})\s+(.*)$")
BULLET = re.compile(r"^(\s*)([-*+])\s+(.*)$")
ORDERED = re.compile(r"^(\s*)(\d+)[.)]\s+(.*)$")
FENCE = re.compile(r"^```\s*([\w+-]*)\s*$")
RULE = re.compile(r"^(-{3,}|\*{3,}|_{3,})\s*$")
TABLE_SEPARATOR = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")
RESERVED = {"title", "type", "template", "labels", "tags", "uid", "created", "updated"}


# Inline: editor HTML <-> Markdown

FOOTNOTE_REF = re.compile(r"<sup\b([^>]*)>.*?</sup>", re.S)
FOOTNOTE_MARK = re.compile(r"\[\^([^\]\s]+)\]")
FOOTNOTE_DEFINITION = re.compile(r"^\[\^([^\]\s]+)\]:[ \t]*(.*(?:\n(?:[ \t]+.*|))*)", re.M)


def _note_text(attributes: str) -> str:
    match = re.search(r'\sdata-note="([^"]*)"', " " + attributes)
    return inline_to_markdown(html.unescape(match.group(1))).replace("\n", " ").strip() if match else ""


def inline_to_markdown(markup: str, notes: list[str] | None = None) -> str:
    """Editor HTML to Markdown. With `notes`, each endnote marker becomes [^n] and its text is appended to the list."""
    text = markup or ""
    if notes is not None:
        def mark(match):
            if "cdx-footnote-ref" not in match.group(1):
                return ""
            notes.append(_note_text(match.group(1)))
            return f"[^{len(notes)}]"
        text = FOOTNOTE_REF.sub(mark, text)
    text = re.sub(r"<br\s*/?>", "\n", text)
    text = re.sub(r"<a\b[^>]*?href=\"([^\"]*)\"[^>]*>(.*?)</a>", lambda m: f"[{m.group(2)}]({html.unescape(m.group(1))})", text, flags=re.S)
    text = re.sub(r"<(b|strong)\b[^>]*>(.*?)</\1>", r"**\2**", text, flags=re.S)
    text = re.sub(r"<(i|em)\b[^>]*>(.*?)</\1>", r"*\2*", text, flags=re.S)
    text = re.sub(r"<(s|strike|del)\b[^>]*>(.*?)</\1>", r"~~\2~~", text, flags=re.S)
    text = re.sub(r"<code\b[^>]*>(.*?)</code>", r"`\1`", text, flags=re.S)
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text)


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def inline_from_markdown(text: str) -> str:
    codes: list[str] = []

    def stash(match):
        codes.append(f'<code class="inline-code">{match.group(1)}</code>')
        return f"\x00{len(codes) - 1}\x00"

    out = re.sub(r"`([^`]+)`", stash, _escape(text))
    out = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r'<a href="\2">\1</a>', out)
    out = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", out)
    out = re.sub(r"__([^_]+)__", r"<b>\1</b>", out)
    out = re.sub(r"~~([^~]+)~~", r"<s>\1</s>", out)
    out = re.sub(r"(^|[^*\w])\*([^*\s][^*]*?)\*(?!\*)", r"\1<i>\2</i>", out)
    out = re.sub(r"(^|[^_\w])_([^_\s][^_]*?)_(?!\w)", r"\1<i>\2</i>", out)
    return re.sub(r"\x00(\d+)\x00", lambda m: codes[int(m.group(1))], out)


# Blocks -> Markdown

def _list_lines(items: list, style: str, notes: list[str], depth: int = 0) -> list[str]:
    lines = []
    for number, item in enumerate(items, start=1):
        content = item if isinstance(item, str) else item.get("content", "")
        children = [] if isinstance(item, str) else item.get("items", [])
        marker = f"{number}." if style == "ordered" else "-"
        box = ""
        if style == "checklist":
            checked = isinstance(item, dict) and (item.get("meta") or {}).get("checked")
            box = "[x] " if checked else "[ ] "
        lines.append(f"{'  ' * depth}{marker} {box}{inline_to_markdown(content, notes)}")
        lines += _list_lines(children, style, notes, depth + 1)
    return lines


def _table(content: list[list[str]], notes: list[str]) -> str:
    if not content:
        return ""
    width = max(len(row) for row in content)
    rows = [[inline_to_markdown(c, notes).replace("|", "\\|").replace("\n", " ") for c in row] + [""] * (width - len(row)) for row in content]
    lines = ["| " + " | ".join(rows[0]) + " |", "| " + " | ".join("---" for _ in range(width)) + " |"]
    lines += ["| " + " | ".join(row) + " |" for row in rows[1:]]
    return "\n".join(lines)


def _timeline_lines(data: dict, notes: list[str]) -> list[str]:
    """A timeline as a list: "- date: title, description" for each entry that has any text."""
    lines = []
    for item in data.get("items") or []:
        when = (item.get("date") or "").strip()
        title = inline_to_markdown(item.get("title") or "", notes).strip()
        text = inline_to_markdown(item.get("description") or "", notes).strip()
        body = " ".join(part for part in (f"**{title}**" if title else "", text) if part)
        if when or body:
            lines.append("- " + (f"{when}: " if when and body else when) + body)
    return lines


def blocks_to_markdown(blocks: list[dict]) -> str:
    notes: list[str] = []
    parts = []
    for block in blocks or []:
        data = block.get("data") or {}
        kind = block.get("type")
        if kind == "header":
            parts.append("#" * max(1, min(5, int(data.get("level") or 2))) + " " + inline_to_markdown(data.get("text", ""), notes))
        elif kind == "paragraph":
            parts.append(inline_to_markdown(data.get("text", ""), notes))
        elif kind == "list":
            parts.append("\n".join(_list_lines(data.get("items", []), data.get("style", "unordered"), notes)))
        elif kind in ("quote", "callout"):
            text = inline_to_markdown(data.get("text", ""), notes)
            parts.append("\n".join("> " + line for line in text.split("\n")))
        elif kind == "code":
            parts.append(f"```{data.get('language', '') if data.get('language') != 'plaintext' else ''}\n{data.get('code', '')}\n```")
        elif kind == "delimiter":
            parts.append("---")
        elif kind == "timeline":
            parts.append("\n".join(_timeline_lines(data, notes)))
        elif kind == "table":
            parts.append(_table(data.get("content", []), notes))
        elif kind == "image":
            parts.append(f"![{inline_to_markdown(data.get('caption', ''))}]({data.get('url', '')})")
        elif kind == "html":
            parts.append(data.get("html", ""))
        elif data.get("text"):
            parts.append(inline_to_markdown(data["text"], notes))
    parts += [f"[^{n}]: {text}" for n, text in enumerate(notes, start=1)]
    return "\n\n".join(p for p in parts if p.strip()) + "\n"


# Markdown -> blocks

def _split_row(line: str) -> list[str]:
    inner = re.sub(r"^\s*\|", "", line)
    inner = re.sub(r"\|\s*$", "", inner)
    return [inline_from_markdown(c.strip()) for c in re.split(r"(?<!\\)\|", inner)]


def _build_list(lines: list[str]) -> dict:
    style = "ordered" if ORDERED.match(lines[0]) else "unordered"
    root: dict = {"items": []}
    stack = [(-1, root)]
    checklist = False
    for line in lines:
        m = BULLET.match(line) or ORDERED.match(line)
        indent = len(m.group(1).replace("\t", "  "))
        content = m.group(3)
        meta: dict = {}
        box = re.match(r"\[([ xX])\]\s+(.*)$", content)
        if box:
            checklist = True
            meta["checked"] = box.group(1).lower() == "x"
            content = box.group(2)
        item = {"content": inline_from_markdown(content), "meta": meta, "items": []}
        while len(stack) > 1 and stack[-1][0] >= indent:
            stack.pop()
        stack[-1][1]["items"].append(item)
        stack.append((indent, item))
    return {"style": "checklist" if checklist else style, "items": root["items"]}


def _endnote_marker(note_id: str, text: str) -> str:
    body = html.escape(inline_from_markdown(text), quote=True)
    return f'<sup class="cdx-footnote-ref" data-note-id="md-{re.sub(r"[^A-Za-z0-9_-]", "", note_id)}" data-note="{body}"></sup>'


def _apply_endnotes(value, notes: dict[str, str]):
    if isinstance(value, str):
        return FOOTNOTE_MARK.sub(lambda m: _endnote_marker(m.group(1), notes[m.group(1)]) if m.group(1) in notes else m.group(0), value)
    if isinstance(value, list):
        return [_apply_endnotes(v, notes) for v in value]
    if isinstance(value, dict):
        return {k: (v if k in ("code", "language") else _apply_endnotes(v, notes)) for k, v in value.items()}
    return value


def markdown_to_blocks(markdown: str) -> list[dict]:
    markdown = markdown.replace("\r\n", "\n").replace("\r", "\n")
    notes = {m.group(1): " ".join(m.group(2).split()) for m in FOOTNOTE_DEFINITION.finditer(markdown)}
    blocks = _markdown_blocks(FOOTNOTE_DEFINITION.sub("", markdown) if notes else markdown)
    return _apply_endnotes(blocks, notes) if notes else blocks


def _markdown_blocks(markdown: str) -> list[dict]:
    lines = markdown.split("\n")
    blocks: list[dict] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        m = FENCE.match(line)
        if m:
            code = []
            i += 1
            while i < len(lines) and not re.match(r"^```\s*$", lines[i]):
                code.append(lines[i])
                i += 1
            i += 1
            blocks.append({"type": "code", "data": {"code": "\n".join(code), "language": m.group(1) or "plaintext"}})
            continue
        m = HEADING.match(line)
        if m:
            blocks.append({"type": "header", "data": {"text": inline_from_markdown(m.group(2).strip()), "level": len(m.group(1))}})
            i += 1
            continue
        if RULE.match(line):
            blocks.append({"type": "delimiter", "data": {"style": "stars"}})
            i += 1
            continue
        if line.startswith(">"):
            quote = []
            while i < len(lines) and lines[i].startswith(">"):
                quote.append(re.sub(r"^>\s?", "", lines[i]))
                i += 1
            blocks.append({"type": "quote", "data": {"text": inline_from_markdown(" ".join(quote).strip()), "caption": "", "color": "blue"}})
            continue
        if "|" in line and i + 1 < len(lines) and TABLE_SEPARATOR.match(lines[i + 1]):
            rows = [_split_row(line)]
            i += 2
            while i < len(lines) and "|" in lines[i] and lines[i].strip():
                rows.append(_split_row(lines[i]))
                i += 1
            blocks.append({"type": "table", "data": {"withHeadings": True, "content": rows}})
            continue
        if BULLET.match(line) or ORDERED.match(line):
            items = []
            while i < len(lines) and (BULLET.match(lines[i]) or ORDERED.match(lines[i])):
                items.append(lines[i])
                i += 1
            blocks.append({"type": "list", "data": _build_list(items)})
            continue
        para = []
        while i < len(lines) and lines[i].strip() and not (
            HEADING.match(lines[i]) or FENCE.match(lines[i]) or RULE.match(lines[i]) or lines[i].startswith(">")
            or BULLET.match(lines[i]) or ORDERED.match(lines[i])
        ):
            para.append(lines[i].strip())
            i += 1
        blocks.append({"type": "paragraph", "data": {"text": inline_from_markdown(" ".join(para))}})
    return blocks


# Frontmatter

def _scalar(value):
    value = value.strip()
    try:
        return json.loads(value)
    except ValueError:
        pass
    if value.startswith("[") and value.endswith("]"):
        return [v.strip().strip("'\"") for v in value[1:-1].split(",") if v.strip()]
    return value.strip("'\"")


def split_frontmatter(text: str) -> tuple[dict, str]:
    text = text.lstrip("\ufeff")
    match = re.match(r"^---\s*\n(.*?)\n---\s*(?:\n|$)", text, flags=re.S)
    if not match:
        return {}, text
    meta: dict = {}
    key = None
    for raw in match.group(1).split("\n"):
        if re.match(r"^\s+-\s+", raw) and key:
            meta.setdefault(key, [])
            if not isinstance(meta[key], list):
                meta[key] = [meta[key]] if meta[key] else []
            meta[key].append(raw.split("-", 1)[1].strip().strip("'\""))
            continue
        pair = re.match(r"^([A-Za-z0-9_ .-]+):\s*(.*)$", raw)
        if pair:
            key = pair.group(1).strip()
            meta[key] = _scalar(pair.group(2)) if pair.group(2).strip() else ""
    return meta, text[match.end():]


def note_to_markdown(doc: dict, blocks: list[dict]) -> str:
    head = {"uid": doc["uid"], "title": doc["title"]}
    if doc.get("note_type"):
        head["type"] = doc["note_type"]
    if doc.get("is_template"):
        head["template"] = True
    if doc.get("journal_week"):
        head["week"] = doc["journal_week"]
    if doc.get("tags"):
        head["labels"] = doc["tags"]
    for prop in doc.get("properties", []):
        head[prop["key"]] = prop["value"]
    front = "\n".join(f"{k}: {json.dumps(v, ensure_ascii=False)}" for k, v in head.items())
    return f"---\n{front}\n---\n\n{blocks_to_markdown(blocks)}"


def parse_note(text: str, filename: str = "") -> dict:
    """A note from Markdown text: title, type, labels, template flag, other frontmatter as properties, and blocks."""
    meta, body = split_frontmatter(text)
    blocks = markdown_to_blocks(body)
    title = str(meta.get("title") or "").strip()
    if not title and blocks and blocks[0]["type"] == "header" and blocks[0]["data"]["level"] == 1:
        title = inline_to_markdown(blocks.pop(0)["data"]["text"]).strip()
    if not title:
        title = re.sub(r"\.(md|markdown)$", "", filename.rsplit("/", 1)[-1], flags=re.I).strip() or "Untitled"
    labels = meta.get("labels", meta.get("tags", []))
    labels = labels if isinstance(labels, list) else [labels] if labels else []
    properties = [
        {"key": k, "value": json.dumps(v) if isinstance(v, list) else str(v)}
        for k, v in meta.items() if k.lower() not in RESERVED and v not in ("", None)
    ]
    return {
        "uid": str(meta.get("uid") or ""), "title": title, "note_type": str(meta.get("type") or ""),
        "is_template": 1 if meta.get("template") in (True, "true", "True", 1) else 0,
        "tags": [str(x) for x in labels], "properties": properties, "blocks": blocks,
    }
