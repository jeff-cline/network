"""Product data, extracted verbatim from
"09 2025 Copy of Insure Your Way - Individual Plans Availability.xlsx".

Four tabs: State Availability, Plan Options, T365 State Availability (an image),
T365 Pricing (an image). The T365 tabs held pictures rather than cells, so their
contents were read off the images and transcribed here.

WHAT THE WORKBOOK DOES NOT CONTAIN: premium rates for AD&D, Accident Medical
Expense or Critical Illness. It gives benefit amounts, tiers and age *bands* —
but no dollar cost per band. Those rates live in RATES (rates.json) and ship as
clearly-labelled demo values until the carrier sheet is loaded. Travel 365 is
the exception: its rates below are real, taken from the pricing image.
"""

CARRIER = "Chubb"
UNDERWRITER = ("ACE Property & Casualty Insurance Company or ACE American Insurance Company "
               "and its U.S.-based Chubb underwriting company affiliates or network partners")
PROGRAM = "Insure Your Way"

# ============================================================ availability ====
# From the State Availability tab. A state is live only where the product is
# ticked. Dated-but-unticked states are filed and pending; blank states are not
# offered at all. We never quote outside a live state.
LIVE = {
    "AL": {"add": 1, "ame": 1, "ci": 1, "comm": .15},
    "AR": {"add": 1, "ame": 1, "ci": 1, "comm": .15},
    "AZ": {"add": 1, "ame": 1, "ci": 1, "comm": .15},
    "CA": {"add": 1, "ame": 1, "ci": 1, "comm": .15},
    "CO": {"add": 1, "ame": 1, "ci": 1, "comm": .15},
    "DE": {"add": 1, "ame": 1, "ci": 1, "comm": .15},
    "FL": {"add": 1, "ame": 1, "ci": 0, "comm": .10},
    "HI": {"add": 1, "ame": 1, "ci": 1, "comm": .15},
    "IA": {"add": 1, "ame": 1, "ci": 1, "comm": .15},
    "IL": {"add": 1, "ame": 1, "ci": 1, "comm": .15},
    "IN": {"add": 1, "ame": 1, "ci": 1, "comm": .15},
    "KS": {"add": 1, "ame": 1, "ci": 0, "comm": .15},
    "KY": {"add": 1, "ame": 1, "ci": 1, "comm": .15},
    "LA": {"add": 1, "ame": 1, "ci": 1, "comm": .15},
    "ME": {"add": 1, "ame": 1, "ci": 1, "comm": .15},
    "MO": {"add": 1, "ame": 1, "ci": 1, "comm": .15},
    "MS": {"add": 1, "ame": 1, "ci": 1, "comm": .15},
    "MT": {"add": 1, "ame": 1, "ci": 1, "comm": .15},
    "NC": {"add": 1, "ame": 1, "ci": 1, "comm": .15},
    "NE": {"add": 1, "ame": 1, "ci": 1, "comm": .15},
    "NH": {"add": 1, "ame": 1, "ci": 0, "comm": .15},
    "NV": {"add": 1, "ame": 1, "ci": 1, "comm": .15},
    "OH": {"add": 1, "ame": 1, "ci": 1, "comm": .15},
    "OK": {"add": 1, "ame": 1, "ci": 1, "comm": .15},
    "RI": {"add": 1, "ame": 1, "ci": 1, "comm": .15},
    "SC": {"add": 1, "ame": 1, "ci": 1, "comm": .15},
    "SD": {"add": 1, "ame": 1, "ci": 0, "comm": .10},
    "UT": {"add": 1, "ame": 1, "ci": 0, "comm": .15},
    "WI": {"add": 1, "ame": 1, "ci": 1, "comm": .15},
    "WV": {"add": 1, "ame": 1, "ci": 1, "comm": .15},
}
# Filed, launch dated, not yet writing.
PENDING = {"CT": "2025-10-01", "DC": "2025-10-01", "GA": "2025-10-01", "ID": "2025-10-01",
           "MD": "2025-10-01", "MI": "2025-10-01", "MN": "2025-10-01", "ND": "2025-10-01",
           "NJ": "2025-10-01", "OR": "2025-10-01", "PA": "2025-10-01", "TN": "2025-10-01",
           "TX": "2025-10-01", "VA": "2025-10-01", "VT": "2025-10-01", "WY": "2025-10-01"}
