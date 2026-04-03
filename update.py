#!/usr/bin/env python3
"""
CivicPulse News Aggregator
--------------------------
Fetches local news from Google News RSS feed, classifies articles using
gpt-5.4, filters by importance, then generates structured JSON items per
section for the website.

Runs daily via GitHub Actions.
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlparse

import feedparser
import pandas as pd
import requests
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

ROOT = Path(__file__).resolve().parent
PLACE = "New York NY"
MODEL = "gpt-5.4"
HEADERS = {"User-Agent": "CivicPulse/0.1"}
BATCH_SIZE = 25
SLEEP_BETWEEN = 0.1

CIN_LABELS = [
    "risks_alerts",
    "civics_politics",
    "opportunities_welfare",
    "community",
    "nonlocal",
    "other",
]

CIN_ORDER = [
    "risks_alerts", "civics_politics", "opportunities_welfare", "community", "other"
]

CIN_PRETTY = {
    "risks_alerts": "Risks & Alerts",
    "civics_politics": "Civics & Politics",
    "opportunities_welfare": "Opportunities & Welfare",
    "community": "Community",
    "other": "Other",
}

FEW_SHOTS = [
    # 1) risks_alerts — ONLY immediate ongoing threats
    {"title": "Active shooter reported at downtown mall - evacuate immediately", "label": "risks_alerts", "importance": 1.0},
    {"title": "Water main break triggers boil advisory downtown", "label": "risks_alerts", "importance": 0.8},
    {"title": "City issues heat advisory; cooling centers open", "label": "risks_alerts", "importance": 0.7},
    {"title": "Air quality alert due to wildfire smoke", "label": "risks_alerts", "importance": 0.8},
    {"title": "Major power outage affects 10,000 homes", "label": "risks_alerts", "importance": 0.8},

    # 2) civics_politics — including crime investigations
    {"title": "Police investigate shooting incident downtown", "label": "civics_politics", "importance": 0.3},
    {"title": "City Council passes $4.1B budget for sanitation", "label": "civics_politics", "importance": 0.7},
    {"title": "Judge blocks city plan to relocate migrant families", "label": "civics_politics", "importance": 0.6},
    {"title": "Mayoral candidate launches campaign rally", "label": "civics_politics", "importance": 0.4},
    {"title": "Teachers union and district reach tentative contract", "label": "civics_politics", "importance": 0.6},

    # 3) opportunities_welfare — jobs, services, benefits, healthcare, education
    {"title": "City launches small-business training grants", "label": "opportunities_welfare", "importance": 0.6},
    {"title": "Job fair to feature apprenticeships and CDL roles", "label": "opportunities_welfare", "importance": 0.5},
    {"title": "County clinic adds free vaccination hours Saturday", "label": "opportunities_welfare", "importance": 0.5},
    {"title": "School calendar: holidays and parent-teacher nights", "label": "opportunities_welfare", "importance": 0.4},
    {"title": "Transit authority installs 80 EV chargers at hub", "label": "opportunities_welfare", "importance": 0.4},

    # 4) community — events, culture, entertainment, local interest, human stories
    {"title": "Museum hosts free night for city workers", "label": "community", "importance": 0.6},
    {"title": "River restoration project opens new trail access", "label": "community", "importance": 0.5},
    {"title": "Atlantic Antic celebrates 50 years with Brooklyn's biggest street fair", "label": "community", "importance": 0.6},
    {"title": "NY Liberty fires head coach", "label": "community", "importance": 0.4},

    # 5) nonlocal — national/international news
    {"title": "Putin Finds a Growing Embrace on the Global Stage", "label": "nonlocal", "importance": 0.1},
    {"title": "Fed should be independent but has made mistakes", "label": "nonlocal", "importance": 0.2},
    {"title": "Crime Crackdown in D.C. Shows Trump Administration's Policy", "label": "nonlocal", "importance": 0.2},
    {"title": "Xi, Putin and Modi Try to Signal Unity at China Summit", "label": "nonlocal", "importance": 0.1},
    {"title": "Supreme Court to hear case on federal immigration policy", "label": "nonlocal", "importance": 0.3},

    # 6) other — unclear or doesn't fit
    {"title": "Former official reveals Parkinson's diagnosis", "label": "other", "importance": 0.2},
]

IMPORTANCE_THRESHOLDS = {
    "risks_alerts": 0.5,
    "civics_politics": 0.5,
    "opportunities_welfare": 0.4,
    "community": 0.4,
    "other": 0.6,
}


def build_feed_url(place: str) -> str:
    base = "https://news.google.com/rss/local/section/geo/"
    tail = "?hl=en-US&gl=US&ceid=US:en"
    return base + requests.utils.quote(place) + tail


def fetch_feed(url: str) -> feedparser.FeedParserDict:
    r = requests.get(url, headers=HEADERS, timeout=20)
    r.raise_for_status()
    return feedparser.parse(r.text)


def parse_published_iso(raw: str) -> str:
    if not raw:
        return ""
    try:
        dt = parsedate_to_datetime(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (TypeError, ValueError):
        return ""


def build_fewshot_block(fewshots: list) -> str:
    lines = [
        f'Headline: "{ex["title"]}"\nLabel: {ex["label"]}\nImportance: {ex.get("importance", 0.5)}'
        for ex in fewshots
    ]
    return "Examples:\n\n" + "\n\n".join(lines)


def label_batch(client: OpenAI, titles_with_ids: list, system_instructions: str) -> str:
    enumerated = "\n".join(f"{idx}. {title}" for idx, title in titles_with_ids)
    resp = client.chat.completions.create(
        model=MODEL,
        temperature=0,
        messages=[
            {"role": "system", "content": system_instructions},
            {"role": "user", "content": f"Label these headlines:\n\n{enumerated}"},
        ],
    )
    return resp.choices[0].message.content.strip()


def summarize_section_structured(
    client: OpenAI, cat_key: str, subset: pd.DataFrame
) -> list[dict]:
    pretty = CIN_PRETTY.get(cat_key, cat_key.title())

    lines = []
    link_meta: dict[str, dict] = {}
    for _, row in subset.sort_values("importance", ascending=False).iterrows():
        lines.append(f"- {row['title']} - {row['source']} ({row['published']})")
        lines.append(f"  Link: {row['link']}")
        link_meta[row["link"]] = {
            "source": row.get("source", "Unknown"),
            "published_iso": parse_published_iso(row.get("published", "")),
        }
    context = "\n".join(lines)

    system_msg = f"""
