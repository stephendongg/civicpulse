#!/usr/bin/env python3
"""
CivicPulse News Aggregator
--------------------------
Fetches local news from Google News RSS feed, classifies articles using 
OpenAI GPT-4, generates summaries, and outputs a JSON digest for the website.

Runs daily via GitHub Actions.
"""

# === Google News Local feed ===

import requests, feedparser, os, json, time
import pandas as pd
from urllib.parse import urlparse
from openai import OpenAI
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv() 

# Global Variable that allows us to specify the location
PLACE = "New York NY"

# Short header string = polite, but simple
HEADERS = {"User-Agent": "CivicPulse/0.1"}

def build_feed_url(place):
    """Return the Google News local RSS feed URL for a place."""
    base = "https://news.google.com/rss/local/section/geo/"
    tail = "?hl=en-US&gl=US&ceid=US:en"
    return base + requests.utils.quote(place) + tail

def fetch_feed(url):
    """Download and parse the RSS feed into a Python object."""
    r = requests.get(url, headers=HEADERS, timeout=20)
    r.raise_for_status()
    return feedparser.parse(r.text)

# Build URL and fetch results
feed_url = build_feed_url(PLACE)
feed = fetch_feed(feed_url)

print(f"Local feed URL:\n{feed_url}\n")
print(f"Found {len(feed.entries)} stories:\n")


# === Label Google News Local feed titles with CIN taxonomy ===

# --- 0) OpenAI setup ---
# Get API key from environment variable (set in GitHub Secrets)
api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    raise ValueError("OPENAI_API_KEY environment variable is required")

client = OpenAI(api_key=api_key)

MODEL = "gpt-4o-mini"   # fast & affordable
BATCH_SIZE = 25         # label many titles per API call
SLEEP_BETWEEN = 0.1     # short pause between calls


# --- 1) Build a DataFrame from the feed ---
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
        "feed_url": feed_url,
    })

df = pd.DataFrame(rows)
print(f"DataFrame built: {len(df)} rows")
print(df.head(5))

# --- 2) Taxonomy + instructions (4 main + community) ---
CIN_LABELS = [
    "risks_alerts",            # 1) Risks & Alerts - emergencies, safety, health alerts
    "civics_politics",         # 2) Civics & Politics - government, policy, elections
    "opportunities_welfare",   # 3) Opportunities & Welfare - jobs, services, benefits
    "community",               # 4) Community - events, culture, local interest
    "nonlocal",                # 5) Non-local/national/international news
    "other"                    # spillover
]

FEW_SHOTS = [
  # 1) risks_alerts - ONLY immediate ongoing threats
  {"title": "Active shooter reported at downtown mall - evacuate immediately", "label": "risks_alerts", "importance": 1.0},
  {"title": "Water main break triggers boil advisory downtown", "label": "risks_alerts", "importance": 0.8},
  {"title": "City issues heat advisory; cooling centers open", "label": "risks_alerts", "importance": 0.7},
  {"title": "Air quality alert due to wildfire smoke", "label": "risks_alerts", "importance": 0.8},
  {"title": "Major power outage affects 10,000 homes", "label": "risks_alerts", "importance": 0.8},

  # 2) civics_politics - including crime investigations
  {"title": "Police investigate shooting incident downtown", "label": "civics_politics", "importance": 0.3},
  {"title": "City Council passes $4.1B budget for sanitation", "label": "civics_politics", "importance": 0.7},
  {"title": "Judge blocks city plan to relocate migrant families", "label": "civics_politics", "importance": 0.6},
  {"title": "Mayoral candidate launches campaign rally", "label": "civics_politics", "importance": 0.4},
  {"title": "Teachers union and district reach tentative contract", "label": "civics_politics", "importance": 0.6},

  # 3) opportunities_welfare - jobs, services, benefits, healthcare, education services
  {"title": "City launches small-business training grants", "label": "opportunities_welfare", "importance": 0.6},
  {"title": "Job fair to feature apprenticeships and CDL roles", "label": "opportunities_welfare", "importance": 0.5},
  {"title": "County clinic adds free vaccination hours Saturday", "label": "opportunities_welfare", "importance": 0.5},
  {"title": "School calendar: holidays and parent-teacher nights", "label": "opportunities_welfare", "importance": 0.4},
  {"title": "Transit authority installs 80 EV chargers at hub", "label": "opportunities_welfare", "importance": 0.4},

  # 4) community - events, culture, entertainment, local interest, human stories
  {"title": "Museum hosts free night for city workers", "label": "community", "importance": 0.6},  # Was 0.4
  {"title": "River restoration project opens new trail access", "label": "community", "importance": 0.5},  # Was 0.3
  {"title": "Atlantic Antic celebrates 50 years with Brooklyn's biggest street fair", "label": "community", "importance": 0.6},  # Was 0.4
  {"title": "NY Liberty fires head coach", "label": "community", "importance": 0.4},  # Was 0.3


  # 5) nonlocal - national/international news
  {"title": "Putin Finds a Growing Embrace on the Global Stage", "label": "nonlocal", "importance": 0.1},
  {"title": "Fed should be independent but has made mistakes", "label": "nonlocal", "importance": 0.2},
  {"title": "Crime Crackdown in D.C. Shows Trump Administration's Policy", "label": "nonlocal", "importance": 0.2},
  {"title": "Xi, Putin and Modi Try to Signal Unity at China Summit", "label": "nonlocal", "importance": 0.1},
  {"title": "Supreme Court to hear case on federal immigration policy", "label": "nonlocal", "importance": 0.3},

  # other - unclear or doesn't fit main categories
  {"title": "Former official reveals Parkinson's diagnosis", "label": "other", "importance": 0.2},
]

