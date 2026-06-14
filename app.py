import streamlit as st
import requests
from datetime import date, timedelta
import pandas as pd
from bs4 import BeautifulSoup
import json
import re

# ═══════════════════════════════════════════════════════════════
#  KONFIGURACE
# ═══════════════════════════════════════════════════════════════

MESTA = {
    "Porto":   {
        "ra_area_id": 364,
        "sk_metro_id": 28758,     # Songkick metro ID pro Porto
        "sk_city_slug": "porto",
    },
    "Lisabon": {
        "ra_area_id": 53,
        "sk_metro_id": 28863,     # Songkick metro ID pro Lisabon
        "sk_city_slug": "lisbon",
    },
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
#  FUNKCE — Resident Advisor
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
            "Datum":        datum,
            "Čas":          cas,
            "Název akce":   e.get("title", "—"),
            "Místo / Klub": venue.get("name", "—"),
            "Interpreti":   ", ".join(a["name"] for a in e.get("artists", [])) or "—",
            "Žánr":         ", ".join(genres) if genres else "—",
            "Zdroj":        "RA",
            "Odkaz":        f"https://ra.co{e['contentUrl']}" if e.get("contentUrl") else "",
        })
    return rows


# ═══════════════════════════════════════════════════════════════
#  FUNKCE — Songkick (scraping JSON-LD)
# ═══════════════════════════════════════════════════════════════

def fetch_songkick(city_slug: str, date_from: date, date_to: date) -> list[dict]:
    """Načte akce ze Songkick pro dané město a datumové rozmezí."""
    rows = []
    page = 1
    while True:
        url = (
            f"https://www.songkick.com/concerts?utf8=✓"
            f"&filters[minDate]={date_from.strftime('%Y-%m-%d')}"
            f"&filters[maxDate]={date_to.strftime('%Y-%m-%d')}"
            f"&filters[location]=sk:{_sk_metro(city_slug)}"
            f"&page={page}"
        )
        try:
            r = requests.get(url, headers=SK_HEADERS, timeout=15)
            if r.status_code != 200:
                break
            soup = BeautifulSoup(r.text, "html.parser")

            # Načti JSON-LD data
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
                            "Datum":        datum,
                            "Čas":          cas,
                            "Název akce":   item.get("name", "—"),
                            "Místo / Klub": venue_name,
                            "Interpreti":   interpreti,
                            "Žánr":         "—",
                            "Zdroj":        "Songkick",
                            "Odkaz":        item.get("url", ""),
                        })
                except Exception:
                    continue

            if not found:
                break
            # Zkontroluj jestli existuje další stránka
            next_btn = soup.select_one("a[rel='next']")
            if not next_btn:
                break
            page += 1
            if page > 5:  # max 5 stránek
                break
        except Exception:
            break
    return rows


def _sk_metro(city_slug: str) -> int:
    return MESTA.get(
        next((k for k, v in MESTA.items() if v["sk_city_slug"] == city_slug), "Porto"),
        MESTA["Porto"]
    )["sk_metro_id"]


# ═══════════════════════════════════════════════════════════════
#  FILTROVÁNÍ ŽÁNRŮ
# ═══════════════════════════════════════════════════════════════

def genre_matches(zanr_str: str, interpreti: str, nazev: str, selected: list[str]) -> bool:
    if not selected:
        return True
    text = f"{zanr_str} {interpreti} {nazev}".lower()
    for s in selected:
        if s.lower() in text:
            return True
    return False


def deduplicate(rows: list[dict]) -> list[dict]:
    """Odstraní duplicity (stejný název akce a datum)."""
    seen = set()
    result = []
    for r in rows:
        key = (r["Datum"], r["Název akce"].lower()[:30])
        if key not in seen:
            seen.add(key)
            result.append(r)
    return result


# ═══════════════════════════════════════════════════════════════
#  UI
# ═══════════════════════════════════════════════════════════════

