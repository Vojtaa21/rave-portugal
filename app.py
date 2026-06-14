import streamlit as st
import requests
from datetime import date, timedelta
import pandas as pd
from bs4 import BeautifulSoup
import json

# ═══════════════════════════════════════════════════════════════
#  KONFIGURACE
# ═══════════════════════════════════════════════════════════════

MESTA = {
    "Porto":   {"ra_area_id": 364, "sk_city_slug": "porto"},
    "Lisabon": {"ra_area_id": 53,  "sk_city_slug": "lisbon"},
}

ZANRY_MOZNOSTI = [
    "Techno", "Acid Techno", "Hard Techno", "Industrial Techno",
    "Drum & Bass", "Jump Up", "Liquid Funk", "Neurofunk",
    "Trance", "Psytrance", "Uplifting Trance",
    "House", "Acid House", "Deep House", "Tech House",
    "Hardcore", "Gabber", "Frenchcore",
    "Electronic", "Electronica", "Ambient", "Industrial",
    "Breakbeat", "Jungle", "Minimal", "EBM", "Noise",
]

RA_URL = "https://ra.co/graphql"
RA_HEADERS = {
    "Content-Type": "application/json",
    "Referer": "https://ra.co/events",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
}
SK_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

RA_QUERY = """
query GET_DEFAULT_EVENTS_OVERVIEW($filters: FilterInputDtoInput, $pageSize: Int, $page: Int) {
  eventListings(filters: $filters, pageSize: $pageSize, page: $page) {
    data {
      event {
        id title date startTime contentUrl attending
        venue { name address }
        artists { name }
        genres { name }
      }
    }
    totalResults
  }
}
"""

# ═══════════════════════════════════════════════════════════════
#  DATOVÉ FUNKCE
# ═══════════════════════════════════════════════════════════════

def fetch_ra(area_id: int, date_from: date, date_to: date) -> list[dict]:
    payload = {
        "query": RA_QUERY,
        "variables": {
            "filters": {
                "areas": {"eq": area_id},
                "listingDate": {
                    "gte": date_from.strftime("%Y-%m-%dT00:00:00.000Z"),
                    "lte": date_to.strftime("%Y-%m-%dT23:59:59.999Z"),
                },
            },
            "pageSize": 100,
            "page": 1,
        },
    }
    try:
        r = requests.post(RA_URL, headers=RA_HEADERS, json=payload, timeout=15)
        r.raise_for_status()
        data = r.json()
        if "errors" in data:
            return []
        listings = data.get("data", {}).get("eventListings", {})
        return [item["event"] for item in listings.get("data", [])]
    except Exception:
        return []


def parse_ra(events: list[dict]) -> list[dict]:
    rows = []
    for e in events:
        genres = [g["name"] for g in e.get("genres", [])]
        datum = (e.get("date") or "")[:10]
        cas_raw = e.get("startTime", "")
        cas = cas_raw.split("T")[1][:5] if cas_raw and "T" in cas_raw else "—"
        venue = e.get("venue") or {}
        rows.append({
            "datum":    datum,
            "cas":      cas,
            "nazev":    e.get("title", "—"),
            "venue":    venue.get("name", "—"),
            "interpreti": ", ".join(a["name"] for a in e.get("artists", [])) or "—",
            "zanry":    ", ".join(genres) if genres else "",
            "zdroj":    "RA",
            "odkaz":    f"https://ra.co{e['contentUrl']}" if e.get("contentUrl") else "",
        })
    return rows


SK_METRO = {"porto": 28758, "lisbon": 28863}