You are an editor summarizing local news for residents of {PLACE}.
For the {pretty} section, return a JSON array of the most important items.

Each item must have:
- "title": clean, concise headline (≤ 15 words)
- "why_it_matters": one sentence (≤ 18 words) explaining local impact
- "link": exact URL from the provided list

Rules:
- Use only provided links — never invent URLs
- Include all genuinely important items, highest importance first
- Skip routine background news that does not affect daily life
- Output a JSON array only, no other text
""".strip()

    resp = client.chat.completions.create(
        model=MODEL,
        temperature=0.2,
        messages=[
            {"role": "system", "content": system_msg},
            {"role": "user", "content": f"Domain: {pretty}\n\nItems:\n{context}\n\nReturn JSON array only."},
        ],
    )

    raw = resp.choices[0].message.content.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    items_raw = json.loads(raw)
    valid_links = set(link_meta.keys())

    items = []
    for item in items_raw:
        link = (item.get("link") or "").strip()
        if link not in valid_links:
            continue
        meta = link_meta[link]
        items.append({
            "title": (item.get("title") or "").strip(),
            "source": meta["source"],
            "why_it_matters": (item.get("why_it_matters") or "").strip(),
            "link": link,
            "published_iso": meta["published_iso"],
        })

    return items


def generate_topline(client: OpenAI, per_section: dict) -> str:
    all_ctx = "\n".join(per_section[c] for c in CIN_ORDER if c in per_section)
    resp = client.chat.completions.create(
        model=MODEL,
        temperature=0.2,
        messages=[
            {"role": "system", "content": "Write a single 1–2 sentence 'Top Line' (≤ 50 words) summarizing the most important cross-domain updates. Use only the provided items."},
            {"role": "user", "content": all_ctx},
        ],
    )
    return resp.choices[0].message.content.strip()


def generate_daily_fact(client: OpenAI, df: pd.DataFrame, df_for_summaries: pd.DataFrame) -> str:
    civic_titles = set(df_for_summaries["title"].tolist())
    non_civic = df[~df["title"].isin(civic_titles) & (df["category"] != "nonlocal")]
    candidates = non_civic[
        (non_civic["category"].isin(["community", "opportunities_welfare"])) |
        (non_civic["title"].str.contains("celebrate|open|launch|success|volunteer|donate|help", case=False, na=False))
    ]

    if len(candidates) == 0:
        return "Stay engaged with your community through local news and civic participation."

    items_text = "\n".join(f"- {t}" for t in candidates.head(5)["title"].tolist())
    system_msg = """