# Not offered.
UNAVAILABLE = ["AK", "MA", "NM", "NY", "WA"]

# ================================================================ products ====
PRODUCTS = {
    "add": {
        "code": "add", "name": "Accidental Death & Dismemberment", "short": "AD&D",
        "icon": "🛡️",
        "benefits": [5000, 10000, 25000, 50000, 75000, 100000, 150000, 200000,
                     250000, 300000, 400000, 500000, 750000, 1000000],
        "bands": ["18-24", "25-34", "35-44", "45-54", "55-64", "65-74", "75+"],
    },
    "ame": {
        "code": "ame", "name": "Accident Medical Expense", "short": "AME",
        "icon": "🩹",
        "benefits": [2500, 5000, 10000, 25000, 50000, 100000, 150000, 200000,
                     250000, 500000, 1000000],
        "deductibles": [0, 25, 50, 100, 150, 200, 250, 300, 400, 500, 1000],
        "bands": ["18-24", "25-29", "30-34", "35-39", "40-44", "45-49", "50-54",
                  "55-59", "60-64", "65-69", "70-74", "75-79", "80-84", "85+"],
    },
    "ci": {
        "code": "ci", "name": "Critical Illness", "short": "CI",
        "icon": "❤️‍🩹",
        "benefits": [2500, 5000, 7500, 10000, 12500, 15000, 20000, 25000],
        "bands": ["18-24", "25-29", "30-34", "35-39", "40-44", "45-49", "50-54",
                  "55-59", "60-64"],
    },
}

# The workbook lists these six combinations and no others — notably there is no
# all-three bundle, so the quoter must not offer one.
VARIATIONS = [
    ("add", "AD&D Only"),
    ("ame", "AME Only"),
    ("ci", "Critical Illness Only"),
    ("add+ame", "AD&D and AME"),
    ("add+ci", "AD&D and Critical Illness"),
    ("ame+ci", "AME and Critical Illness"),
]

TIERS = [
    ("single", "Single", 1, 0),
    ("single_spouse", "Single + Spouse", 2, 0),
    ("single_1c", "Single + 1 Child", 1, 1),
    ("single_2c", "Single + 2 Children", 1, 2),
    ("single_3c", "Single + 3 Children", 1, 3),
    ("single_4c", "Single + 4+ Children", 1, 4),
    ("single_spouse_1c", "Single + Spouse + 1 Child", 2, 1),
    ("single_spouse_2c", "Single + Spouse + 2 Children", 2, 2),
    ("single_spouse_3c", "Single + Spouse + 3 Children", 2, 3),
    ("single_spouse_4c", "Single + Spouse + 4+ Children", 2, 4),
]
TIER_BY_KEY = {k: (label, adults, kids) for k, label, adults, kids in TIERS}

# Florida is filed unbanded — one rate for all ages, varying year over year.
UNBANDED_STATES = {"FL"}


def band_for(product, age):
    """Return the rating band a given age falls into for a product."""
    try:
        age = int(age)
    except (TypeError, ValueError):
        return None
    for b in PRODUCTS[product]["bands"]:
        if b.endswith("+"):
            if age >= int(b[:-1]):
                return b
        else:
            lo, hi = b.split("-")
            if int(lo) <= age <= int(hi):
                return b
    return None


def eligible(product, age):
    """Outside the filed bands there is no rate, so there is no quote."""
    return band_for(product, age) is not None


def state_products(state):
    """Which of the three are actually writable in this state today."""
    s = LIVE.get((state or "").upper())
    if not s:
        return []
    return [p for p in ("add", "ame", "ci") if s.get(p)]


def state_status(state):
    st = (state or "").upper()
    if st in LIVE:
        return "live"
    if st in PENDING:
        return "pending"
    if st in UNAVAILABLE:
        return "unavailable"
    return "unknown"


# ============================================================= Travel 365 ====
# Real rates, transcribed from the T365 Pricing image. Rates are per person and
# all coverages are aggregate amounts for the annual term.
T365_PLANS = [
    ("basics", "Travel 365 Basics", "#e8a33d"),
    ("essentials", "Travel 365 Essentials", "#8cc63f"),
    ("choice", "Travel 365 Choice", "#ec3f8f"),
]

