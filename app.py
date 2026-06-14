import streamlit as st
import requests
from datetime import date, timedelta
import pandas as pd
from bs4 import BeautifulSoup
import json
import hashlib

# ═══════════════════════════════════════════════════════════════
#  CONFIG — přidej libovolné město, ID se zjistí automaticky
# ═══════════════════════════════════════════════════════════════

CITIES_LIST = [
    "Porto", "Lisbon", "Prague", "Brno",
    "Berlin", "Amsterdam", "Barcelona", "Madrid",
    "London", "Paris", "Vienna", "Budapest",
    "Warsaw", "Bratislava", "Zurich", "Brussels",
    "Milan", "Rome", "Athens", "Istanbul",
    "New York", "Los Angeles", "Chicago", "Miami",
    "São Paulo", "Buenos Aires", "Bogotá",
    "Tokyo", "Seoul", "Melbourne", "Sydney",
]

GENRES = [
    "Techno", "Acid Techno", "Hard Techno", "Industrial Techno",
    "Drum & Bass", "Jump Up", "Liquid Funk", "Neurofunk",
    "Trance", "Psytrance", "Uplifting Trance",
    "House", "Acid House", "Deep House", "Tech House",
    "Hardcore", "Gabber", "Frenchcore",
    "Electronic", "Electronica", "Ambient", "Industrial",
    "Breakbeat", "Jungle", "Minimal", "EBM", "Noise",
]

# Ticketmaster API klíč — zaregistruj se ZDARMA na developer.ticketmaster.com
# Po registraci vlož svůj klíč sem:
TM_API_KEY = "S5YU9lCzkJNAcBFf8k8VGCMYCI2VUFew"

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

RA_AREAS_QUERY = """
query FindArea($search: String!) {
  areas(searchTerm: $search, limit: 10) {
    id name urlName
    country { name isoCode }
  }
}
"""

# ═══════════════════════════════════════════════════════════════
#  SESSION STATE
# ═══════════════════════════════════════════════════════════════

if "favorites" not in st.session_state:
    st.session_state.favorites = {}
if "results" not in st.session_state:
    st.session_state.results = []
if "city_cache" not in st.session_state:
    # Cache pro zjištěné IDs: {"Porto": {"ra_id": 364, "sk_id": 28758}}
    st.session_state.city_cache = {}


def event_id(r: dict) -> str:
    return hashlib.md5(f"{r['date']}_{r['title']}".encode()).hexdigest()[:10]

def is_favorite(r: dict) -> bool:
    return event_id(r) in st.session_state.favorites

def add_favorite(eid: str, r: dict):
    st.session_state.favorites[eid] = r

def remove_favorite(eid: str):
    if eid in st.session_state.favorites:
        del st.session_state.favorites[eid]


# ═══════════════════════════════════════════════════════════════
#  AUTO-LOOKUP FUNKCÍ PRO ID MĚST
# ═══════════════════════════════════════════════════════════════

def lookup_ra_area_id(city_name: str) -> int | None:
    """Zjistí RA area ID pro dané město přes GraphQL API."""
    try:
        r = requests.post(
            RA_URL,
            headers=RA_HEADERS,
            json={"query": RA_AREAS_QUERY, "variables": {"search": city_name.lower()}},
            timeout=10,
        )
        r.raise_for_status()
        areas = r.json().get("data", {}).get("areas", [])
        if not areas:
            return None
        # Preferuj přesnou shodu názvu
        for a in areas:
            if a.get("name", "").lower() == city_name.lower():
                return int(a["id"])
        # Jinak první výsledek
        return int(areas[0]["id"])
    except Exception:
        return None


