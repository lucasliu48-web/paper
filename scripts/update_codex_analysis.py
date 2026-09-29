"""Summarize new RSS entries with the locally signed-in Codex CLI."""

import argparse
import html
import json
import re
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FEED = ROOT / "filtered_feed.xml"
OUTPUT = ROOT / "codex_analyses.json"


def feed_items():
    for item in ET.parse(FEED).findall("./channel/item"):
        link = (item.findtext("link") or "").strip()
        if not link.startswith(("https://", "http://")):
            continue
        description = html.unescape(item.findtext("description") or "")
        description = re.sub(r"<[^>]*>", " ", description)
        yield {
            "link": link,
            "title": (item.findtext("title") or "").strip(),
            "description": " ".join(description.split())[:1200],
        }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=12)
    args = parser.parse_args()
    if args.limit < 1:
        parser.error("--limit must be positive")

    current = list(feed_items())
    existing = json.loads(OUTPUT.read_text(encoding="utf-8")) if OUTPUT.exists() else {"items": []}
    saved = {item["link"]: item for item in existing.get("items", [])}
    pending = [item for item in current if item["link"] not in saved][:args.limit]
    if not pending:
        print("No new RSS entries to analyze")
        return

    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["items"],
        "properties": {"items": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["link", "summary"],
                "properties": {"link": {"type": "string"}, "summary": {"type": "string"}},
            },
        }},
    }
    prompt = (
        "你是文献初筛助手。只根据下面的 RSS 题录和摘要，为每条写一句简洁、准确的中文分析，"
        "说明内容与可核验的局限。区分新闻、评论、书评和研究论文；不要猜测研究设计、样本、效果或全文结论。"
        "不要判断与用户研究方向的相关性，因为尚未提供研究问题。"
        "每条 link 原样返回，items 数量和输入相同；仅输出符合 schema 的 JSON。\n"
        + json.dumps(pending, ensure_ascii=False)
    )
    with tempfile.TemporaryDirectory() as tmp:
        schema_path = Path(tmp) / "schema.json"
        reply_path = Path(tmp) / "reply.json"
        schema_path.write_text(json.dumps(schema), encoding="utf-8")
        result = subprocess.run(
            ["codex", "exec", "-s", "read-only", "--ephemeral", "-C", str(ROOT),
             "--output-schema", str(schema_path), "-o", str(reply_path), "-"],
            input=prompt, text=True, capture_output=True, encoding="utf-8",
        )
        if result.returncode:
            raise RuntimeError("Codex CLI failed; existing analyses were left unchanged")
        generated = json.loads(reply_path.read_text(encoding="utf-8"))["items"]

    expected = {item["link"] for item in pending}
    links = [item["link"] for item in generated]
    if len(links) != len(expected) or set(links) != expected:
        raise ValueError("Codex response does not match the requested RSS entries")
    for item in generated:
        if not isinstance(item.get("summary"), str) or not 10 <= len(item["summary"]) <= 500:
            raise ValueError("Codex response contains an invalid summary")
        saved[item["link"]] = {"link": item["link"], "summary": item["summary"].strip()}
    ordered = [saved[item["link"]] for item in current if item["link"] in saved]
    payload = {
        "basis": "RSS title and description only",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "items": ordered,
    }
    staged = OUTPUT.with_suffix(".json.tmp")
    staged.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    staged.replace(OUTPUT)
    print(f"Analyzed {len(generated)} new entries; {len(ordered)} analyses saved")


if __name__ == "__main__":
    main()