def build_fewshot_block(fewshots):
    lines = [f'Headline: "{ex["title"]}"\nLabel: {ex["label"]}\nImportance: {ex.get("importance", 0.5)}' for ex in fewshots]
    return "Examples:\n\n" + "\n\n".join(lines)

FEW_SHOT_TEXT = build_fewshot_block(FEW_SHOTS)
SYSTEM_INSTRUCTIONS = f"""
You are a careful classifier for LOCAL news headlines for {PLACE}. Choose exactly ONE label from:
{', '.join(CIN_LABELS)}.

Definitions (map each headline to the single best-fitting domain):
1) RISKS_ALERTS — ONLY immediate ongoing threats: active emergencies, evacuation orders, active shooter situations, major infrastructure failures (power outages, bridge collapses), severe weather warnings requiring immediate action.

2) CIVICS_POLITICS — government services, city council, courts, budgets, ordinances, elections, campaigns, policy debates, union negotiations, official decisions, crime investigations, police incidents.

3) OPPORTUNITIES_WELFARE — jobs, job training, business assistance, healthcare services, education services, social programs, benefits, community resources.

4) COMMUNITY — local events, culture, arts, entertainment, sports, human interest stories, neighborhood news, celebrations, local personalities.

5) NONLOCAL — national/international news, federal policy, foreign affairs, stories not directly relevant to local residents.

6) OTHER — unclear or doesn't fit main categories.

CRITICAL RULE: If a crime has already happened and police are investigating, it goes to CIVICS_POLITICS, NOT RISKS_ALERTS. Only use RISKS_ALERTS for ongoing active threats requiring immediate action.

IMPORTANCE by category (0.0 = low, 1.0 = high):

RISKS_ALERTS:
- 1.0: Active threats, ongoing emergencies, immediate danger
- 0.8: Major safety issues, significant disruptions, health emergencies  
- 0.6: Safety alerts, weather warnings, traffic disruptions
- 0.2: Background safety news

CIVICS_POLITICS:
- 1.0: Major policy changes, emergency ordinances, election results
- 0.8: Budget decisions, significant government actions, major court rulings
- 0.6: Council meetings, policy debates, campaign developments
- 0.4: Administrative updates, minor policy changes, political commentary
- 0.3: Crime investigations, police incidents, routine government news
- 0.2: Political personalities, routine government news

OPPORTUNITIES_WELFARE:
- 1.0: Major service launches/closures, significant program changes
- 0.8: New job programs, major healthcare initiatives, education policy
- 0.6: Job fairs, training opportunities, service updates, school information
- 0.4: Program announcements, minor service changes
- 0.2: Individual success stories, routine program news

COMMUNITY:
- 0.6: Major cultural events, significant community developments
- 0.4: Local events, entertainment, neighborhood news
- 0.2: Individual achievements, human interest, routine community news

Tie-break priority if multiple seem plausible:
nonlocal > civics_politics > opportunities_welfare > community > risks_alerts > other.

IMPORTANT: Be aggressive about labeling as "nonlocal". If a story is primarily about national politics, international affairs, or federal policy (even if mentioned by local outlets), label it "nonlocal".

Return ONLY a JSON array. For each item:
{{"id": <int>, "category": <one of labels>, "confidence": <0..1>, "importance": <0..1>, "reason": "<=20 words>"}}

{FEW_SHOT_TEXT}
"""