You are creating ONE positive, uplifting fact about New York City from the provided local news items.
Make it a COMPLETE, SELF-CONTAINED fact with specific details (names, places, numbers).
Do NOT choose items already in the main civic updates.
Format: One complete sentence (≤ 30 words).
""".strip()

    resp = client.chat.completions.create(
        model=MODEL,
        temperature=0.3,
        messages=[
            {"role": "system", "content": system_msg},
            {"role": "user", "content": f"Items:\n{items_text}\n\nCreate a complete, self-contained positive fact."},
        ],
    )
    return resp.choices[0].message.content.strip()


def write_outputs(final_json: dict, place: str) -> None:
    slug = place.replace(" ", "_")
    content = json.dumps(final_json, ensure_ascii=False, indent=2)

    root_path = ROOT / f"civicpulse_digest_{slug}.json"
    root_path.write_text(content, encoding="utf-8")
    print(f"Saved -> {root_path.name}")

    docs_path = ROOT / "docs" / "nyc" / f"civicpulse_digest_{slug}.json"
    docs_path.parent.mkdir(parents=True, exist_ok=True)
    docs_path.write_text(content, encoding="utf-8")
    print(f"Saved -> {docs_path}")


def main() -> None:
    # --- Fetch feed ---
    feed_url = build_feed_url(PLACE)
    feed = fetch_feed(feed_url)
    print(f"Local feed URL:\n{feed_url}\n")
    print(f"Found {len(feed.entries)} stories\n")

    # --- Build DataFrame ---
    rows = []
    for e in feed.entries:
        title = getattr(e, "title", "").strip()
        link = getattr(e, "link", "")
        published = getattr(e, "published", "") or getattr(e, "updated", "")
        source = ""
        if hasattr(e, "source") and isinstance(e.source, dict):
            source = e.source.get("title") or ""
        rows.append({
            "place": PLACE,
            "title": title,
            "link": link,
            "published": published,
            "source": source,
            "domain": urlparse(link).netloc,
        })

    df = pd.DataFrame(rows)
    print(f"DataFrame built: {len(df)} rows")

    # --- OpenAI setup ---
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY environment variable is required")
    client = OpenAI(api_key=api_key)

    # --- Classification ---
    few_shot_text = build_fewshot_block(FEW_SHOTS)
    system_instructions = f"""
You are a careful classifier for LOCAL news headlines for {PLACE}. Choose exactly ONE label from:
{', '.join(CIN_LABELS)}.

Definitions:
1) RISKS_ALERTS — ONLY immediate ongoing threats: active emergencies, evacuation orders, major infrastructure failures, severe weather requiring immediate action.
2) CIVICS_POLITICS — government, city council, courts, budgets, elections, policy, union negotiations, crime investigations.
3) OPPORTUNITIES_WELFARE — jobs, training, healthcare services, social programs, benefits, community resources.
4) COMMUNITY — local events, culture, arts, entertainment, sports, human interest, neighborhood news.
5) NONLOCAL — national/international news not directly relevant to local residents.
6) OTHER — unclear or doesn't fit.

CRITICAL RULE: If a crime has already happened and police are investigating, use CIVICS_POLITICS, not RISKS_ALERTS.
IMPORTANT: Be aggressive about labeling as "nonlocal" for federal/international stories.

Tie-break priority: nonlocal > civics_politics > opportunities_welfare > community > risks_alerts > other.