def lookup_sk_metro_id(city_name: str) -> int | None:
    """Zjistí Songkick metro area ID přes jejich location search API."""
    try:
        url = f"https://api.songkick.com/api/3.0/search/locations.json?query={city_name}&apikey=demo"
        # Songkick location search je dostupný i přes web search endpoint
        # Alternativa: scraping jejich stránky
        r = requests.get(
            f"https://www.songkick.com/search?utf8=%E2%9C%93&type=locations&query={city_name}",
            headers=SK_HEADERS,
            timeout=10,
        )
        soup = BeautifulSoup(r.text, "html.parser")
        # Hledej odkaz na metro area
        for a in soup.select("a[href*='/metro_areas/']"):
            href = a.get("href", "")
            parts = href.split("/metro_areas/")
            if len(parts) == 2:
                mid = parts[1].split("-")[0]
                if mid.isdigit():
                    return int(mid)
        return None
    except Exception:
        return None


def get_city_ids(city_name: str) -> dict:
    """
    Vrátí {ra_id, sk_id} pro město.
    Výsledky cachuje v session_state aby se API nevolalo opakovaně.
    """
    cache = st.session_state.city_cache
    if city_name in cache:
        return cache[city_name]

    ra_id = lookup_ra_area_id(city_name)
    sk_id = lookup_sk_metro_id(city_name)

    result = {"ra_id": ra_id, "sk_id": sk_id}
    cache[city_name] = result
    return result


# ═══════════════════════════════════════════════════════════════
#  DATA FUNCTIONS
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
        d = (e.get("date") or "")[:10]
        cas_raw = e.get("startTime", "")
        time = cas_raw.split("T")[1][:5] if cas_raw and "T" in cas_raw else "—"
        venue = e.get("venue") or {}
        rows.append({
            "date":    d,
            "time":    time,
            "title":   e.get("title", "—"),
            "venue":   venue.get("name", "—"),
            "artists": ", ".join(a["name"] for a in e.get("artists", [])) or "—",
            "genres":  ", ".join(genres) if genres else "",
            "source":  "RA",
            "url":     f"https://ra.co{e['contentUrl']}" if e.get("contentUrl") else "",
        })
    return rows


