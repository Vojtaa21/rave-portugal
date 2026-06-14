import streamlit as st
import requests
from datetime import date, timedelta
import pandas as pd

MESTA = {
    "Porto":   364,
    "Lisabon": 53,
}

ZANRY_MOZNOSTI = ["Techno", "Hard Techno", "Drum & Bass", "Psytrance", "House", "Trance"]

RA_URL = "https://ra.co/graphql"
RA_HEADERS = {
    "Content-Type": "application/json",
    "Referer": "https://ra.co/events",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
}

EVENTS_QUERY = """
query GET_DEFAULT_EVENTS_OVERVIEW(
  $filters: FilterInputDtoInput
  $pageSize: Int
  $page: Int
) {
  eventListings(filters: $filters, pageSize: $pageSize, page: $page) {
    data {
      event {
        id
        title
        date
        startTime
        contentUrl
        venue { name address }
        artists { name }
        genres { name }
        attending
      }
    }
    totalResults
  }
}
"""

def fetch_events(area_id: int, date_from: date, date_to: date) -> tuple[list[dict], int]:
    payload = {
        "query": EVENTS_QUERY,
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
            st.error(f"RA API chyba: {data['errors'][0].get('message', '?')}")
            return [], 0
        listings = data.get("data", {}).get("eventListings", {})
        events = [item["event"] for item in listings.get("data", [])]
        total = listings.get("totalResults", 0)
        return events, total
    except requests.RequestException as e:
        st.error(f"❌ Chyba připojení: {e}")
        return [], 0


def genre_matches(event_genres: list[str], selected: list[str]) -> bool:
    if not selected:
        return True
    low = [g.lower() for g in event_genres]
    return any(s.lower() in eg for s in selected for eg in low)


def parse_events(raw: list[dict], selected_genres: list[str]) -> pd.DataFrame:
    rows = []
    for e in raw:
        genres = [g["name"] for g in e.get("genres", [])]
        if not genre_matches(genres, selected_genres):
            continue
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
            "Žánr":         ", ".join(genres) or "—",
            "Odkaz":        f"https://ra.co{e['contentUrl']}" if e.get("contentUrl") else "",
        })
    return pd.DataFrame(rows)


# ── UI ────────────────────────────────────────────────────────

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
st.markdown('<p class="rave-sub">Vyhledávač techno & rave akcí v Portugalsku — data z Resident Advisor</p>', unsafe_allow_html=True)

with st.sidebar:
    st.markdown("### 🔍 Filtry")
    mesto = st.selectbox("Město", options=list(MESTA.keys()))
    st.markdown("**Datum**")
    c1, c2 = st.columns(2)
    with c1: datum_od = st.date_input("Od", value=date.today())
    with c2: datum_do = st.date_input("Do", value=date.today() + timedelta(days=30))
    zanry = st.multiselect(
        "Žánry (nechej prázdné = vše)", options=ZANRY_MOZNOSTI,
        default=["Techno", "Hard Techno", "Drum & Bass", "Psytrance"],
    )
    hledat = st.button("🔎  Vyhledat akce")
    st.markdown("---")
    st.caption("Data: [Resident Advisor](https://ra.co)")

if hledat:
    if datum_od > datum_do:
        st.warning("⚠️ Datum 'Od' musí být dříve než datum 'Do'.")
    else:
        area_id = MESTA[mesto]
        with st.spinner(f"Načítám akce v {mesto}…"):
            raw, total = fetch_events(area_id, datum_od, datum_do)

        # Debug info
        st.caption(f"ℹ️ RA API vrátilo {len(raw)} akcí (celkem v DB: {total}) pro area ID {area_id}")
        if raw:
            urls = [e.get("contentUrl", "—") for e in raw[:3]]
            st.caption(f"Ukázka URL: {' | '.join(urls)}")

        if not raw:
            st.info("RA API nevrátilo žádné akce. Zkus širší datumové rozmezí.")
        else:
            df = parse_events(raw, zanry)
            if df.empty:
                st.info("Akce existují, ale žádná neodpovídá vybraným žánrům. Zkus odebrat filtr.")
            else:
                st.success(f"✅ Nalezeno **{len(df)}** akcí v {mesto} ({datum_od} – {datum_do})")
                st.dataframe(df.drop(columns=["Odkaz"]), use_container_width=True, hide_index=True)
                with st.expander("🔗 Přímé odkazy na akce"):
                    for _, row in df.iterrows():
                        if row["Odkaz"]:
                            st.markdown(f"- [{row['Název akce']} – {row['Datum']}]({row['Odkaz']})")
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