# --- 3) Label in batches ---
def label_batch(titles_with_ids):
    """Send a batch of titles to GPT and get labels back."""
    enumerated_titles = "\n".join(f"{idx}. {title}" for idx, title in titles_with_ids)
    user_msg = f"Label these headlines:\n\n{enumerated_titles}"
    
    resp = client.chat.completions.create(
        model=MODEL,
        temperature=0,
        messages=[
            {"role": "system", "content": SYSTEM_INSTRUCTIONS},
            {"role": "user", "content": user_msg},
        ],
    )
    return resp.choices[0].message.content.strip()

# Prepare data for labeling
titles_list = df["title"].tolist()
all_labels = []

print(f"Labeling {len(titles_list)} titles in batches of {BATCH_SIZE}...")

for i in range(0, len(titles_list), BATCH_SIZE):
    batch_titles = titles_list[i:i+BATCH_SIZE]
    batch_with_ids = [(j, title) for j, title in enumerate(batch_titles, start=i)]
    
    try:
        raw_response = label_batch(batch_with_ids)
        parsed = json.loads(raw_response)
        all_labels.extend(parsed)
        print(f"Batch {i//BATCH_SIZE + 1}: Labeled {len(batch_titles)} items")
    except Exception as e:
        print(f"Error in batch {i//BATCH_SIZE + 1}: {e}")
        # Add fallback labels for this batch
        for j, title in batch_with_ids:
            all_labels.append({"id": j, "category": "other", "confidence": 0.0, "importance": 0.5, "reason": "labeling failed"})
    
    if SLEEP_BETWEEN > 0:
        time.sleep(SLEEP_BETWEEN)

# --- 4) Merge labels back into DataFrame ---
label_lookup = {item["id"]: item for item in all_labels}
df["category"] = [label_lookup.get(i, {"category": "other"})["category"] for i in range(len(df))]
df["confidence"] = [label_lookup.get(i, {"confidence": 0.0})["confidence"] for i in range(len(df))]
df["importance"] = [float(label_lookup.get(i, {"importance": 0.5})["importance"]) for i in range(len(df))]
df["reason"] = [label_lookup.get(i, {"reason": "unknown"})["reason"] for i in range(len(df))]

print("\nLabeling complete! Sample results:")
print(df[["title", "category", "confidence", "importance"]].head(10))

# Save labeled data
csv_path = f"local_news_labeled_{PLACE.replace(' ','_')}.csv"
df.to_csv(csv_path, index=False)
print(f"Saved labeled data to: {csv_path}")


# Filter out nonlocal content for summary generation
original_count = len(df)
df = df[df["category"] != "nonlocal"].reset_index(drop=True)
filtered_count = len(df)
nonlocal_removed = original_count - filtered_count

print(f"\nFiltered out {nonlocal_removed} nonlocal stories")
print(f"Keeping {filtered_count} local stories for civic digest")

# Filter for ONLY critical, actionable content
print(f"\nFiltering for CRITICAL actionable content...")

mask = (
    ((df["category"] == "risks_alerts") & (df["importance"] >= 0.5)) |
    ((df["category"] == "civics_politics") & (df["importance"] >= 0.5)) |
    ((df["category"] == "opportunities_welfare") & (df["importance"] >= 0.4)) |
    ((df["category"] == "community") & (df["importance"] >= 0.4)) |
    ((df["category"] == "other") & (df["importance"] >= 0.6))
)
df_for_summaries = df[mask].copy()