def fetch_songkick(city_slug: str, date_from: date, date_to: date) -> list[dict]:
    rows = []
    metro_id = SK_METRO.get(city_slug, 28758)
    page = 1
    while page <= 5:
        url = (
            f"https://www.songkick.com/metro_areas/{metro_id}/calendar"
            f"?utf8=%E2%9C%93&filters%5BminDate%5D={date_from.strftime('%Y-%m-%d')}"
            f"&filters%5BmaxDate%5D={date_to.strftime('%Y-%m-%d')}&page={page}"
        )
        try:
            r = requests.get(url, headers=SK_HEADERS, timeout=15)
            if r.status_code != 200:
                break
            soup = BeautifulSoup(r.text, "html.parser")
            scripts = soup.find_all("script", type="application/ld+json")
            found = False
            for sc in scripts:
                try:
                    data = json.loads(sc.string or "")
                    items = data if isinstance(data, list) else [data]
                    for item in items:
                        if item.get("@type") not in ("MusicEvent", "Event"):
                            continue
                        found = True
                        start = item.get("startDate", "")
                        datum = start[:10] if start else "—"
                        cas = start[11:16] if len(start) > 10 else "—"
                        ev_date = date.fromisoformat(datum) if datum != "—" else None
                        if ev_date and not (date_from <= ev_date <= date_to):
                            continue
                        location = item.get("location", {})
                        venue_name = location.get("name", "—") if isinstance(location, dict) else "—"
                        performers = item.get("performer", [])
                        if isinstance(performers, dict):
                            performers = [performers]
                        interpreti = ", ".join(p.get("name", "") for p in performers) or "—"
                        rows.append({
                            "datum":      datum,
                            "cas":        cas,
                            "nazev":      item.get("name", "—"),
                            "venue":      venue_name,
                            "interpreti": interpreti,
                            "zanry":      "",
                            "zdroj":      "Songkick",
                            "odkaz":      item.get("url", ""),
                        })
                except Exception:
                    continue
            if not found:
                break
            if not soup.select_one("a[rel='next']"):
                break
            page += 1
        except Exception:
            break
    return rows


def genre_matches(row: dict, selected: list[str]) -> bool:
    if not selected:
        return True
    text = f"{row['zanry']} {row['interpreti']} {row['nazev']}".lower()
    return any(s.lower() in text for s in selected)


def deduplicate(rows: list[dict]) -> list[dict]:
    seen = set()
    result = []
    for r in rows:
        key = (r["datum"], r["nazev"].lower()[:40])
        if key not in seen:
            seen.add(key)
            result.append(r)
    return result


# ═══════════════════════════════════════════════════════════════
#  DESIGN SYSTÉM
# ═══════════════════════════════════════════════════════════════

st.set_page_config(page_title="Rave Portugal", page_icon="🎛️", layout="wide")

st.markdown("""
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;700&family=Space+Mono:wght@400;700&display=swap" rel="stylesheet">

<style>
/* ── Reset & Base ── */
html, body, [class*="css"] {
    font-family: 'Space Grotesk', sans-serif !important;
}
.stApp { background: #0a0a0a !important; }
.stApp > header { background: transparent !important; }
section[data-testid="stSidebar"] {
    background: #0f0f0f !important;
    border-right: 0.5px solid #1d1d1d !important;
}
section[data-testid="stSidebar"] * { color: #888 !important; }
section[data-testid="stSidebar"] .stSelectbox label,
section[data-testid="stSidebar"] .stMultiSelect label,
section[data-testid="stSidebar"] .stDateInput label {
    color: #555 !important;
    font-family: 'Space Mono', monospace !important;
    font-size: 10px !important;
    letter-spacing: 2px !important;
    text-transform: uppercase !important;
}

/* ── Sidebar inputs ── */
section[data-testid="stSidebar"] .stSelectbox > div > div,
section[data-testid="stSidebar"] .stMultiSelect > div > div,
section[data-testid="stSidebar"] .stDateInput > div > div > input {
    background: #151515 !important;
    border: 0.5px solid #2a2a2a !important;
    color: #ccc !important;
    border-radius: 6px !important;
}
section[data-testid="stSidebar"] .stMultiSelect span[data-baseweb="tag"] {
    background: #1a1e00 !important;
    color: #d4ff00 !important;
    border: 0.5px solid #3a4400 !important;
    border-radius: 4px !important;
    font-family: 'Space Mono', monospace !important;
    font-size: 10px !important;
}

/* ── Search button ── */
div.stButton > button {
    background: #d4ff00 !important;
    color: #0a0a0a !important;
    font-family: 'Space Mono', monospace !important;
    font-weight: 700 !important;
    font-size: 11px !important;
    letter-spacing: 2px !important;
    border: none !important;
    border-radius: 6px !important;
    padding: 0.6rem 1.5rem !important;
    width: 100% !important;
    margin-top: 8px !important;
}
div.stButton > button:hover {
    background: #c0e800 !important;
    color: #0a0a0a !important;
}

/* ── Main content text ── */
.block-container { padding-top: 2rem !important; }
h1, h2, h3 { color: #f0f0f0 !important; }
p, li { color: #888 !important; }

/* ── Download button ── */
div.stDownloadButton > button {
    background: transparent !important;
    border: 0.5px solid #2a2a2a !important;
    color: #555 !important;
    font-family: 'Space Mono', monospace !important;
    font-size: 10px !important;
    letter-spacing: 1px !important;
    border-radius: 6px !important;
}
div.stDownloadButton > button:hover {
    border-color: #d4ff00 !important;
    color: #d4ff00 !important;
}

/* ── Success / info messages ── */
div[data-testid="stAlert"] {
    background: #111 !important;
    border: 0.5px solid #2a2a2a !important;
    border-radius: 6px !important;
    color: #888 !important;
}

/* ── Spinner ── */
.stSpinner > div { border-top-color: #d4ff00 !important; }

/* ── Expander ── */
details { background: #111 !important; border: 0.5px solid #1d1d1d !important; border-radius: 6px !important; }
details summary { color: #555 !important; font-family: 'Space Mono', monospace !important; font-size: 11px !important; }
details a { color: #d4ff00 !important; }
</style>
""", unsafe_allow_html=True)

