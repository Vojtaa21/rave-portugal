import streamlit as st
import requests
from datetime import date, timedelta
import pandas as pd

# ═══════════════════════════════════════════════════════════════
#  KONFIGURACE
# ═══════════════════════════════════════════════════════════════

# Klíčová slova pro vyhledání area ID přes RA GraphQL API
# + URL slug pro ověření, že akce jsou skutečně v daném městě
MESTA = {
    "Porto":   {"search": "porto",  "url_slug": "/pt/porto"},
    "Lisabon": {"search": "lisbon", "url_slug": "/pt/lisbon"},
}

ZANRY_MOZNOSTI = ["Techno", "Hard Techno", "Drum & Bass", "Psytrance", "House", "Trance"]

RA_URL = "https://ra.co/graphql"
RA_HEADERS = {
    "Content-Type": "application/json",
    "Referer": "https://ra.co/events",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
}

AREA_QUERY = """
query FindArea($search: String!) {
  areas(searchTerm: $search) {
    id
    name
    urlName
    country { name isoCode }
  }
}
"""

EVENTS_QUERY = """
query GetEvents($filters: FilterInputDtoInput, $pageSize: Int, $page: Int) {
  eventListings(filters: $filters, pageSize: $pageSize, page: $page) {
    data {
      event {
        id
        title
        date
        startTime
        contentUrl
        venue { name }
        artists { name }
        genres { name }
      }
    }
    totalResults
  }
}
"""

# ═══════════════════════════════════════════════════════════════
#  FUNKCE
# ═══════════════════════════════════════════════════════════════