print(f"Keeping {len(df_for_summaries)} CRITICAL items (from {len(df)} total)")


# === Generate summaries for each category ===

# Order for final output
CIN_ORDER = [
    "risks_alerts", "civics_politics", "opportunities_welfare", "community", "other"
]

CIN_PRETTY = {
    "risks_alerts": "Risks & Alerts",
    "civics_politics": "Civics & Politics", 
    "opportunities_welfare": "Opportunities & Welfare",
    "community": "Community",
    "other": "Other"
}

# --- 1) Group by category and build context strings ---
per_section = {}
for cat in CIN_LABELS:
    # Use df_for_summaries instead of df - this contains only high-importance items
    subset = df_for_summaries[df_for_summaries["category"] == cat]
    if len(subset) == 0:
        continue

    # Sort by importance (highest first)
    subset = subset.sort_values("importance", ascending=False)
    
    lines = []
    for _, row in subset.iterrows():
        line = f"- {row['title']} - {row['source']} (source: {row['source']}, {row['published']})"
        lines.append(line)
        lines.append(f"  Link: {row['link']}")
    
    per_section[cat] = "\n".join(lines)

print("Categories with content:")
for cat, content in per_section.items():
    print(f"- {cat}: {len(content.splitlines())} lines")

# --- 2) Section examples for consistent formatting ---
SECTION_EXAMPLES = {
    "risks_alerts": {
        "bullets": [
            "Police investigate shooting incident downtown that left two injured. [↗](link)",
            "Water main break on Fifth Street causes service disruptions for 200 homes. [↗](link)",
            "Heat advisory issued with cooling centers opening citywide. [↗](link)"
        ]
    },
    "civics_politics": {
        "bullets": [
            "Council passes $4.1B sanitation budget in 8-2 vote. [↗](link)",
            "Mayoral candidate announces affordable housing platform. [↗](link)"
        ]
    },
    "opportunities_welfare": {
        "bullets": [
            "City launches small-business training grants for 200 entrepreneurs. [↗](link)",
            "Job fair features apprenticeships and CDL training opportunities. [↗](link)"
        ]
    }
}

def build_examples_text(examples_dict):
    """Convert examples dict to formatted text for prompts"""
    lines = []
    for category, content in examples_dict.items():
        pretty_name = CIN_PRETTY.get(category, category.title())
        lines.append(f"**{pretty_name} Example:**")
        for bullet in content["bullets"]:
            lines.append(f"- {bullet}")
        lines.append("")
    return "\n".join(lines)

EXAMPLES_TEXT = build_examples_text(SECTION_EXAMPLES)

# Updated SECTION_SYSTEM with examples
SECTION_SYSTEM = f"""
You are an editor summarizing local news for residents of {PLACE}.
Only include information that residents NEED to know to make decisions or take action.

FORMAT REQUIREMENTS:
- NO topline summary - go straight to bullets
- Include all genuinely important items (no arbitrary limits)
- Prioritize by importance: high importance items first
- Each bullet: 1 sentence (≤ 20 words), include [↗](URL) link
- Skip routine/background news that doesn't affect daily life
- Include timestamps only if timing is critical
- Follow the exact format shown in examples below

{EXAMPLES_TEXT}

Output Markdown following this exact format. Do not invent facts. Use provided URLs only.
"""

def summarize_section(cat_key, context):
    pretty = CIN_PRETTY.get(cat_key, cat_key.title())
    user_msg = f"""Domain: {pretty}
Items:
{context}

Write Markdown for this domain only. Do not invent facts. Include links as [↗](URL)."""
    resp = client.chat.completions.create(
        model=MODEL,
        temperature=0.2,
        messages=[
            {"role": "system", "content": SECTION_SYSTEM},
            {"role": "user", "content": user_msg},
        ],
    )
    return f"### {pretty}\n\n" + resp.choices[0].message.content.strip()

section_markdowns = []
sections_map = {}

for cat in CIN_ORDER:
    ctx = per_section.get(cat)
    if ctx:
        md_block = summarize_section(cat, ctx)
        section_markdowns.append(md_block)

        # NEW: also save a structured version
        sections_map[cat] = {
            "title": CIN_PRETTY.get(cat, cat.title()),
            "summary_md": md_block,
            "items": ctx.splitlines()  # keep minimal; replace later with a parser if you want
        }