st.set_page_config(page_title="🎛️ Rave Portugal", page_icon="🎛️", layout="wide")
st.markdown("""
<style>
    .rave-title { font-family:'Courier New',monospace; font-size:2.4rem; font-weight:700; letter-spacing:2px; color:#e0ff4f; margin-bottom:0; }
    .rave-sub   { font-size:0.95rem; color:#888; margin-top:2px; margin-bottom:1.5rem; font-family:'Courier New',monospace; }
    div.stButton > button { background:#e0ff4f; color:#111; font-weight:700; font-family:'Courier New',monospace; letter-spacing:1px; border:none; border-radius:6px; padding:0.55rem 2rem; width:100%; margin-top:0.5rem; }
    div.stButton > button:hover { background:#c8e600; }
    section[data-testid="stSidebar"] { background:#111; }
    section[data-testid="stSidebar"] label { color:#ccc !important; font-family:'Courier New',monospace; }
</style>
""", unsafe_allow_html=True)

st.markdown('<p class="rave-title">🎛️ RAVE PORTUGAL</p>', unsafe_allow_html=True)
st.markdown('<p class="rave-sub">Vyhledávač rave akcí v Portugalsku — data z Resident Advisor + Songkick</p>', unsafe_allow_html=True)

with st.sidebar:
    st.markdown("### 🔍 Filtry")
    mesto = st.selectbox("Město", options=list(MESTA.keys()))
    st.markdown("**Datum**")
    c1, c2 = st.columns(2)
    with c1: datum_od = st.date_input("Od", value=date.today())
    with c2: datum_do = st.date_input("Do", value=date.today() + timedelta(days=30))
    zanry = st.multiselect(
        "Žánry (nechej prázdné = vše)", options=ZANRY_MOZNOSTI,
        default=["Techno", "Hard Techno", "Drum & Bass", "Psytrance", "Gabber", "Frenchcore"],
    )
    hledat = st.button("🔎  Vyhledat akce")
    st.markdown("---")
    st.caption("Data: [Resident Advisor](https://ra.co) + [Songkick](https://songkick.com)")

if hledat:
    if datum_od > datum_do:
        st.warning("⚠️ Datum 'Od' musí být dříve než datum 'Do'.")
    else:
        cfg = MESTA[mesto]
        all_rows = []

        col1, col2 = st.columns(2)

        with col1:
            with st.spinner("Načítám z Resident Advisor…"):
                ra_raw = fetch_ra(cfg["ra_area_id"], datum_od, datum_do)
                ra_rows = parse_ra(ra_raw)
                st.caption(f"RA: {len(ra_rows)} akcí")
                all_rows.extend(ra_rows)

        with col2:
            with st.spinner("Načítám ze Songkick…"):
                sk_rows = fetch_songkick(cfg["sk_city_slug"], datum_od, datum_do)
                st.caption(f"Songkick: {len(sk_rows)} akcí")
                all_rows.extend(sk_rows)

        # Deduplikace a filtr žánrů
        all_rows = deduplicate(all_rows)
        filtered = [
            r for r in all_rows
            if genre_matches(r["Žánr"], r["Interpreti"], r["Název akce"], zanry)
        ]

        # Seřadit podle data
        filtered.sort(key=lambda x: x["Datum"])

        if not filtered:
            st.info("Žádné akce nebyly nalezeny. Zkus širší rozmezí nebo odeber filtr žánrů.")
        else:
            st.success(f"✅ Celkem **{len(filtered)}** akcí v {mesto} ({datum_od} – {datum_do})")
            df = pd.DataFrame(filtered)
            st.dataframe(df.drop(columns=["Odkaz"]), use_container_width=True, hide_index=True)

            with st.expander("🔗 Přímé odkazy na akce"):
                for r in filtered:
                    if r["Odkaz"]:
                        st.markdown(f"- [{r['Název akce']} – {r['Datum']}]({r['Odkaz']}) `{r['Zdroj']}`")

            csv = df.to_csv(index=False).encode("utf-8")
            st.download_button("⬇️ Stáhnout CSV", csv,
                file_name=f"rave_{mesto.lower()}_{datum_od}.csv", mime="text/csv")
else:
    st.markdown("""
    <div style="text-align:center; padding:3rem 0; color:#555;">
        <p style="font-size:3rem;">🎶</p>
        <p style="font-family:'Courier New',monospace;">Vyber město, datum a žánry v levém panelu,<br>pak klikni na <strong>Vyhledat akce</strong>.</p>
    </div>
    """, unsafe_allow_html=True)
