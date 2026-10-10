"""The user's job-hunting area: which place names count as local and what to search for."""
from urllib.parse import quote

STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California", "CO": "Colorado",
    "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia", "FL": "Florida", "GA": "Georgia",
    "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan",
    "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York", "NC": "North Carolina",
    "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island",
    "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont",
    "VA": "Virginia", "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
}


def normalize(region):
    """Clean a region dict from the UI or a pack. Returns None if no city is set."""
    if not region or not str(region.get("city", "")).strip():
        return None
    nearby = region.get("nearby") or []
    if isinstance(nearby, str):
        nearby = nearby.split(",")
    nearby = [n.strip() for n in nearby if n and n.strip()]
    queries = [q.strip() for q in region.get("queries") or [] if q and q.strip()]
    return {
        "city": region["city"].strip(),
        "state": str(region.get("state", "")).strip().upper()[:2],
        "nearby": nearby,
        "radius": max(5, min(200, int(region.get("radius") or 50))),
        "queries": queries,  # optional override of what to search for
    }


def label(region):
    return f"{region['city']}, {region['state']}" if region.get("state") else region["city"]


def area_terms(region):
    """Lowercase place names that make a job 'local'."""
    terms = [region["city"], *region["nearby"]]
    if region.get("state"):
        terms.append(f"{region['city']}, {STATES.get(region['state'], region['state'])}")
    return sorted({t.lower() for t in terms})


def search_places(region):
    """Place names to type into each employer's search box (city first, then up to 3 nearby)."""
    return region["queries"] or [region["city"], *region["nearby"][:3]]


def render_link(template, region):
    """Fill {city}, {state}, {place} (url-encoded 'City, ST') and {radius} in a manual-link URL."""
    return template.format(city=quote(region["city"]), state=quote(region.get("state", "")),
                           place=quote(label(region)), radius=region["radius"])