# --- 4) (Optional) Global top line from all included items ---
all_ctx = "\n".join(per_section[c] for c in CIN_ORDER if c in per_section)
TOPLINE_SYSTEM = "Write a single 1–2 sentence 'Top Line' (<= 50 words) summarizing the most important cross-domain updates. Use only the provided items."
topline_resp = client.chat.completions.create(
    model=MODEL,
    temperature=0.2,
    messages=[
        {"role": "system", "content": TOPLINE_SYSTEM},
        {"role": "user", "content": all_ctx},
    ],
)
topline = topline_resp.choices[0].message.content.strip()

# --- 4.5) Generate daily positive fact ---
if len(df_for_summaries) > 0:
    POSITIVE_FACT_SYSTEM = """
    You are creating ONE positive, uplifting fact about New York City from the provided local news items.
    Choose something that highlights community resilience, innovation, or positive developments.
    
    IMPORTANT: 
    - Do NOT choose items that are already being summarized in the main civic updates sections.
    - Look for positive stories that are NOT in the high-importance civic content.
    - Make it a COMPLETE, SELF-CONTAINED fact that doesn't require clicking a link to understand.
    - Include specific details (names, places, numbers) from the news item so it's informative on its own.
    
    Format: One complete sentence (≤ 30 words) that is positive and uplifting.
    """
    
    # Get items that are NOT in the high-importance civic updates (to avoid redundancy)
    civic_titles = set(df_for_summaries["title"].tolist())
    non_civic_items = df[~df["title"].isin(civic_titles) & (df["category"] != "nonlocal")]
    
    # Look for positive items from community, opportunities, or other categories
    positive_candidates = non_civic_items[
        (non_civic_items["category"].isin(["community", "opportunities_welfare"])) |
        (non_civic_items["title"].str.contains("celebrate|open|launch|success|volunteer|donate|help", case=False, na=False))
    ]
    
    if len(positive_candidates) > 0:
        sample_items = positive_candidates.head(5)["title"].tolist()
        items_text = "\n".join([f"- {item}" for item in sample_items])
        
        fact_resp = client.chat.completions.create(
            model=MODEL,
            temperature=0.3,
            messages=[
                {"role": "system", "content": POSITIVE_FACT_SYSTEM},
                {"role": "user", "content": f"Items (NOT in main civic updates): {items_text}\n\nCreate a complete, self-contained positive fact from one of these items. Include specific details so readers don't need to click a link."},
            ],
        )
        daily_fact = fact_resp.choices[0].message.content.strip()
    else:
        daily_fact = "Stay engaged with your community through local news and civic participation."
else:
    daily_fact = "Stay engaged with your community through local news and civic participation."

# --- 5) Stitch final Markdown and save ---
final_md = topline + "\n\n" + "\n\n".join(section_markdowns)
print(final_md[:1500])

md_path = f"civicpulse_sections_{PLACE.replace(' ','_')}.md"
with open(md_path, "w", encoding="utf-8") as f:
    f.write(final_md)
print("Saved ->", md_path)

# === Create JSON output for website ===
final_json = {
    "place": PLACE,
    "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "daily_fact": daily_fact,
    "topline_md": topline,
    "order": [k for k in CIN_ORDER if k in sections_map],
    "sections": sections_map
}
json_path = f"civicpulse_digest_{PLACE.replace(' ','_')}.json"
with open(json_path, "w", encoding="utf-8") as f:
    json.dump(final_json, f, ensure_ascii=False, indent=2)
print("Saved ->", json_path)


# At the end, make sure to create the docs/nyc directory if it doesn't exist
os.makedirs("docs/nyc", exist_ok=True)

# Copy to docs/nyc folder for website
docs_json_path = f"docs/nyc/civicpulse_digest_{PLACE.replace(' ','_')}.json"
with open(docs_json_path, "w", encoding="utf-8") as f:
    json.dump(final_json, f, ensure_ascii=False, indent=2)
print("Copied to docs/nyc ->", docs_json_path)

print("\n✓ CivicPulse update complete!")