T365_TIER_STATES = {
    1: ["CT", "GA", "KS", "KY", "MA", "ME", "MI", "MN", "MS", "NC", "NE", "NH", "NM", "WV"],
    2: ["AK", "AL", "AR", "AZ", "CO", "DC", "DE", "FL", "HI", "IA", "ID", "IL", "IN", "LA",
        "MD", "ND", "NJ", "NV", "OH", "OK", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VA",
        "VT", "WA", "WI", "WY"],
    3: ["CA"],
}
# tier -> plan -> {yearly, monthly, biweekly}
T365_RATES = {
    1: {"basics":     {"yearly": 144.00, "monthly": 12.00, "biweekly": 5.54},
        "essentials": {"yearly": 236.00, "monthly": 19.67, "biweekly": 9.08},
        "choice":     {"yearly": 454.00, "monthly": 37.83, "biweekly": 17.46}},
    2: {"basics":     {"yearly": 141.00, "monthly": 11.75, "biweekly": 5.42},
        "essentials": {"yearly": 233.00, "monthly": 19.42, "biweekly": 8.96},
        "choice":     {"yearly": 449.00, "monthly": 37.42, "biweekly": 17.27}},
    3: {"basics":     {"yearly": 120.18, "monthly": 10.02, "biweekly": 4.62},
        "essentials": {"yearly": 196.97, "monthly": 16.41, "biweekly": 7.58},
        "choice":     {"yearly": 378.91, "monthly": 31.58, "biweekly": 14.57}},
}
T365_MAX_AGE = 80          # "Plans are not available for travelers over 80 years old."
# Travel 365 is sold as an annual policy. Monthly and bi-weekly figures exist to
# make the price comparable, not because the customer can buy it that way.
T365_SOLD_AS = "annual"
T365_NOTES = [
    "Travel 365 is purchased as an annual policy. Monthly and bi-weekly figures are shown for "
    "comparison only — the plan is bought and billed for the full year.",
    "Coverage limits and rates are per person. All coverages are aggregate amounts for the "
    "annual term.",
    "Plans are not available for travelers over 80 years old.",
    "Plans do not include the Financial Default benefit.",
    "Coverage is not available in all states.",
]
T365_SOURCE = "https://tinyurl.com/chubbtravel365"
# Chubb's own availability sheet lists all 50 states plus DC. The pricing image
# only assigns tiers to 47 of them, so these four have no published rate and are
# quoted on request rather than guessed at.
T365_NO_RATE = ["MO", "MT", "NY", "OR"]


def t365_tier(state):
    st = (state or "").upper()
    for tier, states in T365_TIER_STATES.items():
        if st in states:
            return tier
    return None


STATE_NAMES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois",
    "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
    "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan",
    "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri", "MT": "Montana",
    "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey",
    "NM": "New Mexico", "NY": "New York", "NC": "North Carolina", "ND": "North Dakota",
    "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania",
    "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee",
    "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington",
    "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
}

# =============================================================== moneywords ===
# Phrases that identify intent on an inbound call. Each maps to the product the
# caller is really asking about, so the phone system can route and attribute.
MONEYWORDS = [
    ("accidental death", "add"), ("accidental death and dismemberment", "add"),
    ("ad&d", "add"), ("add policy", "add"), ("death benefit", "add"),
    ("dismemberment", "add"), ("lost a limb", "add"), ("accidental death insurance", "add"),
    ("accident medical", "ame"), ("accident medical expense", "ame"),
    ("ame", "ame"), ("accident insurance", "ame"), ("er bill", "ame"),
    ("emergency room", "ame"), ("deductible help", "ame"), ("out of pocket", "ame"),
    ("critical illness", "ci"), ("cancer policy", "ci"), ("heart attack coverage", "ci"),
    ("stroke coverage", "ci"), ("lump sum diagnosis", "ci"),
    ("travel insurance", "t365"), ("travel medical", "t365"), ("trip cancellation", "t365"),
    ("travel 365", "t365"), ("annual travel policy", "t365"), ("trip interruption", "t365"),
]