# ─── Hero header ─────────────────────────────────────────────
st.markdown("""
<div style="margin-bottom: 2rem;">
  <div style="font-family:'Space Mono',monospace; font-size:10px; color:#d4ff00; letter-spacing:3px; margin-bottom:6px;">
    UNDERGROUND ELECTRONIC MUSIC
  </div>
  <div style="font-family:'Space Grotesk',sans-serif; font-size:42px; font-weight:700; color:#f0f0f0; letter-spacing:-1.5px; line-height:1;">
    RAVE <span style="color:#d4ff00;">PORTUGAL</span>
  </div>
  <div style="font-family:'Space Mono',monospace; font-size:11px; color:#444; margin-top:6px; letter-spacing:1px;">
    Resident Advisor + Songkick — Porto & Lisabon
  </div>
</div>
""", unsafe_allow_html=True)

# ─── Sidebar ─────────────────────────────────────────────────
with st.sidebar:
    st.markdown("""
    <div style="font-family:'Space Mono',monospace; font-size:11px; color:#d4ff00;
                letter-spacing:3px; padding: 1rem 0 1.5rem; border-bottom: 0.5px solid #1d1d1d; margin-bottom:1.5rem;">
        FILTRY
    </div>
    """, unsafe_allow_html=True)

    mesto = st.selectbox("Město", options=list(MESTA.keys()))

    c1, c2 = st.columns(2)
    with c1: datum_od = st.date_input("Od", value=date.today())
    with c2: datum_do = st.date_input("Do", value=date.today() + timedelta(days=30))

    zanry = st.multiselect(
        "Žánry",
        options=ZANRY_MOZNOSTI,
        default=["Techno", "Hard Techno", "Drum & Bass", "Psytrance", "Gabber", "Frenchcore"],
        placeholder="Vše (bez filtru)",
    )

    hledat = st.button("VYHLEDAT AKCE")

    st.markdown("""
    <div style="margin-top: 2rem; padding-top: 1rem; border-top: 0.5px solid #1d1d1d;">
      <div style="font-family:'Space Mono',monospace; font-size:9px; color:#333; letter-spacing:1px; line-height:2;">
        DATA<br>
        <span style="color:#d4ff00;">■</span> Resident Advisor<br>
        <span style="color:#00e5ff;">■</span> Songkick
      </div>
    </div>
    """, unsafe_allow_html=True)

# ─── Výsledky ────────────────────────────────────────────────
def render_event_card(r: dict):
    accent = "#d4ff00" if r["zdroj"] == "RA" else "#00e5ff"
    accent_bg = "#1a1e00" if r["zdroj"] == "RA" else "#001a1e"
    accent_border = "#3a4400" if r["zdroj"] == "RA" else "#003040"

    zanry_tags = ""
    for z in r["zanry"].split(", ")[:3]:
        if z.strip():
            zanry_tags += f'<span style="font-family:Space Mono,monospace;font-size:9px;padding:2px 7px;border-radius:3px;background:{accent_bg};color:{accent};border:0.5px solid {accent_border};margin-right:4px;">{z.strip().upper()}</span>'

    odkaz_html = f'<a href="{r["odkaz"]}" target="_blank" style="font-family:Space Mono,monospace;font-size:9px;color:#444;text-decoration:none;letter-spacing:1px;">DETAIL →</a>' if r["odkaz"] else ""

    st.markdown(f"""
    <div style="background:#111; border:0.5px solid #1d1d1d; border-radius:8px;
                padding:16px; margin-bottom:10px; position:relative;
                border-top: 2px solid {accent};">
      <div style="display:flex; justify-content:space-between; align-items:flex-start;">
        <div style="flex:1;">
          <div style="font-family:'Space Mono',monospace; font-size:9px; color:#555;
                      letter-spacing:2px; margin-bottom:5px;">
            {r["datum"]} {("— " + r["cas"]) if r["cas"] != "—" else ""}
          </div>
          <div style="font-family:'Space Grotesk',sans-serif; font-size:15px; font-weight:700;
                      color:#f0f0f0; line-height:1.2; margin-bottom:5px;">
            {r["nazev"]}
          </div>
          <div style="font-size:12px; color:#555; margin-bottom:10px;">
            {r["venue"]}
            {(" · " + r["interpreti"][:60] + ("…" if len(r["interpreti"]) > 60 else "")) if r["interpreti"] != "—" else ""}
          </div>
          <div style="display:flex; align-items:center; gap:8px; flex-wrap:wrap;">
            {zanry_tags}
            {odkaz_html}
          </div>
        </div>
        <div style="font-family:'Space Mono',monospace; font-size:9px;
                    color:{accent}; background:{accent_bg}; border:0.5px solid {accent_border};
                    padding:3px 8px; border-radius:3px; margin-left:12px; flex-shrink:0;">
          {r["zdroj"]}
        </div>
      </div>
    </div>
    """, unsafe_allow_html=True)