Return ONLY a JSON array:
{{"id": <int>, "category": <label>, "confidence": <0..1>, "importance": <0..1>, "reason": "<=20 words"}}

{few_shot_text}
""".strip()

    titles_list = df["title"].tolist()
    all_labels: list[dict] = []
    print(f"Labeling {len(titles_list)} titles in batches of {BATCH_SIZE}...")

    for i in range(0, len(titles_list), BATCH_SIZE):
        batch = titles_list[i:i + BATCH_SIZE]
        batch_with_ids = [(j, title) for j, title in enumerate(batch, start=i)]
        try:
            raw = label_batch(client, batch_with_ids, system_instructions)
            all_labels.extend(json.loads(raw))
            print(f"Batch {i // BATCH_SIZE + 1}: labeled {len(batch)} items")
        except Exception as e:
            print(f"Error in batch {i // BATCH_SIZE + 1}: {e}")
            for j, _ in batch_with_ids:
                all_labels.append({"id": j, "category": "other", "confidence": 0.0, "importance": 0.5, "reason": "labeling failed"})
        if SLEEP_BETWEEN > 0:
            time.sleep(SLEEP_BETWEEN)

    label_lookup = {item["id"]: item for item in all_labels}
    df["category"]   = [label_lookup.get(i, {"category": "other"})["category"] for i in range(len(df))]
    df["confidence"] = [label_lookup.get(i, {"confidence": 0.0})["confidence"] for i in range(len(df))]
    df["importance"] = [float(label_lookup.get(i, {"importance": 0.5})["importance"]) for i in range(len(df))]
    df["reason"]     = [label_lookup.get(i, {"reason": "unknown"})["reason"] for i in range(len(df))]

    print("\nLabeling complete!")
    print(df[["title", "category", "confidence", "importance"]].head(10))

    csv_path = ROOT / f"local_news_labeled_{PLACE.replace(' ', '_')}.csv"
    df.to_csv(csv_path, index=False)
    print(f"Saved labeled data -> {csv_path.name}")

    # --- Filter ---
    df_local = df[df["category"] != "nonlocal"].reset_index(drop=True)
    print(f"\nFiltered out {len(df) - len(df_local)} nonlocal stories")

    mask = df_local.apply(
        lambda row: row["importance"] >= IMPORTANCE_THRESHOLDS.get(row["category"], 0.5),
        axis=1,
    )
    df_for_summaries = df_local[mask].copy()
    print(f"Keeping {len(df_for_summaries)} items for digest (from {len(df_local)} local)")

    # --- Build context strings for topline ---
    per_section: dict[str, str] = {}
    for cat in CIN_LABELS:
        subset = df_for_summaries[df_for_summaries["category"] == cat]
        if len(subset) == 0:
            continue
        subset = subset.sort_values("importance", ascending=False)
        lines = []
        for _, row in subset.iterrows():
            lines.append(f"- {row['title']} - {row['source']} ({row['published']})")
            lines.append(f"  Link: {row['link']}")
        per_section[cat] = "\n".join(lines)

    # --- Structured section summaries ---
    sections_map: dict[str, dict] = {}
    for cat in CIN_ORDER:
        subset = df_for_summaries[df_for_summaries["category"] == cat]
        if len(subset) == 0:
            continue
        print(f"Summarizing {cat} ({len(subset)} items)...")
        try:
            items = summarize_section_structured(client, cat, subset)
            if items:
                sections_map[cat] = {
                    "title": CIN_PRETTY.get(cat, cat.title()),
                    "items": items,
                }
        except Exception as e:
            print(f"Error summarizing {cat}: {e}")

    # --- Topline ---
    print("Generating topline...")
    topline = generate_topline(client, per_section)

    # --- Daily fact ---
    print("Generating daily fact...")
    daily_fact = generate_daily_fact(client, df_local, df_for_summaries)

    # --- Write outputs ---
    final_json = {
        "place": PLACE,
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "daily_fact": daily_fact,
        "topline_md": topline,
        "order": [k for k in CIN_ORDER if k in sections_map],
        "sections": sections_map,
    }
    write_outputs(final_json, PLACE)
    print("\n✓ CivicPulse update complete!")


if __name__ == "__main__":
    main()