def fetch_songkick(metro_id: int, date_from: date, date_to: date) -> list[dict]:
    if not metro_id:
        return []
    rows = []
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
                        d = start[:10] if start else "—"
                        t = start[11:16] if len(start) > 10 else "—"
                        ev_date = date.fromisoformat(d) if d != "—" else None
                        if ev_date and not (date_from <= ev_date <= date_to):
                            continue
                        location = item.get("location", {})
                        venue_name = location.get("name", "—") if isinstance(location, dict) else "—"
                        performers = item.get("performer", [])
                        if isinstance(performers, dict):
                            performers = [performers]
                        artists = ", ".join(p.get("name", "") for p in performers) or "—"
                        rows.append({
                            "date":    d,
                            "time":    t,
                            "title":   item.get("name", "—"),
                            "venue":   venue_name,
                            "artists": artists,
                            "genres":  "",
                            "source":  "Songkick",
                            "url":     item.get("url", ""),
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


def fetch_bandsintown(city_name: str, date_from: date, date_to: date) -> list[dict]:
    """Bandsintown public REST API — events by city."""
    rows = []
    try:
        url = (
            f"https://rest.bandsintown.com/v4/events/search"
            f"?app_id=test&location={requests.utils.quote(city_name)}"
            f"&date={date_from.strftime('%Y-%m-%d')},{date_to.strftime('%Y-%m-%d')}"
            f"&per_page=50"
        )
        r = requests.get(url, headers=SK_HEADERS, timeout=15)
        if r.status_code != 200:
            return []
        data = r.json()
        events = data if isinstance(data, list) else data.get("data", data.get("events", []))
        for e in events:
            if not isinstance(e, dict):
                continue
            dt = e.get("datetime", e.get("starts_at", ""))
            d = dt[:10] if dt else "—"
            t = dt[11:16] if len(dt) > 10 else "—"
            venue = e.get("venue", {}) or {}
            lineup = e.get("lineup", e.get("artists", []))
            if isinstance(lineup, list):
                artists = ", ".join(
                    (a.get("name", "") if isinstance(a, dict) else str(a))
                    for a in lineup
                ) or "—"
            else:
                artists = "—"
            rows.append({
                "date":    d,
                "time":    t,
                "title":   e.get("title") or e.get("name") or artists or "—",
                "venue":   venue.get("name", "—") if isinstance(venue, dict) else "—",
                "artists": artists,
                "genres":  "",
                "source":  "Bandsintown",
                "url":     e.get("url", ""),
            })
    except Exception:
        pass
    return rows


def _parse_jsonld_events(soup, date_from: date, date_to: date, source: str) -> list[dict]:
    """Sdílená logika pro parsování JSON-LD eventů (Songkick, Dice)."""
    rows = []
    for sc in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(sc.string or "")
            items = data if isinstance(data, list) else [data]
            for item in items:
                if item.get("@type") not in ("MusicEvent", "Event"):
                    continue
                start = item.get("startDate", "")
                d = start[:10] if start else "—"
                t = start[11:16] if len(start) > 10 else "—"
                ev_date = date.fromisoformat(d) if d != "—" else None
                if ev_date and not (date_from <= ev_date <= date_to):
                    continue
                location = item.get("location", {})
                venue_name = location.get("name", "—") if isinstance(location, dict) else "—"
                performers = item.get("performer", [])
                if isinstance(performers, dict):
                    performers = [performers]
                artists = ", ".join(p.get("name", "") for p in performers) or "—"
                rows.append({
                    "date":    d,
                    "time":    t,
                    "title":   item.get("name", "—"),
                    "venue":   venue_name,
                    "artists": artists,
                    "genres":  "",
                    "source":  source,
                    "url":     item.get("url", ""),
                })
        except Exception:
            continue
    return rows


def fetch_dice(city_name: str, date_from: date, date_to: date) -> list[dict]:
    """Scrape Dice.fm events pro dané město přes JSON-LD."""
    rows = []
    slug = city_name.lower().replace(" ", "-")
    # Dice používá URL formát /browse/{city_slug}
    urls_to_try = [
        f"https://dice.fm/browse/{slug}",
        f"https://dice.fm/venue/{slug}",
        f"https://dice.fm/search?q={requests.utils.quote(city_name)}&type=events",
    ]
    for url in urls_to_try:
        try:
            r = requests.get(url, headers=SK_HEADERS, timeout=15)
            if r.status_code != 200:
                continue
            soup = BeautifulSoup(r.text, "html.parser")
            found = _parse_jsonld_events(soup, date_from, date_to, "Dice")
            rows.extend(found)
            if found:
                break
        except Exception:
            continue
    return rows



def fetch_shotgun(city_name: str, date_from: date, date_to: date) -> list[dict]:
    """Scrape Shotgun.live events — specializovaná elektronická hudba, underground."""
    rows = []
    slug = city_name.lower().replace(" ", "-")
    urls_to_try = [
        f"https://shotgun.live/en/cities/{slug}",
        f"https://shotgun.live/en/cities/{slug}/techno",
        f"https://shotgun.live/en/cities/{slug}/electronic",
    ]
    for url in urls_to_try:
        try:
            r = requests.get(url, headers=SK_HEADERS, timeout=15)
            if r.status_code != 200:
                continue
            soup = BeautifulSoup(r.text, "html.parser")
            found = _parse_jsonld_events(soup, date_from, date_to, "Shotgun")
            rows.extend(found)
        except Exception:
            continue
    return rows


def fetch_ticketmaster(city_name: str, date_from: date, date_to: date, api_key: str) -> list[dict]:
    """Ticketmaster Discovery API — velké akce a arény. Vyžaduje API klíč."""
    if not api_key or api_key == "YOUR_TM_KEY":
        return []
    rows = []
    try:
        url = (
            f"https://app.ticketmaster.com/discovery/v2/events.json"
            f"?apikey={api_key}"
            f"&city={requests.utils.quote(city_name)}"
            f"&classificationName=music"
            f"&startDateTime={date_from.strftime('%Y-%m-%d')}T00:00:00Z"
            f"&endDateTime={date_to.strftime('%Y-%m-%d')}T23:59:59Z"
            f"&size=50"
            f"&sort=date,asc"
        )
        r = requests.get(url, headers=SK_HEADERS, timeout=15)
        r.raise_for_status()
        data = r.json()
        events = (data.get("_embedded") or {}).get("events", [])
        for e in events:
            dates = e.get("dates", {}).get("start", {})
            d = dates.get("localDate", "—")
            t = dates.get("localTime", "—")[:5] if dates.get("localTime") else "—"
            venues = (e.get("_embedded") or {}).get("venues", [{}])
            venue_name = venues[0].get("name", "—") if venues else "—"
            attractions = (e.get("_embedded") or {}).get("attractions", [])
            artists = ", ".join(a.get("name", "") for a in attractions) or "—"
            genres_list = []
            for cls in e.get("classifications", []):
                if cls.get("genre", {}).get("name") not in (None, "Undefined"):
                    genres_list.append(cls["genre"]["name"])
                if cls.get("subGenre", {}).get("name") not in (None, "Undefined"):
                    genres_list.append(cls["subGenre"]["name"])
            rows.append({
                "date":    d,
                "time":    t,
                "title":   e.get("name", "—"),
                "venue":   venue_name,
                "artists": artists,
                "genres":  ", ".join(set(genres_list)),
                "source":  "Ticketmaster",
                "url":     e.get("url", ""),
            })
    except Exception:
        pass
    return rows


def genre_matches(row: dict, selected: list[str]) -> bool:
    if not selected:
        return True
    text = f"{row['genres']} {row['artists']} {row['title']}".lower()
    return any(s.lower() in text for s in selected)



def deduplicate(rows: list[dict]) -> list[dict]:
    seen = set()
    result = []
    for r in rows:
        key = (r["date"], r["title"].lower()[:40])
        if key not in seen:
            seen.add(key)
            result.append(r)
    return result


# ═══════════════════════════════════════════════════════════════
#  PAGE CONFIG & CSS
# ═══════════════════════════════════════════════════════════════

st.set_page_config(page_title="Rave Portugal", page_icon="🎛️", layout="wide")

st.markdown("""
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;700&family=Space+Mono:wght@400;700&display=swap" rel="stylesheet">
<style>
html, body, [class*="css"] { font-family: 'Space Grotesk', sans-serif !important; }
.stApp { background: #0a0a0a !important; }
.stApp > header { background: transparent !important; }
section[data-testid="stSidebar"] { background: #0f0f0f !important; border-right: 0.5px solid #1d1d1d !important; }
section[data-testid="stSidebar"] label {
    color: #555 !important; font-family: 'Space Mono', monospace !important;
    font-size: 10px !important; letter-spacing: 2px !important; text-transform: uppercase !important;
}
section[data-testid="stSidebar"] .stSelectbox > div > div,
section[data-testid="stSidebar"] .stMultiSelect > div > div,
section[data-testid="stSidebar"] .stDateInput > div > div > input {
    background: #151515 !important; border: 0.5px solid #2a2a2a !important;
    color: #ccc !important; border-radius: 6px !important;
}
section[data-testid="stSidebar"] .stMultiSelect span[data-baseweb="tag"] {
    background: #1a1e00 !important; color: #d4ff00 !important;
    border: 0.5px solid #3a4400 !important; border-radius: 4px !important;
    font-family: 'Space Mono', monospace !important; font-size: 10px !important;
}
div.stButton > button {
    background: #1a1a1a !important; color: #888 !important;
    font-family: 'Space Mono', monospace !important; font-size: 10px !important;
    letter-spacing: 1px !important; border: 0.5px solid #2a2a2a !important;
    border-radius: 6px !important; padding: 0.3rem 1rem !important;
    width: 100% !important; margin-top: 2px !important;
}
div.stButton > button:hover { border-color: #ff3cac !important; color: #ff3cac !important; }
.search-btn > div > button {
    background: #d4ff00 !important; color: #0a0a0a !important;
    font-weight: 700 !important; font-size: 11px !important;
    letter-spacing: 2px !important; border: none !important;
}
.search-btn > div > button:hover { background: #c0e800 !important; color: #0a0a0a !important; }
.block-container { padding-top: 2rem !important; }
div.stDownloadButton > button {
    background: transparent !important; border: 0.5px solid #2a2a2a !important;
    color: #555 !important; font-family: 'Space Mono', monospace !important;
    font-size: 10px !important; letter-spacing: 1px !important; border-radius: 6px !important;
}
div.stDownloadButton > button:hover { border-color: #d4ff00 !important; color: #d4ff00 !important; }
.stTabs [data-baseweb="tab-list"] { background: transparent !important; border-bottom: 0.5px solid #1d1d1d !important; }
.stTabs [data-baseweb="tab"] { background: transparent !important; color: #444 !important; font-family: 'Space Mono', monospace !important; font-size: 11px !important; letter-spacing: 1px !important; }
.stTabs [aria-selected="true"] { color: #d4ff00 !important; border-bottom: 2px solid #d4ff00 !important; }
</style>
""", unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════════
#  HERO
# ═══════════════════════════════════════════════════════════════

fav_count = len(st.session_state.favorites)
st.markdown(f"""
<div style="margin-bottom:2rem;display:flex;justify-content:space-between;align-items:flex-end;">
  <div>
    <div style="font-family:'Space Mono',monospace;font-size:10px;color:#d4ff00;letter-spacing:3px;margin-bottom:6px;">
      UNDERGROUND ELECTRONIC MUSIC
    </div>
    <div style="font-family:'Space Grotesk',sans-serif;font-size:42px;font-weight:700;color:#f0f0f0;letter-spacing:-1.5px;line-height:1;">
      RAVE <span style="color:#d4ff00;">FINDER</span>
    </div>
    <div style="font-family:'Space Mono',monospace;font-size:11px;color:#444;margin-top:6px;letter-spacing:1px;">
      Resident Advisor + Songkick — auto city lookup
    </div>
  </div>
  <div style="font-family:'Space Mono',monospace;font-size:10px;color:#555;text-align:right;">
    <span style="color:#ff3cac;font-size:20px;">♥</span><br>
    {fav_count} saved
  </div>
</div>
""", unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════════
#  SIDEBAR
# ═══════════════════════════════════════════════════════════════

with st.sidebar:
    st.markdown("""
    <div style="font-family:'Space Mono',monospace;font-size:11px;color:#d4ff00;
                letter-spacing:3px;padding:1rem 0 1.5rem;border-bottom:0.5px solid #1d1d1d;margin-bottom:1.5rem;">
        FILTERS
    </div>
    """, unsafe_allow_html=True)

    cities_sel = st.multiselect(
        "Cities",
        options=CITIES_LIST,
        default=["Porto"],
        placeholder="Select one or more cities…",
    )

    c1, c2 = st.columns(2)
    with c1: date_from = st.date_input("From", value=date.today())
    with c2: date_to   = st.date_input("To",   value=date.today() + timedelta(days=30))

    genres_sel = st.multiselect(
        "Genres", options=GENRES,
        default=["Techno", "Hard Techno", "Drum & Bass", "Psytrance", "Gabber", "Frenchcore"],
        placeholder="All genres",
    )


    st.markdown('<div class="search-btn">', unsafe_allow_html=True)
    search = st.button("SEARCH EVENTS")
    st.markdown('</div>', unsafe_allow_html=True)

    # Zobraz cache — jaká města a ID jsou uložena
    if st.session_state.city_cache:
        st.markdown("""
        <div style="margin-top:1.5rem;padding-top:1rem;border-top:0.5px solid #1d1d1d;">
          <div style="font-family:'Space Mono',monospace;font-size:9px;color:#333;letter-spacing:1px;margin-bottom:8px;">CACHED CITY IDs</div>
        """, unsafe_allow_html=True)
        for cname, ids in st.session_state.city_cache.items():
            ra  = ids.get("ra_id") or "—"
            sk  = ids.get("sk_id") or "—"
            st.markdown(f"""
            <div style="font-family:'Space Mono',monospace;font-size:9px;color:#444;line-height:2;">
              <span style="color:#888;">{cname}</span><br>
              <span style="color:#d4ff00;">■</span> RA: {ra} &nbsp;
              <span style="color:#00e5ff;">■</span> SK: {sk}
            </div>
            """, unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("""
    <div style="margin-top:1.5rem;padding-top:1rem;border-top:0.5px solid #1d1d1d;">
      <div style="font-family:'Space Mono',monospace;font-size:9px;color:#333;letter-spacing:1px;line-height:2.5;">
        DATA SOURCES<br>
        <span style="color:#d4ff00;">■</span> Resident Advisor<br>
        <span style="color:#00e5ff;">■</span> Songkick<br>
        <span style="color:#ff7f00;">■</span> Bandsintown<br>
        <span style="color:#bf5fff;">■</span> Dice.fm<br>
        <span style="color:#ff2d55;">■</span> Shotgun.live<br>
        <span style="color:#026cdf;">■</span> Ticketmaster*
      </div>
    </div>
    """, unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════
#  EVENT CARD
# ═══════════════════════════════════════════════════════════════

def esc(s: str) -> str:
    """Escapuje HTML speciální znaky aby text nerozhodil markup."""
    return (str(s)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;"))


def render_card(r: dict, key_prefix: str):
    eid     = event_id(r)
    fav     = is_favorite(r)
    source_colors = {
        "RA":           ("#d4ff00", "#1a1e00", "#3a4400"),
        "Songkick":     ("#00e5ff", "#001a1e", "#003040"),
        "Bandsintown":  ("#ff7f00", "#1e0f00", "#3a2000"),
        "Dice":         ("#bf5fff", "#150020", "#2e0050"),
        "Shotgun":      ("#ff2d55", "#200008", "#4a0015"),
        "Ticketmaster": ("#026cdf", "#001030", "#002060"),
    }
    accent, acc_bg, acc_brd = source_colors.get(r["source"], ("#888", "#1a1a1a", "#333"))
    heart_c = "#ff3cac" if fav else "#2a2a2a"

    # Escapované hodnoty
    title   = esc(r["title"])
    venue   = esc(r["venue"])
    source  = esc(r["source"])
    city    = esc(r.get("city", ""))
    date_s  = esc(r["date"])
    time_s  = esc(r["time"]) if r["time"] != "—" else ""
    url     = r["url"]

    tags_html = ""
    for g in r["genres"].split(", ")[:3]:
        if g.strip():
            tags_html += (
                f'<span style="font-family:Space Mono,monospace;font-size:9px;'
                f'padding:2px 7px;border-radius:3px;background:{acc_bg};'
                f'color:{accent};border:0.5px solid {acc_brd};margin-right:4px;">'
                f'{esc(g.strip()).upper()}</span>'
            )

    link_html = ""
    if url:
        link_html = (
            f'<a href="{esc(url)}" target="_blank" style="font-family:Space Mono,monospace;'
            f'font-size:9px;color:#444;text-decoration:none;letter-spacing:1px;margin-left:6px;">'
            f'DETAILS →</a>'
        )

    artists_raw = r["artists"] if r["artists"] != "—" else ""
    artists_str = ""
    if artists_raw:
        short = esc(artists_raw[:55]) + ("…" if len(artists_raw) > 55 else "")
        artists_str = f"  ·  {short}"

    time_part  = f" — {time_s}" if time_s else ""
    city_part  = f" · {city.upper()}" if city else ""

    html = f"""<div style="background:#111;border:0.5px solid #1d1d1d;border-radius:8px;padding:16px 16px 10px;margin-bottom:2px;border-top:2px solid {accent};">
  <div style="display:flex;justify-content:space-between;align-items:flex-start;">
    <div style="flex:1;min-width:0;">
      <div style="font-family:Space Mono,monospace;font-size:9px;color:#555;letter-spacing:2px;margin-bottom:5px;">{date_s}{time_part}{city_part}</div>
      <div style="font-family:Space Grotesk,sans-serif;font-size:15px;font-weight:700;color:#f0f0f0;line-height:1.2;margin-bottom:5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">{title}</div>
      <div style="font-size:12px;color:#555;margin-bottom:10px;">{venue}{artists_str}</div>
      <div style="display:flex;align-items:center;flex-wrap:wrap;gap:4px;">{tags_html}{link_html}</div>
    </div>
    <div style="display:flex;flex-direction:column;align-items:flex-end;gap:8px;margin-left:12px;flex-shrink:0;">
      <span style="font-family:Space Mono,monospace;font-size:9px;color:{accent};background:{acc_bg};border:0.5px solid {acc_brd};padding:3px 8px;border-radius:3px;">{source}</span>
      <span style="font-size:20px;color:{heart_c};line-height:1;">&#9829;</span>
    </div>
  </div>
</div>"""
    st.markdown(html, unsafe_allow_html=True)

    btn_label = "♥  Remove from favorites" if fav else "♡  Save to favorites"

    def _toggle(eid=eid, r=r, fav=fav):
        if fav:
            remove_favorite(eid)
        else:
            add_favorite(eid, r)

    st.button(btn_label, key=f"{key_prefix}_{eid}", on_click=_toggle)
    st.markdown("<div style='margin-bottom:12px;'></div>", unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════
#  SEARCH
# ═══════════════════════════════════════════════════════════════

if search:
    if not cities_sel:
        st.warning("Please select at least one city.")
    elif date_from > date_to:
        st.error("'From' date must be before 'To' date.")
    else:
        all_rows = []
        for city in cities_sel:
            with st.spinner(f"Looking up {city}…"):
                ids = get_city_ids(city)
            ra_id = ids.get("ra_id")
            sk_id = ids.get("sk_id")
            if not ra_id and not sk_id:
                st.warning(f"Could not find '{city}' — skipping.")
                continue
            col_ra, col_sk, col_bit, col_dice = st.columns(4)
            with col_ra:
                if ra_id:
                    with st.spinner(f"RA…"):
                        ra_rows = parse_ra(fetch_ra(ra_id, date_from, date_to))
                        for r in ra_rows: r["city"] = city
                        all_rows.extend(ra_rows)
                    st.markdown(f'<div style="font-family:Space Mono,monospace;font-size:9px;color:#d4ff00;letter-spacing:1px;">■ RA — {len(ra_rows)}</div>', unsafe_allow_html=True)
            with col_sk:
                if sk_id:
                    with st.spinner(f"Songkick…"):
                        sk_rows = fetch_songkick(sk_id, date_from, date_to)
                        for r in sk_rows: r["city"] = city
                        all_rows.extend(sk_rows)
                    st.markdown(f'<div style="font-family:Space Mono,monospace;font-size:9px;color:#00e5ff;letter-spacing:1px;">■ Songkick — {len(sk_rows)}</div>', unsafe_allow_html=True)
            with col_bit:
                with st.spinner(f"Bandsintown…"):
                    bit_rows = fetch_bandsintown(city, date_from, date_to)
                    for r in bit_rows: r["city"] = city
                    all_rows.extend(bit_rows)
                st.markdown(f'<div style="font-family:Space Mono,monospace;font-size:9px;color:#ff7f00;letter-spacing:1px;">■ Bandsintown — {len(bit_rows)}</div>', unsafe_allow_html=True)
            with col_dice:
                with st.spinner(f"Dice…"):
                    dice_rows = fetch_dice(city, date_from, date_to)
                    for r in dice_rows: r["city"] = city
                    all_rows.extend(dice_rows)
                st.markdown(f'<div style="font-family:Space Mono,monospace;font-size:9px;color:#bf5fff;letter-spacing:1px;">■ Dice — {len(dice_rows)}</div>', unsafe_allow_html=True)
            col_sg, col_tm = st.columns(2)
            with col_sg:
                with st.spinner(f"Shotgun…"):
                    sg_rows = fetch_shotgun(city, date_from, date_to)
                    for r in sg_rows: r["city"] = city
                    all_rows.extend(sg_rows)
                st.markdown(f'<div style="font-family:Space Mono,monospace;font-size:9px;color:#ff2d55;letter-spacing:1px;">■ Shotgun — {len(sg_rows)}</div>', unsafe_allow_html=True)
            with col_tm:
                with st.spinner(f"Ticketmaster…"):
                    tm_rows = fetch_ticketmaster(city, date_from, date_to, TM_API_KEY)
                    for r in tm_rows: r["city"] = city
                    all_rows.extend(tm_rows)
                label = f"{len(tm_rows)}" if TM_API_KEY != "YOUR_TM_KEY" else "no key"
                st.markdown(f'<div style="font-family:Space Mono,monospace;font-size:9px;color:#026cdf;letter-spacing:1px;">■ Ticketmaster — {label}</div>', unsafe_allow_html=True)
        all_rows = deduplicate(all_rows)
        filtered = [r for r in all_rows if genre_matches(r, genres_sel)]
        filtered.sort(key=lambda x: (x["date"], x.get("city", "")))
        st.session_state.results = filtered


# ═══════════════════════════════════════════════════════════════
#  TABS
# ═══════════════════════════════════════════════════════════════

fav_count = len(st.session_state.favorites)
tab_search, tab_fav = st.tabs([
    "🔎  Search events",
    f"♥  Saved ({fav_count})",
])

with tab_search:
    results = st.session_state.results
    if not results:
        st.markdown("""
        <div style="padding:4rem 0;text-align:center;">
          <div style="font-family:'Space Mono',monospace;font-size:48px;color:#1a1a1a;margin-bottom:1rem;">◈</div>
          <div style="font-family:'Space Mono',monospace;font-size:11px;color:#333;letter-spacing:2px;line-height:2.5;">
            SELECT CITY AND DATE<br>SET GENRES<br>CLICK SEARCH
          </div>
        </div>
        """, unsafe_allow_html=True)
    else:
        st.markdown(f"""
        <div style="font-family:'Space Mono',monospace;font-size:10px;color:#555;letter-spacing:2px;
                    margin:1rem 0;padding-bottom:1rem;border-bottom:0.5px solid #1d1d1d;">
            {len(results)} EVENTS FOUND — {date_from.strftime("%d %b")} → {date_to.strftime("%d %b %Y")}
        </div>
        """, unsafe_allow_html=True)

        for r in results:
            render_card(r, key_prefix="s")

        df_exp = pd.DataFrame(results)
        csv = df_exp.to_csv(index=False).encode("utf-8")
        st.download_button("EXPORT CSV", csv,
            file_name=f"rave_events_{date_from}.csv", mime="text/csv")

with tab_fav:
    favs = list(st.session_state.favorites.values())
    if not favs:
        st.markdown("""
        <div style="padding:4rem 0;text-align:center;">
          <div style="font-family:'Space Mono',monospace;font-size:48px;color:#1a1a1a;margin-bottom:1rem;">♥</div>
          <div style="font-family:'Space Mono',monospace;font-size:11px;color:#333;letter-spacing:2px;line-height:2.5;">
            NO SAVED EVENTS YET<br>CLICK ♡ ON ANY EVENT TO SAVE IT
          </div>
        </div>
        """, unsafe_allow_html=True)
    else:
        favs.sort(key=lambda x: x["date"])
        st.markdown(f"""
        <div style="font-family:'Space Mono',monospace;font-size:10px;color:#ff3cac;letter-spacing:2px;
                    margin-bottom:1.5rem;padding-bottom:1rem;border-bottom:0.5px solid #1d1d1d;">
            ♥ SAVED EVENTS — {len(favs)} TOTAL
        </div>
        """, unsafe_allow_html=True)

        for r in favs:
            render_card(r, key_prefix="f")

        df_fav = pd.DataFrame(favs)
        csv_fav = df_fav.to_csv(index=False).encode("utf-8")
        st.download_button("EXPORT SAVED CSV", csv_fav,
            file_name="rave_saved.csv", mime="text/csv")

        if st.button("CLEAR ALL SAVED", key="clear_all"):
            st.session_state.favorites = {}
            st.rerun()