if hledat:
    if datum_od > datum_do:
        st.markdown('<div style="color:#ff3cac; font-family:Space Mono,monospace; font-size:11px;">⚠ Datum Od musí být dříve než Do</div>', unsafe_allow_html=True)
    else:
        cfg = MESTA[mesto]
        all_rows = []

        col_ra, col_sk = st.columns(2)

        with col_ra:
            with st.spinner("Resident Advisor…"):
                ra_raw = fetch_ra(cfg["ra_area_id"], datum_od, datum_do)
                ra_rows = parse_ra(ra_raw)
                all_rows.extend(ra_rows)
            st.markdown(f'<div style="font-family:Space Mono,monospace;font-size:9px;color:#d4ff00;letter-spacing:1px;">■ RA — {len(ra_rows)} akcí</div>', unsafe_allow_html=True)

        with col_sk:
            with st.spinner("Songkick…"):
                sk_rows = fetch_songkick(cfg["sk_city_slug"], datum_od, datum_do)
                all_rows.extend(sk_rows)
            st.markdown(f'<div style="font-family:Space Mono,monospace;font-size:9px;color:#00e5ff;letter-spacing:1px;">■ Songkick — {len(sk_rows)} akcí</div>', unsafe_allow_html=True)

        all_rows = deduplicate(all_rows)
        filtered = [r for r in all_rows if genre_matches(r, zanry)]
        filtered.sort(key=lambda x: x["datum"])

        st.markdown("<div style='margin: 1.5rem 0 1rem;'>", unsafe_allow_html=True)

        if not filtered:
            st.markdown('<div style="font-family:Space Mono,monospace;font-size:11px;color:#444;padding:2rem 0;">Žádné akce nenalezeny — zkus širší rozmezí nebo odeber filtr žánrů.</div>', unsafe_allow_html=True)
        else:
            st.markdown(f"""
            <div style="font-family:'Space Mono',monospace; font-size:10px; color:#555;
                        letter-spacing:2px; margin-bottom:1.5rem; padding-bottom:1rem;
                        border-bottom:0.5px solid #1d1d1d;">
                NALEZENO {len(filtered)} AKCÍ — {mesto.upper()} —
                {datum_od.strftime("%d.%m")} → {datum_do.strftime("%d.%m.%Y")}
            </div>
            """, unsafe_allow_html=True)

            for r in filtered:
                render_event_card(r)

            st.markdown("<div style='margin-top:1.5rem;'>", unsafe_allow_html=True)
            df = pd.DataFrame(filtered).rename(columns={
                "datum": "Datum", "cas": "Čas", "nazev": "Název akce",
                "venue": "Místo", "interpreti": "Interpreti",
                "zanry": "Žánr", "zdroj": "Zdroj", "odkaz": "Odkaz"
            })
            csv = df.to_csv(index=False).encode("utf-8")
            st.download_button("EXPORT CSV", csv,
                file_name=f"rave_{mesto.lower()}_{datum_od}.csv", mime="text/csv")
else:
    st.markdown("""
    <div style="padding: 4rem 0; text-align:center;">
      <div style="font-family:'Space Mono',monospace; font-size:48px; color:#1a1a1a; margin-bottom:1rem;">◈</div>
      <div style="font-family:'Space Mono',monospace; font-size:11px; color:#333; letter-spacing:2px; line-height:2.5;">
        VYBER MĚSTO A DATUM<br>
        NASTAV ŽÁNRY<br>
        KLIKNI VYHLEDAT
      </div>
    </div>
    """, unsafe_allow_html=True)