def ra_post(query: str, variables: dict) -> dict:
    """Odešle GraphQL dotaz na RA API."""
    resp = requests.post(
        RA_URL,
        headers=RA_HEADERS,
        json={"query": query, "variables": variables},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


@st.cache_data(ttl=3600)
def get_area_id(search_term: str, url_slug: str) -> int | None:
    """
    Dynamicky zjistí area ID pro dané město.
    Hledá shodu podle url_slug (např. '/pt/porto') aby nevznikl konflikt
    s jiným městem se stejným názvem (např. Porto ve Španělsku).
    """
    try:
        data = ra_post(AREA_QUERY, {"search": search_term})
        areas = data.get("data", {}).get("areas", [])
        for area in areas:
            area_url = (area.get("urlName") or "").lower()
            if url_slug.lower() in area_url or area_url.endswith(url_slug.split("/")[-1]):
                country = area.get("country", {})
                if country.get("isoCode", "").upper() == "PT":
                    return int(area["id"])
        # záloha: vrátí první výsledek z Portugalska
        for area in areas:
            if area.get("country", {}).get("isoCode", "").upper() == "PT":
                return int(area["id"])
        return None
    except Exception as e:
        st.error(f"❌ Chyba při zjišťování area ID: {e}")
        return None


def fetch_events(area_id: int, date_from: date, date_to: date, max_results: int = 50) -> list[dict]:
    """Stáhne akce z RA GraphQL API."""
    variables = {
        "filters": {
            "areas": {"eq": area_id},
            "listingDate": {
                "gte": date_from.strftime("%Y-%m-%dT00:00:00.000Z"),
                "lte": date_to.strftime("%Y-%m-%dT23:59:59.999Z"),
            },
        },
        "pageSize": max_results,
        "page": 1,
    }
    try:
        data = ra_post(EVENTS_QUERY, variables)
        listings = data.get("data", {}).get("eventListings", {})
        return [item["event"] for item in listings.get("data", [])]
    except requests.RequestException as e:
        st.error(f"❌ Chyba při načítání akcí: {e}")
        return []


def genre_matches(event_genres: list[str], selected_genres: list[str]) -> bool:
    """Vrátí True pokud akce obsahuje alespoň jeden vybraný žánr."""
    if not selected_genres:
        return True
    ev_lower = [g.lower() for g in event_genres]
    for sg in selected_genres:
        if any(sg.lower() in eg for eg in ev_lower):
            return True
    return False


def parse_events(raw: list[dict], selected_genres: list[str]) -> pd.DataFrame:
    """Zpracuje surová data z API do přehledné tabulky."""
    rows = []
    for e in raw:
        genres = [g["name"] for g in e.get("genres", [])]
        if not genre_matches(genres, selected_genres):
            continue

        datum = (e.get("date") or "")[:10]
        cas_raw = e.get("startTime", "")
        cas = cas_raw.split("T")[1][:5] if cas_raw and "T" in cas_raw else "—"

        venue = e.get("venue") or {}
        umelci = ", ".join(a["name"] for a in e.get("artists", [])) or "—"
        zanry_str = ", ".join(genres) or "—"
        odkaz = f"https://ra.co{e['contentUrl']}" if e.get("contentUrl") else ""

        rows.append({
            "Datum": datum,
            "Čas": cas,
            "Název akce": e.get("title", "—"),
            "Místo / Klub": venue.get("name", "—"),
            "Interpreti": umelci,
            "Žánr": zanry_str,
            "Odkaz": odkaz,
        })
    return pd.DataFrame(rows)


# ═══════════════════════════════════════════════════════════════
#  VZHLED
# ═══════════════════════════════════════════════════════════════

st.set_page_config(
    page_title="🎛️ Rave Portugal",
    page_icon="🎛️",
    layout="wide",
)

st.markdown("""
<style>
    .rave-title {
        font-family: 'Courier New', monospace;
        font-size: 2.4rem;
        font-weight: 700;
        letter-spacing: 2px;
        color: #e0ff4f;
        margin-bottom: 0;
    }
    .rave-sub {
        font-size: 0.95rem;
        color: #888;
        margin-top: 2px;
        margin-bottom: 1.5rem;
        font-family: 'Courier New', monospace;
    }
    .stDataFrame { border-radius: 8px; overflow: hidden; }
    div.stButton > button {
        background: #e0ff4f;
        color: #111;
        font-weight: 700;
        font-family: 'Courier New', monospace;
        letter-spacing: 1px;
        border: none;
        border-radius: 6px;
        padding: 0.55rem 2rem;
        width: 100%;
        margin-top: 0.5rem;
    }
    div.stButton > button:hover { background: #c8e600; }
    section[data-testid="stSidebar"] { background: #111; }
    section[data-testid="stSidebar"] label { color: #ccc !important; font-family: 'Courier New', monospace; }
</style>
""", unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════════
#  ROZHRANÍ
# ═══════════════════════════════════════════════════════════════

st.markdown('<p class="rave-title">🎛️ RAVE PORTUGAL</p>', unsafe_allow_html=True)
st.markdown('<p class="rave-sub">Vyhledávač techno & rave akcí v Portugalsku — data z Resident Advisor</p>', unsafe_allow_html=True)

with st.sidebar:
    st.markdown("### 🔍 Filtry")

    mesto = st.selectbox("Město", options=list(MESTA.keys()))

    st.markdown("**Datum**")
    col1, col2 = st.columns(2)
    with col1:
        datum_od = st.date_input("Od", value=date.today())
    with col2:
        datum_do = st.date_input("Do", value=date.today() + timedelta(days=30))

    zanry = st.multiselect(
        "Žánry (nechej prázdné = vše)",
        options=ZANRY_MOZNOSTI,
        default=["Techno", "Hard Techno", "Drum & Bass", "Psytrance"],
    )

    hledat = st.button("🔎  Vyhledat akce")

    st.markdown("---")
    st.caption("Data poskytuje [Resident Advisor](https://ra.co). Žánry se filtrují lokálně.")

# ── Hlavní oblast ─────────────────────────────────────────────
if hledat:
    if datum_od > datum_do:
        st.warning("⚠️ Datum 'Od' musí být dříve než datum 'Do'.")
    else:
        mesto_cfg = MESTA[mesto]

        with st.spinner(f"Zjišťuji area ID pro {mesto}…"):
            area_id = get_area_id(mesto_cfg["search"], mesto_cfg["url_slug"])

        if area_id is None:
            st.error(f"❌ Nepodařilo se najít area ID pro {mesto}. RA API nemusí být dostupné.")
        else:
            st.caption(f"ℹ️ Použité area ID pro {mesto}: `{area_id}`")

            with st.spinner(f"Načítám akce v {mesto}…"):
                raw = fetch_events(area_id, datum_od, datum_do)

            if not raw:
                st.info("Žádné akce nebyly nalezeny. Zkus jiné město nebo širší datumové rozmezí.")
            else:
                df = parse_events(raw, zanry)

                if df.empty:
                    st.info(f"Akce v {mesto} existují, ale žádná neodpovídá vybraným žánrům.")
                else:
                    st.success(f"✅ Nalezeno **{len(df)}** akcí v {mesto} ({datum_od} – {datum_do})")

                    zobraz = df.drop(columns=["Odkaz"])
                    st.dataframe(zobraz, use_container_width=True, hide_index=True)

                    with st.expander("🔗 Přímé odkazy na akce"):
                        for _, row in df.iterrows():
                            if row["Odkaz"]:
                                st.markdown(f"- [{row['Název akce']} – {row['Datum']}]({row['Odkaz']})")

                    csv = df.to_csv(index=False).encode("utf-8")
                    st.download_button(
                        label="⬇️  Stáhnout jako CSV",
                        data=csv,
                        file_name=f"rave_{mesto.lower()}_{datum_od}.csv",
                        mime="text/csv",
                    )
else:
    st.markdown("""
    <div style="text-align:center; padding: 3rem 0; color: #555;">
        <p style="font-size: 3rem;">🎶</p>
        <p style="font-family: 'Courier New', monospace;">Vyber město, datum a žánry v levém panelu,<br>pak klikni na <strong>Vyhledat akce</strong>.</p>
    </div>
    """, unsafe_allow_html=True)
