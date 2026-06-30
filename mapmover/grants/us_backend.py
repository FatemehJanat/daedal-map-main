"""
US Grant Backend - deterministic backend functions for the US grant-
matching vertical, kept deliberately decoupled from any MCP/server
protocol per MCP_artifact.md's own sequencing ("build and test against
the grant corpus first, privately" before any server/auth scaffolding).

Split out of grant_analyzer.py (2026-06-29) as part of a country-adapter
refactor, prompted directly by an external architecture review: this
module was accumulating US-specific assumptions (CFDA-keyed precedent
lookups, USA-XX loc_id parsing, Grants.gov live checks) inside what was
nominally a country-agnostic file, with no second real backend to check
the abstraction against. See can_backend.py for Canada's backend (real,
but deliberately narrower - see its CAPABILITIES dict) and
grant_analyzer.py for the thin country-keyed coordinator both live under.
A formal shared-interface contract (e.g. a CountryGrantBackend base
class) is deliberately NOT introduced yet - with only one full
implementation (this one) and one partial one, the real shared shape
isn't visible yet; forcing an interface now would be guessing at a
boundary instead of finding it. Revisit once Canada gets its own scoring
function.

Functions, matching the design in grant_funding_programs.md and
grant_readiness_score.md:

    match_grant_programs()       - Step 1: eligibility filter + blockers
    get_grant_precedents()       - Step 2: precedent lookup
    check_prior_federal_awards() - capacity signal, the "free win" identified
                                    in grant_readiness_score.md (no new data
                                    needed, just a lookup against USA.parquet)
    get_grant_writing_template()  - which narrative format/sections apply
    score_and_rank_programs()    - the composite 0-100 Grant Readiness Score,
                                    combining the above into a ranked top-N

These are plain functions returning plain dicts/lists - no LLM calls, no
protocol coupling. Most are deterministic local-data lookups; the
explicitly live helpers (`find_open_opportunities_live()` and
`check_open_opportunity(..., live_fallback=True)`) do make network calls
to Grants.gov by design. An MCP tool (or anything else) can wrap these
later without changing the logic.

IMPORTANT - the honesty constraint from grant_readiness_score.md applies
here too: nothing in this module computes or returns a probability of
winning a grant. The 0-100 score is a FIT score against the historical
winner profile, not a win probability - USAspending has no rejected-
application data, so no probability claim is statistically supportable.
Every score must carry that caveat when displayed. Do not add a "success
probability" field without re-reading grant_readiness_score.md's "core
honesty constraint" section first.
"""
import functools
import re
from pathlib import Path

import pandas as pd

from mapmover.paths import DATA_ROOT

from .rate_limited_fetcher import RateLimitedFetcher
from .schema import validate_programs_df
from .tristate import parse_tristate

MODULE_DIR = Path(__file__).resolve().parent
DATA_DIR = MODULE_DIR / "data"
PROGRAMS_CSV = DATA_DIR / "grant_funding_programs.csv"
TEMPLATES_CSV = DATA_DIR / "grant_writing_templates.csv"
OPEN_OPPORTUNITIES_CSV = DATA_ROOT / "countries" / "USA" / "grants_gov_open_opportunities" / "latest.csv"
CFDA_SUMMARY_PARQUET = DATA_ROOT / "countries" / "USA" / "usaspending_grants" / "cfda_program_summary.parquet"
AWARDS_PARQUET = DATA_ROOT / "countries" / "USA" / "usaspending_grants" / "USA.parquet"

# Real, current capability set - surfaced so a caller (or grant_analyzer.py's
# coordinator) can check what this backend actually supports instead of
# discovering gaps by exception. All True today; kept as a dict (not a
# hardcoded assumption) so a future capability regression is a one-line
# diff, not a silent behavior change.
CAPABILITIES = {
    "discovery": True,
    "precedent": True,
    "readiness_scoring": True,
    "live_opportunity_check": True,
    "writing_template": True,
}

# Cached loaders - these files get read repeatedly within a single
# score_and_rank_programs() call (once per matched program, sometimes
# twice for the same file). Caching means "load once per process," not
# "load once per logical question" - call clear_caches() in long-running
# processes (e.g. an eventual MCP server) after any of these files change
# on disk, or stale data will be served.
@functools.lru_cache(maxsize=1)
def _load_programs_cached():
    df = pd.read_csv(PROGRAMS_CSV, dtype=str)
    validate_programs_df(df, "grant_funding_programs.csv")
    return df


@functools.lru_cache(maxsize=1)
def _load_templates_cached():
    return pd.read_csv(TEMPLATES_CSV, dtype=str)


@functools.lru_cache(maxsize=1)
def _load_cfda_summary_cached():
    return pd.read_parquet(CFDA_SUMMARY_PARQUET)


@functools.lru_cache(maxsize=1)
def _load_open_opportunities_cached():
    if not OPEN_OPPORTUNITIES_CSV.exists():
        return None
    return pd.read_csv(OPEN_OPPORTUNITIES_CSV, dtype=str)


@functools.lru_cache(maxsize=1)
def _load_awards_for_track_record_cached():
    return pd.read_parquet(
        AWARDS_PARQUET,
        columns=["recipient_name", "cfda_numbers_and_titles", "total_obligated_amount", "award_base_action_date"],
    )


@functools.lru_cache(maxsize=1)
def _load_awards_for_country_precedent_cached():
    return pd.read_parquet(
        AWARDS_PARQUET,
        columns=[
            "cfda_numbers_and_titles", "place_of_performance_country_code",
            "total_obligated_amount", "recipient_business_type_description",
            "award_description", "award_base_action_date",
        ],
    )


def clear_caches():
    """Call after any underlying CSV/parquet changes on disk, in a
    long-running process. A fresh CLI run doesn't need this - the cache
    only lives as long as the process does."""
    for fn in (_load_programs_cached, _load_templates_cached, _load_cfda_summary_cached,
               _load_open_opportunities_cached, _load_awards_for_track_record_cached,
               _load_awards_for_country_precedent_cached):
        fn.cache_clear()

# Score weights (sum to 100). Precedent strength deliberately NOT included
# here - per grant_readiness_score.md, low precedent strength should lower
# DISPLAYED CONFIDENCE, not silently change the fit score itself.
WEIGHT_RECIPIENT_TYPE = 30
WEIGHT_GEOGRAPHY = 20
WEIGHT_AWARD_SIZE = 20
WEIGHT_CAPACITY = 30

# Best-effort state mapping for the non-"national" geography_scope values
# currently in grant_funding_programs.csv. Not exhaustive - extend as new
# geography_scope values get added to the CSV. ARC's 13-state Appalachian
# region definition (subset of full-state abbreviations actually used by
# loc_id prefixes, not sub-state county precision).
GEOGRAPHY_STATE_MAP = {
    "appalachia": {"AL", "GA", "KY", "MD", "MS", "NC", "NY", "OH", "PA", "SC", "TN", "VA", "WV"},
    "mn_nd_sd_plus_23_tribal_nations": {"MN", "ND", "SD"},
}

BOILERPLATE_MARKERS = ("NOT APPLICABLE", "DATA NOT AVAILABLE", "NOT AVAILABLE")

# Abbreviations in the eligible_applicant_types vocabulary that don't appear
# as the same token in USAspending's recipient_business_type_description text
# (e.g. org_type "higher_ed" -> {"HIGHER","ED"}, but the real text says
# "INSTITUTION OF HIGHER EDUCATION" - "ED" never appears as its own word, so
# a naive word-subset match silently fails). Found via the international/
# USAID validation run (2026-06-26) - usaid_university_partnerships, a
# program whose dominant recipient type IS higher-ed institutions, scored
# as if higher_ed were a rare/unmatched type until this was fixed.
ORG_TYPE_WORD_ALIASES = {"ED": "EDUCATION"}


def _org_type_words(org_type):
    return {ORG_TYPE_WORD_ALIASES.get(w, w) for w in org_type.upper().split("_")}


# USAspending's recipient_business_type_description vocabulary is coarser
# than grant_funding_programs.csv's eligible_applicant_types vocabulary -
# several org_types are qualified/compound labels (e.g. "rural_small_
# business", "nonprofit_owners_of_assisted_housing") whose qualifier words
# (RURAL, OWNERS, ASSISTED, HOUSING, ACTION, COMMUNITY, NGO, INTERNATIONAL)
# never appear in the real business-type text, so the word-subset check in
# _org_type_words() can NEVER match them - not "rare," structurally
# impossible. Found via a systematic coverage test (see
# test_org_type_coverage.py) run after the "higher_ed"/"ED" bug, which
# checked all 22 org_type vocabulary values against all 26 real
# recipient_business_type_description phrases and found 7 more silent
# false negatives. Each entry lists the literal real-world phrase
# substrings that should count as a match for that org_type - takes
# priority over the word-subset heuristic, not a supplement to it.
ORG_TYPE_PHRASE_OVERRIDES = {
    "local_government": {
        "CITY OR TOWNSHIP GOVERNMENT", "COUNTY GOVERNMENT", "SPECIAL DISTRICT GOVERNMENT",
        "REGIONAL ORGANIZATION", "INDEPENDENT SCHOOL DISTRICT", "PUBLIC/INDIAN HOUSING AUTHORITY",
    },
    "small_business": {"SMALL BUSINESS"},
    "rural_small_business": {"SMALL BUSINESS"},
    "for_profit_owners_of_assisted_housing": {"FOR-PROFIT ORGANIZATION", "SMALL BUSINESS"},
    "nonprofit_owners_of_assisted_housing": {
        "NONPROFIT WITH 501C3 IRS STATUS", "NONPROFIT WITHOUT 501C3 IRS STATUS",
    },
    "community_action_nonprofit": {
        "NONPROFIT WITH 501C3 IRS STATUS", "NONPROFIT WITHOUT 501C3 IRS STATUS",
    },
    "international_ngo": {
        "NONPROFIT WITH 501C3 IRS STATUS", "NONPROFIT WITHOUT 501C3 IRS STATUS",
        "NON-DOMESTIC (NON-U.S.) ENTITY",
    },
    "foreign_government_entity": {"NON-DOMESTIC (NON-U.S.) ENTITY"},
}

# Known USAspending CFDA-picklist data-quality glitches - a few historical
# rows record "INDIAN/NATIVE AMERICANTRIBAL GOVERNMENT" with the space
# between "AMERICAN" and "TRIBAL" dropped, which breaks word-tokenization
# matching for tribal_government (the word "TRIBAL" disappears entirely,
# glued into "AMERICANTRIBAL"). Found by the same coverage test.
BUSINESS_TYPE_TEXT_FIXES = {"AMERICANTRIBAL": "AMERICAN TRIBAL"}


def _normalize_business_type_text(text):
    upper = str(text).upper()
    for bad, good in BUSINESS_TYPE_TEXT_FIXES.items():
        upper = upper.replace(bad, good)
    return upper


def _phrase_present(phrase, entry_upper):
    """Substring check with one hardcoded negation guard: "FOR-PROFIT
    ORGANIZATION (OTHER THAN SMALL BUSINESS)" contains "SMALL BUSINESS" as
    a literal substring while explicitly meaning the opposite - it's a
    distinct, real USAspending category for for-profits that are NOT small
    businesses. A plain substring check would make small_business/
    rural_small_business false-positive-match it. Found by the same
    coverage test - general negation-handling would be overkill for one
    known phrase, so this is a narrow, named guard, not a parser.
    """
    if phrase == "SMALL BUSINESS":
        return "SMALL BUSINESS" in entry_upper and "OTHER THAN SMALL BUSINESS" not in entry_upper
    return phrase in entry_upper


def _org_type_matches_entry(org_type, entry_text):
    """Does this org_type count as a match for one recipient_type_breakdown
    entry (e.g. "NONPROFIT WITH 501C3 IRS STATUS (...) (4624)")?

    Overrides take priority (substring match against the literal real-world
    phrase) since several org_types are structurally unmatchable by the
    word-subset heuristic - see ORG_TYPE_PHRASE_OVERRIDES. Falls back to
    word-subset matching (with text normalization for known data typos)
    for everything else.
    """
    entry_upper = _normalize_business_type_text(entry_text)
    overrides = ORG_TYPE_PHRASE_OVERRIDES.get(org_type)
    if overrides:
        return any(_phrase_present(phrase, entry_upper) for phrase in overrides)

    words = _org_type_words(org_type)
    entry_words = set(re.findall(r"[A-Z0-9]+", entry_upper))
    return bool(words) and words.issubset(entry_words)


def _split_pipe(value):
    if pd.isna(value) or not str(value).strip():
        return []
    return [v.strip() for v in str(value).split("|") if v.strip()]


def _split_outside_parens(value, sep=";"):
    """Split on sep, but not when inside parentheses - "A (B; C); D" -> ["A (B; C)", "D"]."""
    parts, depth, current = [], 0, []
    for ch in str(value):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        if ch == sep and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(ch)
    parts.append("".join(current))
    return [p.strip() for p in parts if p.strip()]


def _loc_id_state(loc_id):
    if not loc_id:
        return None
    m = re.match(r"USA-([A-Z]{2})", loc_id)
    return m.group(1) if m else None


def _geography_matches(geography_scope, recipient_loc_id, place_of_performance_loc_id, target_country_code=None):
    if geography_scope in ("national",):
        return True, None
    if geography_scope in ("international", "international_frontline_communities"):
        if target_country_code:
            return True, (
                f"International scope - target country {target_country_code} given; "
                f"check country-level precedent separately (see get_country_precedent)."
            )
        if recipient_loc_id or place_of_performance_loc_id:
            # A domestic USA-xx loc_id with no target_country_code is positive
            # evidence of a domestic-only project - international programs
            # (USAID/DFC, foreign foundations) don't fund domestic work, so
            # this is a confirmed mismatch, not an "unverifiable" unknown.
            # Found via validation (2026-06-26): without this, a domestic
            # Appalachia nonprofit's shared "disaster_recovery" sector tag
            # let it match USAID programs it can never actually apply to.
            return False, "International scope - your project's loc_id indicates domestic-only work and no target country was given; this program doesn't fund domestic work."
        return None, "International scope - no domestic loc_id or target country given, can't verify either way."

    allowed_states = GEOGRAPHY_STATE_MAP.get(geography_scope)
    if allowed_states is None:
        return None, f"Unknown geography_scope '{geography_scope}' - not in GEOGRAPHY_STATE_MAP, can't verify"

    candidate_states = {s for s in (_loc_id_state(recipient_loc_id), _loc_id_state(place_of_performance_loc_id)) if s}
    if not candidate_states:
        return None, "No loc_id given - can't verify geography match"

    return bool(candidate_states & allowed_states), None


def load_programs():
    return _load_programs_cached()


def match_grant_programs(
    org_type,
    sector_tags=None,
    recipient_loc_id=None,
    place_of_performance_loc_id=None,
    has_government_partner=False,
    has_match_funding=False,
    target_country_code=None,
):
    """Step 1: filter grant_funding_programs.csv for a project's profile.

    org_type: a single value from the eligible_applicant_types vocabulary
        in grant_funding_programs.md (e.g. "nonprofit_501c3").
    sector_tags: list of sector tags to match against (optional - if
        omitted, sector isn't used as a filter).
    recipient_loc_id / place_of_performance_loc_id: both should be passed
        when known. If only one is available, ASK rather than assume they
        match - they disagree on 28-43% of real awards (see
        grant_funding_programs.md). Passing only one is allowed but the
        geography check will be weaker.
    has_government_partner: whether the project already has a state/local/
        tribal government co-applicant lined up.
    has_match_funding: whether the project has match funding available.
    target_country_code: ISO 3-letter country code (e.g. "VEN") for
        international-scope programs. Without it, a domestic loc_id
        confirms a domestic-only project and excludes international
        programs (they don't fund domestic work); omitting both loc_id
        and country leaves international scope as an unverifiable unknown
        rather than a confirmed match or mismatch.

    Returns a list of dicts, ranked: directly-eligible-no-blockers first,
    then eligible-via-pathway (blocked but workable), then not eligible at
    all. Does NOT compute or return a success probability - see module
    docstring.

    requires_government_intermediary/requires_match_funding are tri-state
    (TRUE/FALSE/UNKNOWN) in the CSV - UNKNOWN never becomes a blocker (we
    don't assert a requirement we haven't confirmed), but it also never
    silently becomes "no blocker" the way a naive TRUE-only check would -
    see tristate.py's docstring for the real bug this prevents. Unknown
    requirements are surfaced via `unknown_requirements` on each result.
    """
    df = load_programs()
    results = []

    for _, row in df.iterrows():
        eligible_types = _split_pipe(row["eligible_applicant_types"])
        if org_type not in eligible_types:
            continue  # hard gate - not eligible under any pathway

        if sector_tags:
            program_tags = set(_split_pipe(row["sector_tags"]))
            if not (set(sector_tags) & program_tags):
                continue

        geo_match, geo_note = _geography_matches(
            row["geography_scope"], recipient_loc_id, place_of_performance_loc_id, target_country_code
        )
        if geo_match is False:
            continue  # confirmed geography mismatch - exclude

        requires_intermediary = parse_tristate(row["requires_government_intermediary"])
        requires_match = parse_tristate(row["requires_match_funding"])

        blockers = []
        unknown_requirements = []
        if requires_intermediary is True and not has_government_partner:
            blockers.append(
                "Requires a government (state/local/tribal) co-applicant - "
                "you cannot apply directly without one."
            )
        elif requires_intermediary is None:
            unknown_requirements.append(
                "Whether this program requires a government co-applicant is unconfirmed - "
                "verify before relying on direct eligibility."
            )
        if requires_match is True and not has_match_funding:
            blockers.append("Requires match funding, which isn't confirmed available yet.")
        elif requires_match is None:
            unknown_requirements.append(
                "Whether this program requires match funding is unconfirmed - verify before applying."
            )

        pathway_note = None
        if requires_intermediary is True and has_government_partner:
            pathway_note = "Eligible via your government partner as co-applicant/sub-applicant."
        elif requires_intermediary is True:
            pathway_note = (
                "Cannot apply directly. Find a state/local/tribal government "
                "willing to apply on your behalf."
            )

        results.append({
            "program_id": row["program_id"],
            "program_name": row["program_name"],
            "funder_type": row["funder_type"],
            "agency_or_funder": row["agency_or_funder"],
            "cfda_number": row["cfda_number"] if pd.notna(row["cfda_number"]) else None,
            "funds_what": row["funds_what"],
            "geography_note": geo_note,
            "blockers": blockers,
            "unknown_requirements": unknown_requirements,
            "eligibility_confidence": "uncertain" if unknown_requirements else "confirmed",
            "directly_eligible": len(blockers) == 0,
            "pathway_note": pathway_note,
            "typical_award_size": row["typical_award_size"],
            "notes": row["notes"],
            "source_url": row["source_url"],
        })

    results.sort(key=lambda r: (not r["directly_eligible"], len(r["blockers"])))
    return results


def _classify_precedent_confidence(samples):
    if not samples:
        return "none", "No sample award text available for this program."

    texts = [s.strip() for s in samples.split(" ||| ") if s.strip()]
    if not texts:
        return "none", "No sample award text available for this program."

    boilerplate_count = sum(
        1 for t in texts
        if any(marker in t.upper() for marker in BOILERPLATE_MARKERS) or len(t) < 60
    )
    ratio = boilerplate_count / len(texts)

    if ratio >= 0.67:
        return "low", "Sample text is mostly boilerplate/placeholder (program name repeated or 'not available')."
    if ratio >= 0.34:
        return "medium", "Sample text is a mix of real descriptions and boilerplate."
    return "high", "Sample text appears to be real, descriptive award narratives."


def get_grant_precedents(cfda_code, org_type=None):
    """Step 2: precedent lookup against cfda_program_summary.parquet.

    Returns descriptive statistics about past winners of this program -
    NOT a prediction about any specific applicant. See module docstring.
    """
    df = _load_cfda_summary_cached()
    match = df[df["cfda_code"] == cfda_code]

    if match.empty:
        return {
            "found": False,
            "note": f"No award history found for CFDA {cfda_code} in the 10-year USAspending pull.",
        }

    row = match.iloc[0]
    confidence, confidence_note = _classify_precedent_confidence(row.get("sample_award_descriptions"))

    org_type_alignment_note = None
    if org_type:
        if _org_type_matches_entry(org_type, row.get("recipient_type_breakdown") or ""):
            org_type_alignment_note = (
                f"Your org type ('{org_type}') appears among this program's actual past recipients."
            )
        else:
            org_type_alignment_note = (
                f"Your org type ('{org_type}') was NOT found among this program's top past recipient "
                f"types - that doesn't mean ineligible, just less common historically."
            )

    return {
        "found": True,
        "cfda_code": row["cfda_code"],
        "program_title": row["cfda_title"],
        "prior_titles": row.get("prior_titles"),
        "awarding_agency": row["awarding_agency_name"],
        "award_count": int(row["award_count"]),
        "median_obligated_amount": float(row["median_obligated_amount"]) if pd.notna(row["median_obligated_amount"]) else None,
        "avg_obligated_amount": float(row["avg_obligated_amount"]) if pd.notna(row["avg_obligated_amount"]) else None,
        "recipient_type_breakdown": row["recipient_type_breakdown"],
        "administration_breakdown": row["administration_breakdown"],
        "sample_award_descriptions": row["sample_award_descriptions"],
        "precedent_confidence": confidence,
        "precedent_confidence_note": confidence_note,
        "org_type_alignment_note": org_type_alignment_note,
        "limitation": (
            "These are descriptive statistics about past award winners, not a prediction "
            "of whether any specific application will be funded."
        ),
    }


def check_prior_federal_awards(org_name):
    """Capacity signal: has this org received federal grants before?

    The "free win" from grant_readiness_score.md - no new data sourcing
    needed, just a lookup against USA.parquet by recipient name. Uses a
    case-insensitive substring match since recipient_name in USAspending
    isn't always an exact match to how an org refers to itself.

    IMPORTANT - substring matching is a real false-positive risk, not a
    hypothetical one: querying "Heart to Heart" matches "HEART TO HEART
    INTERNATIONAL INC" (a Kansas-based global health NGO), a completely
    different organization from the Florida-based Heart to Heart
    Foundation profiled elsewhere in this research. This function returns
    the distinct matched names explicitly so a caller can see and discard
    false matches - never trust award_count/total_obligated_amount without
    checking matched_recipient_names first.
    """
    if not org_name or not org_name.strip():
        # re.escape("") produces an empty regex pattern, which
        # str.contains() matches against EVERY row - found via robustness
        # testing (2026-06-26): calling this with an empty string silently
        # returned "has_prior_awards: True" with all 2,296,030 awards in
        # the 10-year pull, not "no org name given." A blank form field
        # should never look like the strongest possible capacity signal.
        return {
            "has_prior_awards": False,
            "matched_recipient_names": [],
            "note": "No org_name given - cannot check prior federal award history.",
        }

    df = _load_awards_for_track_record_cached()
    mask = df["recipient_name"].str.contains(re.escape(org_name), case=False, na=False)
    matches = df[mask]

    if matches.empty:
        return {
            "has_prior_awards": False,
            "matched_recipient_names": [],
            "note": f"No prior federal awards found for '{org_name}' in the 10-year pull. "
                    f"This doesn't rule out awards outside the window or under a different "
                    f"recorded name.",
        }

    matched_names = sorted(matches["recipient_name"].dropna().unique().tolist())

    return {
        "has_prior_awards": True,
        "matched_recipient_names": matched_names,
        "ambiguous_match": len(matched_names) > 1,
        "award_count": int(len(matches)),
        "total_obligated_amount": float(matches["total_obligated_amount"].sum()),
        "most_recent_award_date": str(matches["award_base_action_date"].max()),
        "programs": sorted(matches["cfda_numbers_and_titles"].dropna().unique().tolist())[:10],
        "note": "Verify matched_recipient_names is actually your org before trusting these numbers - "
                "substring matching can match unrelated organizations with similar names.",
    }


def get_country_precedent(cfda_code, country_code):
    """International counterpart to get_grant_precedents() - has the US
    funded THIS program's work in a SPECIFIC country before?

    get_grant_precedents() answers "who typically wins this program"
    nationally, which doesn't mean much for USAID/DFC programs (geography_
    scope="international" in grant_funding_programs.csv) - what matters
    there is whether a given country is a historical funding priority at
    all. Slices USA.parquet by exact place_of_performance_country_code
    (ISO 3-letter, e.g. "VEN", "HTI") instead of nationally.

    Exact-country match only, no regional rollup - a country with zero
    prior awards doesn't mean ineligible (USAID/DFC priorities shift with
    foreign policy faster than domestic CFDA programs do, and a country
    can become a new priority overnight after a crisis), just no direct
    historical evidence at this specific slice. Inventing a "similar
    region" stat here would overstate precision this data doesn't have -
    see the module's honesty constraint.
    """
    # place_of_performance_country_code in USA.parquet is always upper-case,
    # no surrounding whitespace - normalize the input to match, or a case/
    # whitespace difference (e.g. "ven" or " VEN ") silently returns
    # found=False instead of the real precedent. Found via robustness
    # testing (2026-06-26).
    country_code = str(country_code).strip().upper()
    df = _load_awards_for_country_precedent_cached()
    mask = (
        df["cfda_numbers_and_titles"].str.contains(re.escape(cfda_code), na=False)
        & (df["place_of_performance_country_code"] == country_code)
    )
    matches = df[mask]

    if matches.empty:
        return {
            "found": False,
            "cfda_code": cfda_code,
            "country_code": country_code,
            "note": f"No awards found under CFDA {cfda_code} with place of performance in "
                    f"'{country_code}' in the 10-year USAspending pull. Doesn't rule out future "
                    f"funding there - USAID/DFC country priorities shift with foreign policy and "
                    f"crisis response faster than domestic programs.",
        }

    descriptions = [d for d in matches["award_description"].dropna().tolist() if str(d).strip()][:5]

    return {
        "found": True,
        "cfda_code": cfda_code,
        "country_code": country_code,
        "award_count": int(len(matches)),
        "total_obligated_amount": float(matches["total_obligated_amount"].sum()),
        "median_obligated_amount": float(matches["total_obligated_amount"].median()),
        "recipient_business_type_breakdown": matches["recipient_business_type_description"].value_counts().head(5).to_dict(),
        "date_range": f"{matches['award_base_action_date'].min()} to {matches['award_base_action_date'].max()}",
        "sample_award_descriptions": descriptions,
        "limitation": "Descriptive statistics about past awards in this country under this program, "
                      "not a prediction of future funding availability for any specific country or "
                      "crisis - see module docstring's honesty constraint.",
    }


def _classify_funding_mechanism(title):
    """NOFO vs APS vs RFA vs BAA - which kind of solicitation is this?

    Matters because they behave completely differently: a NOFO has a fixed
    near-term deadline; an APS (Annual Program Statement) is a standing,
    often year-round "call to action" for rolling concept papers with no
    real deadline pressure (confirmed live, 2026-06-26: real APS postings
    have closeDate values like "01/01/2099"); an RFA is issued in response
    to an APS; a BAA is open-ended innovative-work solicitation. Grants.gov's
    API has no structured field for this - every hit's `docType` is just
    `"synopsis"` regardless of mechanism (confirmed by inspecting real API
    responses) - so this is a title-text heuristic, not a real classifier.
    Default "nofo_or_other" covers ordinary NOFOs/RFPs and anything that
    doesn't match a known pattern.
    """
    upper = str(title or "").upper()
    if "ANNUAL PROGRAM STATEMENT" in upper or re.search(r"\bAPS\b", upper):
        return "aps"
    if "BROAD AGENCY ANNOUNCEMENT" in upper or re.search(r"\bBAA\b", upper):
        return "baa"
    if "REQUEST FOR APPLICATIONS" in upper or re.search(r"\bRFA\b", upper):
        return "rfa"
    return "nofo_or_other"


def check_open_opportunity(cfda_code, live_fallback=True):
    """Is there a currently-open NOFO for this program right now?

    Pattern B / Pattern A split, aligned with the project's existing live-
    collector framework (live_pipeline_program.md's NSS Shelters precedent -
    "what's open right now" has near-zero historical-retention value, so
    a live API facade is the right primary pattern, with a periodic static
    snapshot for cheap cross-reference/aggregate use):

    1. First checks the pre-pulled grants_gov_open_opportunities/latest.csv
       snapshot (Pattern B - cheap, no network call, but only covers the
       8 disaster/resilience/green-infra keywords it was pulled with).
    2. If the snapshot shows no match and live_fallback=True, falls back to
       a live, exact-CFDA query against Grants.gov (Pattern A -
       find_open_opportunities_live's sibling, using the API's dedicated
       `cfda` filter rather than a keyword guess) - this is the
       authoritative check, not a guess, and catches programs outside the
       snapshot's keyword set.

    Set live_fallback=False to stay snapshot-only (e.g. for bulk scoring
    runs where many programs are checked and you don't want N network
    calls) - the result will say checked_live=False so the caller knows
    "not found" might just mean "not in the narrow snapshot."
    """
    df = _load_open_opportunities_cached()
    snapshot_matches = (
        df[df["cfda_numbers"].str.contains(re.escape(cfda_code), na=False)]
        if df is not None else pd.DataFrame()
    )

    if not snapshot_matches.empty:
        rows = snapshot_matches.to_dict("records")
        return {
            "checked": True,
            "checked_live": False,
            "is_currently_open": True,
            "opportunities": [
                {
                    "title": r["title"], "agency": r["agency"], "close_date": r["close_date"],
                    "opportunity_number": r["opportunity_number"],
                    "funding_mechanism": _classify_funding_mechanism(r["title"]),
                }
                for r in rows
            ],
        }

    if not live_fallback:
        return {
            "checked": True,
            "checked_live": False,
            "is_currently_open": False,
            "note": f"No open NOFO found for CFDA {cfda_code} in the static snapshot "
                    f"(8-keyword coverage only). live_fallback was off - this could be a "
                    f"false negative, not a confirmed absence.",
        }

    try:
        response = RateLimitedFetcher(min_interval=1.0).post(
            "https://api.grants.gov/v1/api/search2",
            json={"cfda": cfda_code, "rows": 5, "oppStatuses": "posted"},
        )
        hits = response.json().get("data", {}).get("oppHits", [])
    except Exception as e:
        return {
            "checked": True,
            "checked_live": False,
            "is_currently_open": False,
            "note": f"Snapshot had no match and the live fallback call failed ({e}) - "
                    f"treat as unknown, not confirmed closed.",
        }

    if not hits:
        return {
            "checked": True,
            "checked_live": True,
            "is_currently_open": False,
            "note": f"Confirmed live: no open NOFO for CFDA {cfda_code} right now.",
        }

    return {
        "checked": True,
        "checked_live": True,
        "is_currently_open": True,
        "opportunities": [
            {
                "title": h.get("title"), "agency": h.get("agency"), "close_date": h.get("closeDate"),
                "opportunity_number": h.get("number"),
                "funding_mechanism": _classify_funding_mechanism(h.get("title")),
            }
            for h in hits
        ],
    }


def find_open_opportunities_live(keyword, max_results=10):
    """Discovery mode: "I work in X, what grants are available right now?"

    Unlike check_open_opportunity (which only sees the pre-pulled 8-keyword
    disaster/resilience snapshot), this queries Grants.gov's search2 API
    live, for ANY keyword - "education," "agriculture," whatever the
    caller's actual work area is. No pre-built program catalog needed; this
    is pure discovery over what's open right now.

    Uses the same shared rate limiter (1 req/sec) as the bulk downloader -
    see county-map-private/data_converters/utilities/rate_limited_fetcher.py.
    """
    fetcher = RateLimitedFetcher(min_interval=1.0)
    response = fetcher.post(
        "https://api.grants.gov/v1/api/search2",
        json={"keyword": keyword, "rows": max_results, "startRecordNum": 0, "oppStatuses": "posted"},
    )
    data = response.json().get("data", {})
    hits = data.get("oppHits", [])

    return {
        "keyword": keyword,
        "total_hits": data.get("hitCount", 0),
        "showing": len(hits),
        "opportunities": [
            {
                "title": h.get("title"),
                "agency": h.get("agency"),
                "opportunity_number": h.get("number"),
                "open_date": h.get("openDate"),
                "close_date": h.get("closeDate"),
                "cfda_numbers": h.get("cfdaList") or [],
                "funding_mechanism": _classify_funding_mechanism(h.get("title")),
            }
            for h in hits
        ],
    }


def get_grant_writing_template(program_id):
    """Which narrative format/sections apply to this program.

    Looks up grant_writing_templates.csv. Only NSF and FEMA BRIC/HMGP are
    independently agency-verified (agency_verified=TRUE); USFS programs are
    inferred from one verified sibling (Wood Innovations) applied across
    the rest of the agency family; everything else falls back to the
    generic nonprofit-sector convention, which is NOT verified against any
    specific program's actual NOFO. The `agency_verified` flag in the
    return value must be surfaced to the end user, not hidden - a templated
    answer that looks equally confident whether verified or guessed would
    be actively misleading.
    """
    templates = _load_templates_cached()

    for _, row in templates.iterrows():
        if row["applies_to_program_ids"] == "default":
            continue
        if program_id in _split_pipe(row["applies_to_program_ids"]):
            return {
                "template_id": row["template_id"],
                "agency_verified": row["agency_verified"].upper() == "TRUE",
                "base_forms": row["base_forms"],
                "narrative_sections": _split_outside_parens(row["narrative_sections"]),
                "page_limits": row["page_limits"],
                "special_requirements": row["special_requirements"],
                "source_url": row["source_url"],
            }

    fallback = templates[templates["applies_to_program_ids"] == "default"].iloc[0]
    return {
        "template_id": fallback["template_id"],
        "agency_verified": False,
        "base_forms": fallback["base_forms"],
        "narrative_sections": _split_outside_parens(fallback["narrative_sections"]),
        "page_limits": fallback["page_limits"],
        "special_requirements": fallback["special_requirements"],
        "source_url": fallback["source_url"],
        "note": f"No agency-specific template researched yet for '{program_id}' - "
                f"using the generic nonprofit-sector convention. Verify against the "
                f"actual NOFO before relying on this.",
    }


def _extract_checkable_terms(section_text):
    """Break a narrative_sections entry into individually checkable terms.

    e.g. "Project Summary (Overview; Intellectual Merit; Broader Impacts)"
    -> ["Project Summary", "Overview", "Intellectual Merit", "Broader Impacts"]

    Parenthetical sub-items matter on their own - NSF's "Broader Impacts" is
    a separately graded, separately mandatory sub-requirement, not just
    descriptive detail about "Project Summary."
    """
    text = section_text.strip()
    paren_match = re.search(r"\(([^)]*)\)", text)
    head = re.sub(r"\s*\([^)]*\)\s*", "", text).strip()
    terms = [head] if head else []
    if paren_match:
        terms.extend(t.strip() for t in paren_match.group(1).split(";") if t.strip())
    return [t for t in terms if t]


def score_proposal_structure(draft_text, program_id):
    """Layer 3a: does a draft proposal cover the sections the agency
    actually asks for?

    This is the realistic version of "compare against winning proposals" -
    full submitted-proposal text isn't available in bulk for any agency in
    our vertical (researched 2026-06-25, see USA grant research.md), but
    the agency's own required-sections list IS known for NSF/FEMA BRIC/HMGP
    (verified) and USFS Wood Innovations (verified, inferred for siblings).
    Ranking a draft against the actual required structure is the
    next-best, broadly-buildable thing: "did you cover what they asked
    for," not "does this read like a winner."

    Simple literal-phrase presence check, not NLP - a missing section is
    a missing section regardless of how it's phrased, but this WILL miss
    a section that's present under different wording. Treat misses as
    "didn't find it," not "definitely absent."
    """
    template = get_grant_writing_template(program_id)
    draft_lower = draft_text.lower()

    checklist = []
    for section in template["narrative_sections"]:
        for term in _extract_checkable_terms(section):
            present = term.lower() in draft_lower
            checklist.append({
                "term": term,
                "from_section": section,
                "present": present,
                "action_item": None if present else f"Add or clearly label a section covering: {term}",
            })

    missing = [c for c in checklist if not c["present"]]
    present_count = len(checklist) - len(missing)

    # A real numeric score of 0 reads as "this is a bad proposal." But 0 of
    # N matched terms (found via the Venezuela Provost-memo validation,
    # 2026-06-26) is much more often a sign that the input was never meant
    # to BE a grant-application draft at all - an internal advocacy memo, a
    # cover letter, a project summary for a different audience - than that
    # someone wrote a proposal missing literally every section. Treating
    # those two cases identically (a misleadingly confident failing grade)
    # is worse than not scoring at all, so this case gets its own signal
    # instead of a number.
    wrong_document_type_warning = None
    if checklist and present_count == 0:
        structure_score = None
        wrong_document_type_warning = (
            f"0 of {len(checklist)} expected sections for this program's template were found "
            f"anywhere in this text. That's a strong signal this document isn't meant to BE a "
            f"grant-application draft (e.g. an internal advocacy memo, a cover letter, a project "
            f"summary for a different audience) rather than a real structural failure - "
            f"score_proposal_structure assumes the input IS a submission draft. Confirm that "
            f"before treating the missing-sections checklist below as a proposal-quality issue."
        )
    else:
        structure_score = round(100 * present_count / len(checklist)) if checklist else None

    mandatory_note = None
    if "broader impacts" in str(template.get("special_requirements", "")).lower():
        bi_present = any(c["term"].lower() == "broader impacts" and c["present"] for c in checklist)
        if not bi_present:
            mandatory_note = (
                "NSF requires 'Broader Impacts' as its OWN labeled section in both the Project "
                "Summary and Project Description - a common rejection reason when omitted. "
                "Not finding it in your draft is a higher-severity miss than the other sections."
            )

    return {
        "program_id": program_id,
        "template_id": template["template_id"],
        "agency_verified": template["agency_verified"],
        "structure_score": structure_score,
        "checklist": checklist,
        "missing_count": len(missing),
        "mandatory_note": mandatory_note,
        "wrong_document_type_warning": wrong_document_type_warning,
        "limitation": "Literal-phrase presence check, not semantic understanding - a section present "
                      "under different wording will show as missing here. Verify misses by eye before "
                      "treating them as confirmed gaps." + (
                          "" if template["agency_verified"] else
                          " Also note: this template itself is unverified/inferred for this program - "
                          "treat the whole checklist as a starting point, not ground truth."
                      ),
    }


def find_similar_precedent_text(draft_text, source="nsf", keyword=None, top_n=3):
    """Layer 3b: content comparison against real funded abstracts.

    Only meaningfully available for NSF and NIH (nsf_awards/USA.parquet,
    nih_reporter_projects/USA.parquet) - the two sources in this project
    with large-scale REAL submitted-text (abstracts, not just award
    descriptions). FEMA/USFS/USDA/HUD/ARC have no comparable corpus
    (researched 2026-06-25) - calling this with source outside nsf/nih
    will raise, not silently return nothing.

    Uses plain word-overlap similarity (Jaccard on significant words), not
    embeddings/LLM - deterministic, no model call, consistent with the
    rest of this module. This is a "find a similar real example to read,"
    not a quality judgment - the most similar abstract isn't necessarily
    the strongest one.
    """
    if source == "nsf":
        path = PROJECT_ROOT / "county-map-data" / "countries" / "USA" / "nsf_awards" / "USA.parquet"
        text_col = "abstract_text"
        keyword_col = "matched_keywords"
        title_col = "title"
    elif source == "nih":
        path = PROJECT_ROOT / "county-map-data" / "countries" / "USA" / "nih_reporter_projects" / "USA.parquet"
        text_col = "abstract_text"
        keyword_col = "matched_keywords"
        title_col = "project_title"
    else:
        raise ValueError(
            f"source must be 'nsf' or 'nih' - no comparable real-text corpus exists for '{source}' "
            f"(researched 2026-06-25, see USA grant research.md)."
        )

    df = pd.read_parquet(path, columns=[text_col, keyword_col, title_col])
    df = df[df[text_col].notna() & (df[text_col].str.len() > 0)]

    if keyword:
        df = df[df[keyword_col].str.contains(re.escape(keyword), case=False, na=False)]
    if df.empty:
        return {"found": False, "note": f"No {source} abstracts matched keyword '{keyword}'."}

    draft_words = set(re.findall(r"[a-z]{4,}", draft_text.lower()))

    def jaccard(text):
        words = set(re.findall(r"[a-z]{4,}", str(text).lower()))
        if not words or not draft_words:
            return 0.0
        return len(draft_words & words) / len(draft_words | words)

    df = df.copy()
    df["_similarity"] = df[text_col].apply(jaccard)
    top = df.sort_values("_similarity", ascending=False).head(top_n)

    return {
        "found": True,
        "source": source,
        "candidates_searched": len(df),
        "matches": [
            {"title": row[title_col], "similarity": round(row["_similarity"], 3), "abstract_text": row[text_col]}
            for _, row in top.iterrows()
        ],
        "limitation": "Word-overlap similarity, not a quality judgment - the most similar real abstract "
                      "is a reading reference for tone/scope/structure, not necessarily the strongest example.",
    }


def _sub(points, max_points, status, note, action_item=None):
    """One sub-factor result. action_item is None when nothing needs doing."""
    return {"points": points, "max": max_points, "status": status, "note": note, "action_item": action_item}


def _factor_total(*subs):
    return sum(s["points"] for s in subs)


# --- 1. Recipient-type alignment (30 = 20 rank + 10 concentration) ---

def _sub_recipient_rank(recipient_type_breakdown, org_type):
    max_points = 20
    if not recipient_type_breakdown:
        return _sub(max_points // 2, max_points, "unknown", "No recipient-type breakdown available.")

    entries = [e.strip() for e in str(recipient_type_breakdown).split(";") if e.strip()]

    for rank, entry in enumerate(entries):
        if _org_type_matches_entry(org_type, entry):
            points = [max_points, int(max_points * 0.67), int(max_points * 0.4)]
            score = points[rank] if rank < len(points) else int(max_points * 0.2)
            return _sub(score, max_points, "ok", f"Org type ranked #{rank + 1} among past recipients.")

    return _sub(
        int(max_points * 0.15), max_points, "weak",
        "Org type not in this program's top 3 past recipient types.",
        action_item="Org types like yours rarely show up as direct recipients here - "
                    "consider whether a different program or a co-applicant structure fits better.",
    )


def _sub_recipient_concentration(recipient_type_breakdown, org_type):
    max_points = 10
    if not recipient_type_breakdown:
        return _sub(max_points // 2, max_points, "unknown", "No recipient-type breakdown available.")

    entries = [e.strip() for e in str(recipient_type_breakdown).split(";") if e.strip()]
    counts = [int(m.group(1)) for e in entries if (m := re.search(r"\((\d+)\)", e))]
    if not counts:
        return _sub(max_points // 2, max_points, "unknown", "Could not parse recipient counts.")

    top_share = counts[0] / sum(counts)
    top_is_org_type = bool(entries) and _org_type_matches_entry(org_type, entries[0])

    if top_is_org_type or top_share < 0.6:
        return _sub(max_points, max_points, "ok", f"Recipient mix is reasonably diverse (top type holds {top_share:.0%}).")

    dominant_type = re.sub(r"\s*\(\d+\)\s*$", "", entries[0])
    return _sub(
        int(max_points * 0.3), max_points, "weak",
        f"This program's awards are concentrated among '{dominant_type}' ({top_share:.0%} of top-3 recipients).",
        action_item=f"Consider partnering with a '{dominant_type.lower()}' as co-applicant - "
                    f"this program's funding is concentrated there, not spread evenly.",
    )


# --- 2. Geographic alignment (20 = 10 recipient location + 10 place of performance) ---

def _geo_check_one(geography_scope, loc_id):
    """Check a single loc_id against geography_scope. Returns (status, note)."""
    if geography_scope == "national":
        return "ok", "National scope - no geographic restriction."
    if geography_scope in ("international", "international_frontline_communities"):
        return "unknown", "International scope - domestic loc_id check doesn't apply."

    allowed_states = GEOGRAPHY_STATE_MAP.get(geography_scope)
    if allowed_states is None:
        return "unknown", f"Unrecognized geography_scope '{geography_scope}' - can't verify automatically."
    if not loc_id:
        return "unknown", "No loc_id given for this check."

    state = _loc_id_state(loc_id)
    if state in allowed_states:
        return "ok", f"{state} is within this program's geographic scope."
    return "mismatch", f"{state} does not appear to be within this program's geographic scope ('{geography_scope}')."


def _sub_geography(geography_scope, loc_id, label):
    max_points = 10
    status, note = _geo_check_one(geography_scope, loc_id)
    if status == "ok":
        return _sub(max_points, max_points, status, note)
    if status == "unknown":
        return _sub(
            max_points // 2, max_points, status, note,
            action_item=f"Confirm whether this program's geography actually covers your {label}." if loc_id is None else None,
        )
    return _sub(
        0, max_points, status, note,
        action_item=f"Double-check eligibility - your {label} may fall outside this program's funded region.",
    )


# --- 3. Award & scope alignment (20 = 12 size + 8 duration) ---

def _sub_geography_country(cfda_code, country_code):
    """International counterpart to _sub_geography() - used in place of
    the place-of-performance check when geography_scope is "international"
    and a target_country_code was actually given. Without a country code,
    score_and_rank_programs falls back to _sub_geography's existing
    "unknown, can't verify" behavior - this only fires when there's an
    actual country to check precedent against.
    """
    max_points = 10
    precedent = get_country_precedent(cfda_code, country_code)
    if not precedent["found"]:
        return _sub(
            int(max_points * 0.4), max_points, "weak",
            f"No prior awards found under this program with place of performance in "
            f"{country_code} in the 10-year pull - doesn't rule it out, just no direct precedent.",
            action_item=f"No historical USAID/DFC award precedent for {country_code} under this "
                        f"program - confirm with the agency whether {country_code} is a current "
                        f"funding priority before investing heavily in this pathway.",
        )
    return _sub(
        max_points, max_points, "ok",
        f"Confirmed: {precedent['award_count']} prior award(s) under this program with place of "
        f"performance in {country_code} (median ${precedent['median_obligated_amount']:,.0f}).",
    )


def _international_only_intent(target_country_code, recipient_loc_id, place_of_performance_loc_id):
    """True when the caller has signaled a purely-international project (a
    target_country_code) with no domestic anchor at all (no recipient_loc_id
    or place_of_performance_loc_id). Used to flag domestic-only
    (geography_scope="national") programs as a likely mismatch rather than
    "ok, no restriction" - "national" means "anywhere in the US," which is
    not the same as "fits a project with no US presence."

    Deliberately does NOT exclude national-scope programs when a domestic
    loc_id IS also given alongside a target_country_code (a hybrid US+
    international project, e.g. a university with both a domestic and a
    foreign component) - only fires when there's no domestic signal
    whatsoever, mirroring the international-scope exclusion already added
    for confirmed-domestic-only projects.
    """
    return bool(target_country_code) and not recipient_loc_id and not place_of_performance_loc_id


def _sub_award_size(median_obligated_amount, target_award_amount):
    max_points = 12
    if target_award_amount is None:
        return _sub(
            max_points // 2, max_points, "unknown", "No target award amount given.",
            action_item="Provide a target ask amount to score this factor.",
        )
    if median_obligated_amount in (None, 0):
        return _sub(max_points // 2, max_points, "unknown", "No historical award-size data for this program.")

    ratio = target_award_amount / median_obligated_amount
    if 0.5 <= ratio <= 2.0:
        return _sub(max_points, max_points, "ok", f"Ask is within typical range ({ratio:.2f}x the median).")
    if 0.25 <= ratio <= 4.0:
        direction = "above" if ratio > 1 else "below"
        return _sub(
            int(max_points * 0.6), max_points, "weak",
            f"Ask is {ratio:.2f}x the median - somewhat {direction} the typical range.",
            action_item=f"Consider adjusting your ask closer to the typical award size for this program "
                        f"(median: ${median_obligated_amount:,.0f}).",
        )
    direction = "above" if ratio > 1 else "below"
    return _sub(
        int(max_points * 0.2), max_points, "off",
        f"Ask is {ratio:.2f}x the median - far {direction} the typical range.",
        action_item=f"Your ask is far outside this program's typical award size (median: "
                    f"${median_obligated_amount:,.0f}) - consider rescoping or phasing the request.",
    )


def _sub_project_duration(median_project_length_days, target_project_length_days):
    max_points = 8
    if target_project_length_days is None:
        return _sub(
            max_points // 2, max_points, "unknown", "No target project length given.",
            action_item="Provide a target project length (days) to score this factor.",
        )
    if median_project_length_days in (None, 0) or pd.isna(median_project_length_days):
        return _sub(max_points // 2, max_points, "unknown", "No historical project-length data for this program.")

    ratio = target_project_length_days / median_project_length_days
    if 0.5 <= ratio <= 2.0:
        return _sub(max_points, max_points, "ok", f"Proposed length is within typical range ({ratio:.2f}x the median).")
    direction = "longer" if ratio > 1 else "shorter"
    return _sub(
        int(max_points * 0.4), max_points, "weak",
        f"Proposed length is {ratio:.2f}x the median - notably {direction} than typical.",
        action_item=f"Typical funded projects under this program run ~{median_project_length_days:.0f} days - "
                    f"consider adjusting your timeline.",
    )


# --- 4. Capacity signals (30 = 10 match funding + 10 government partner + 10 track record) ---

def _sub_match_funding(requires_match_status, has_match_funding):
    """requires_match_status is tri-state (True/False/None=unknown) - an
    unknown requirement gets a reduced score and an explicit action item,
    never the same "ok, no blocker" treatment as a confirmed False. See
    tristate.py's docstring for the real bug this replaces."""
    max_points = 10
    if requires_match_status is False:
        return _sub(max_points, max_points, "ok", "No match funding required.")
    if requires_match_status is None:
        return _sub(
            max_points // 2, max_points, "unknown",
            "Whether match funding is required is unconfirmed for this program - not yet "
            "researched against the actual program terms.",
            action_item="Confirm match-funding requirements directly with the agency before "
                        "relying on this score.",
        )
    if has_match_funding:
        return _sub(max_points, max_points, "ok", "Match funding required and confirmed available.")
    return _sub(
        0, max_points, "blocked", "Match funding is required and not yet confirmed available.",
        action_item="Secure match funding before applying - this program requires it.",
    )


def _sub_government_partner(requires_intermediary_status, has_government_partner):
    """Same tri-state treatment as _sub_match_funding above."""
    max_points = 10
    if requires_intermediary_status is False:
        return _sub(max_points, max_points, "ok", "No government co-applicant required.")
    if requires_intermediary_status is None:
        return _sub(
            max_points // 2, max_points, "unknown",
            "Whether a government co-applicant is required is unconfirmed for this program - "
            "not yet researched against the actual program terms.",
            action_item="Confirm government-intermediary requirements directly with the agency "
                        "before relying on this score.",
        )
    if has_government_partner:
        return _sub(max_points, max_points, "ok", "Government co-applicant required and already in place.")
    return _sub(
        0, max_points, "blocked", "Requires a state/local/tribal government co-applicant, not yet confirmed.",
        action_item="Find a state/local/tribal government willing to apply or sub-apply on your behalf.",
    )


def _sub_track_record(org_name):
    max_points = 10
    if not org_name:
        return _sub(
            max_points // 2, max_points, "unknown", "No org name given.",
            action_item="Provide your org's legal name to check prior federal award history.",
        )

    result = check_prior_federal_awards(org_name)
    if result.get("ambiguous_match"):
        return _sub(
            max_points // 2, max_points, "unknown",
            f"Multiple distinct orgs matched '{org_name}' - results ambiguous.",
            action_item=f"Verify which of {result['matched_recipient_names']} is actually your organization.",
        )
    if result["has_prior_awards"]:
        return _sub(max_points, max_points, "ok", f"Found {result['award_count']} prior federal award(s) on record.")
    return _sub(
        int(max_points * 0.5), max_points, "weak",
        "No prior federal award history found - doesn't disqualify you, but first-time applicants face a steeper climb.",
        action_item="If you don't already have one, register in SAM.gov and obtain a UEI before applying - "
                    "required for any federal award regardless of history.",
    )


def score_and_rank_programs(
    org_type,
    sector_tags=None,
    recipient_loc_id=None,
    place_of_performance_loc_id=None,
    has_government_partner=False,
    has_match_funding=False,
    target_award_amount=None,
    target_project_length_days=None,
    org_name=None,
    target_country_code=None,
    top_n=5,
    live_opportunity_fallback=True,
):
    """Composite 0-100 Grant Readiness Score, ranked, top N, broken into
    12 sub-factors across 4 weighted categories so each one carries a
    specific, actionable status rather than one blended note.

    target_country_code: ISO 3-letter country code (e.g. "VEN", "HTI") for
        international (geography_scope="international") programs - swaps
        the place-of-performance geography sub-factor from "unknown, no
        loc_id check applies" to a real country-level precedent check via
        get_country_precedent(). Irrelevant for domestic programs, and a
        no-op if omitted - existing domestic callers are unaffected.
    live_opportunity_fallback: whether check_open_opportunity() is allowed
        to make a live Grants.gov API call when the local snapshot misses.
        Keep this False in deterministic tests/offline runs so "scoring"
        stays purely local-data-backed instead of hanging on network state.

    NOT a win probability - see module docstring and
    grant_readiness_score.md's "core honesty constraint". This is a fit
    score against the historical winner profile, with an attached
    precedent_confidence tag (high/medium/low/none) that should be shown
    alongside the score, not folded into it.

    Returns {"top_matches": [...], "assistance_resources": [...]} - rows
    with funds_what == "application_assistance" (free help-applying
    resources like RICCE, Local Infrastructure Hub, Tribal Resource
    Center) are listed separately, not scored/ranked alongside actual
    funding programs - "fit against past winners" doesn't make sense for
    something you contact rather than apply to.
    """
    matches = match_grant_programs(
        org_type=org_type,
        sector_tags=sector_tags,
        recipient_loc_id=recipient_loc_id,
        place_of_performance_loc_id=place_of_performance_loc_id,
        has_government_partner=has_government_partner,
        has_match_funding=has_match_funding,
        target_country_code=target_country_code,
    )

    programs_df = load_programs()
    scored = []
    assistance_resources = []

    # Doesn't vary per matched program - compute once, not once per match
    # (was previously rescanning the awards parquet for the same org_name
    # on every single matched program).
    track_record = _sub_track_record(org_name)

    for m in matches:
        if m["funds_what"] == "application_assistance":
            # Not a funding source to score "fit against past winners" against -
            # it's a free help-you-apply resource (e.g. Local Infrastructure Hub,
            # RICCE, Tribal Resource Center). List separately, don't rank it
            # alongside actual funding programs.
            assistance_resources.append({
                "program_id": m["program_id"],
                "program_name": m["program_name"],
                "agency_or_funder": m["agency_or_funder"],
                "notes": m["notes"],
                "source_url": m["source_url"],
            })
            continue

        program_row = programs_df[programs_df["program_id"] == m["program_id"]].iloc[0]
        requires_intermediary_status = parse_tristate(program_row["requires_government_intermediary"])
        requires_match_status = parse_tristate(program_row["requires_match_funding"])
        geography_scope = program_row["geography_scope"]

        first_cfda = None
        if m["cfda_number"]:
            first_cfda = _split_pipe(m["cfda_number"])[0] if "|" in str(m["cfda_number"]) else m["cfda_number"]

        precedent = get_grant_precedents(first_cfda, org_type=org_type) if first_cfda else None
        open_opportunity = (
            check_open_opportunity(first_cfda, live_fallback=live_opportunity_fallback)
            if first_cfda else {"checked": False, "note": "No CFDA number on this program row."}
        )

        found_precedent = bool(precedent and precedent.get("found"))
        recipient_breakdown = precedent.get("recipient_type_breakdown") if found_precedent else None
        median_amount = precedent.get("median_obligated_amount") if found_precedent else None
        precedent_confidence = precedent.get("precedent_confidence") if found_precedent else "none"

        median_project_length = None
        if found_precedent:
            cfda_df = _load_cfda_summary_cached()
            cfda_match = cfda_df[cfda_df["cfda_code"] == precedent["cfda_code"]]
            if not cfda_match.empty:
                median_project_length = cfda_match.iloc[0]["median_project_length_days"]

        recipient_rank = _sub_recipient_rank(recipient_breakdown, org_type)
        recipient_concentration = _sub_recipient_concentration(recipient_breakdown, org_type)
        geo_recipient = _sub_geography(geography_scope, recipient_loc_id, "organization's home location")
        if (
            geography_scope in ("international", "international_frontline_communities")
            and target_country_code and first_cfda
        ):
            geo_pop = _sub_geography_country(first_cfda, target_country_code)
        else:
            geo_pop = _sub_geography(geography_scope, place_of_performance_loc_id, "project's place of performance")

        if geography_scope == "national" and _international_only_intent(
            target_country_code, recipient_loc_id, place_of_performance_loc_id
        ):
            # "national" means "anywhere in the US," not "fits a project
            # with no US presence" - a project that's only signaled an
            # international target_country_code and no domestic loc_id at
            # all is very unlikely to actually be eligible here, even
            # though sector tags alone can match. Real noise filter, found
            # via a real bad suggestion (CDFI Equitable Recovery Program
            # surfacing for a Venezuela-only nonprofit query).
            mismatch_note = (
                f"This program only funds domestic US work ('national' scope) - it doesn't fit "
                f"a project with no US-based presence indicated and a target country of "
                f"{target_country_code}. Likely noise, not a real lead."
            )
            geo_recipient = _sub(0, 10, "mismatch", mismatch_note, action_item="Likely not a real fit - this program doesn't fund international-only work.")
            geo_pop = _sub(0, 10, "mismatch", mismatch_note)

        size = _sub_award_size(median_amount, target_award_amount)
        duration = _sub_project_duration(median_project_length, target_project_length_days)
        match_funding = _sub_match_funding(requires_match_status, has_match_funding)
        gov_partner = _sub_government_partner(requires_intermediary_status, has_government_partner)

        categories = {
            "recipient_type_alignment": {
                "max": WEIGHT_RECIPIENT_TYPE,
                "sub_factors": {"historical_rank": recipient_rank, "recipient_concentration": recipient_concentration},
            },
            "geographic_alignment": {
                "max": WEIGHT_GEOGRAPHY,
                "sub_factors": {"recipient_location": geo_recipient, "place_of_performance": geo_pop},
            },
            "award_and_scope_alignment": {
                "max": WEIGHT_AWARD_SIZE,
                "sub_factors": {"award_size": size, "project_duration": duration},
            },
            "capacity_signals": {
                "max": WEIGHT_CAPACITY,
                "sub_factors": {"match_funding": match_funding, "government_partner": gov_partner, "track_record": track_record},
            },
        }
        for cat in categories.values():
            cat["points"] = _factor_total(*cat["sub_factors"].values())

        action_items = [
            sub["action_item"]
            for cat in categories.values()
            for sub in cat["sub_factors"].values()
            if sub["action_item"]
        ]

        total = sum(cat["points"] for cat in categories.values())

        if open_opportunity.get("checked") and not open_opportunity.get("is_currently_open"):
            if open_opportunity.get("checked_live"):
                action_items.append(
                    "Confirmed live on Grants.gov: no open NOFO for this program right now - "
                    "watch for the next funding cycle."
                )
            else:
                action_items.append(
                    "No open NOFO found in the static snapshot for this program, and the "
                    "live confirmation check didn't run or failed - verify directly on Grants.gov."
                )

        scored.append({
            "program_id": m["program_id"],
            "program_name": m["program_name"],
            "agency_or_funder": m["agency_or_funder"],
            "source_url": m["source_url"],
            "score": total,
            "precedent_confidence": precedent_confidence,
            "open_opportunity": open_opportunity,
            "score_breakdown": categories,
            "action_items": action_items + [f"More information: {m['source_url']}"],
            "directly_eligible": m["directly_eligible"],
            "blockers": m["blockers"],
            "unknown_requirements": m["unknown_requirements"],
            "eligibility_confidence": m["eligibility_confidence"],
            "pathway_note": m["pathway_note"],
            "writing_template": get_grant_writing_template(m["program_id"]),
            "limitation": "Score reflects fit against past winners, not a probability of winning. "
                          "See grant_readiness_score.md for why.",
        })

    scored.sort(key=lambda r: r["score"], reverse=True)
    # top_n < 1 (e.g. a stray -1) would silently slice from the END of the
    # list via Python's negative-index semantics (scored[:-1] = "all but
    # the last") instead of erroring or returning nothing - found via
    # robustness testing (2026-06-26). Clamp rather than raise, consistent
    # with this module's graceful-degradation style elsewhere.
    safe_top_n = max(1, top_n)
    return {"top_matches": scored[:safe_top_n], "assistance_resources": assistance_resources}


def build_memo_talking_points(scored_result, top_n=5):
    """Pipeline Phase 2 (proposal development - internal buy-in): turn
    score_and_rank_programs()'s output into memo-ready talking points.

    Born directly from the Venezuela earthquake scenario (2026-06-26) -
    asked to suggest improvements to a real Provost-facing advocacy memo,
    I hand-synthesized "name the specific funding targets instead of vague
    'federal and civilian funding'" from a score_and_rank_programs() call.
    That synthesis is mechanical enough to be a real function instead of
    something re-derived by an LLM every time: take the ranked matches,
    produce named-program bullets (score, agency, blockers, URL) and a
    ready-to-paste summary paragraph.

    Does NOT draft the whole memo - that's still a human/LLM judgment call
    about framing, audience, and what else belongs in it. This only
    produces the factual funding-target content block, deterministically,
    so it doesn't have to be re-derived or guessed at by whoever writes
    the memo next.
    """
    top = scored_result.get("top_matches", [])[:top_n]
    if not top:
        return {
            "found": False,
            "note": "No matching programs to build talking points from - run "
                    "score_and_rank_programs() first and check it returned matches.",
        }

    bullets = []
    for r in top:
        blocker_note = f" Blocked: {'; '.join(r['blockers'])}." if r["blockers"] else ""
        oo = r.get("open_opportunity") or {}
        if oo.get("is_currently_open") and oo.get("opportunities"):
            mechanism = oo["opportunities"][0].get("funding_mechanism", "nofo_or_other")
            open_note = f" Currently open ({mechanism})."
        elif oo.get("checked_live"):
            open_note = " No live solicitation posted right now."
        else:
            open_note = ""

        headline = (
            f"{r['program_name']} ({r['agency_or_funder']}) - {r['score']}/100 fit, "
            f"{r['precedent_confidence']} precedent.{blocker_note}{open_note}"
        )
        bullets.append({
            "program_id": r["program_id"],
            "program_name": r["program_name"],
            "agency_or_funder": r["agency_or_funder"],
            "score": r["score"],
            "precedent_confidence": r["precedent_confidence"],
            "blockers": r["blockers"],
            "source_url": r["source_url"],
            "headline": headline,
        })

    best = bullets[0]
    summary = (
        f"{len(bullets)} funding target(s) identified, led by {best['program_name']} "
        f"({best['agency_or_funder']}, {best['score']}/100 fit)."
    )
    memo_paragraph = summary + " " + " ".join(b["headline"] for b in bullets)

    assistance_note = None
    assistance = scored_result.get("assistance_resources") or []
    if assistance:
        names = ", ".join(a["program_name"] for a in assistance)
        assistance_note = (
            f"Also available (free application-assistance, not funding sources): {names}."
        )

    return {
        "found": True,
        "summary": summary,
        "talking_points": bullets,
        "memo_paragraph": memo_paragraph,
        "assistance_note": assistance_note,
        "limitation": "These are fit-against-past-winners scores, not approval odds - phrase the "
                      "memo as 'identified funding targets,' not 'will receive funding.' See the "
                      "honesty constraint in the module docstring.",
    }


# Standard SF-424A (Budget Information - Non-Construction Programs) line-item
# categories, per the actual federal form every Phase-3 submission to a
# direct_project program uses (Section B, lines 6a-6k) - a real, citable
# structure, not a guess. SF-424C is the construction-program equivalent;
# noted in the function output rather than duplicated here since the
# category list is materially different (no personnel/fringe lines).
SF424A_BUDGET_CATEGORIES = [
    "Personnel", "Fringe Benefits", "Travel", "Equipment", "Supplies",
    "Contractual", "Construction", "Other", "Indirect Charges",
]

# 2 CFR 200.414(f) - the federal de minimis indirect cost rate: any
# non-federal entity that has never received a negotiated indirect cost
# rate may elect to charge a flat 10% of Modified Total Direct Costs
# (MTDC) without further justification. Real, citable regulation - not a
# rule of thumb invented for this tool.
DE_MINIMIS_INDIRECT_RATE = 0.10


def build_budget_framework(target_award_amount, program_id=None, target_project_length_days=None,
                            has_negotiated_indirect_rate=False):
    """Pipeline Phase 2 (proposal development - budget development): the
    structural checklist for a budget submission, not a content/dollar-
    amount generator.

    Deliberately does NOT fabricate category-level dollar splits (e.g.
    "spend 50% on personnel") - no real per-category budget data exists
    anywhere in this project's sources (USAspending reports award totals,
    not object-class breakdowns), so inventing percentages would be
    exactly the kind of unsupported precision the module's honesty
    constraint exists to prevent. What this DOES provide, all real and
    citable: the actual SF-424A category structure every direct_project
    federal submission uses, the real 2 CFR 200.414(f) de minimis indirect
    rate option, and - when program_id is given - a real sanity-check
    against this specific program's actual historical award size via
    get_grant_precedents(), the same data score_and_rank_programs' award_
    size sub-factor already uses.
    """
    checklist = [
        {"category": c, "note": None} for c in SF424A_BUDGET_CATEGORIES
    ]

    indirect_note = None
    if not has_negotiated_indirect_rate:
        indirect_note = (
            f"No negotiated indirect cost rate on file - you may elect the "
            f"federal de minimis rate of {DE_MINIMIS_INDIRECT_RATE:.0%} of Modified Total Direct "
            f"Costs (MTDC) without further justification, per 2 CFR 200.414(f). This is a real "
            f"regulatory option, not a suggested rate - verify MTDC's exact definition "
            f"(excludes equipment, capital expenditures, and the portion of subawards over "
            f"$25,000, among other exclusions) before applying it."
        )

    precedent_note = None
    template_note = None
    if program_id:
        programs_df = load_programs()
        match = programs_df[programs_df["program_id"] == program_id]
        if not match.empty:
            cfda = match.iloc[0]["cfda_number"]
            first_cfda = _split_pipe(cfda)[0] if cfda and "|" in str(cfda) else cfda
            if first_cfda and pd.notna(first_cfda):
                precedent = get_grant_precedents(first_cfda)
                if precedent.get("found"):
                    median_amount = precedent.get("median_obligated_amount")
                    if median_amount:
                        ratio = target_award_amount / median_amount
                        precedent_note = (
                            f"Your target (${target_award_amount:,.0f}) is {ratio:.2f}x this "
                            f"program's real median award (${median_amount:,.0f}, {precedent['award_count']} "
                            f"awards/10yr) - the same comparison score_and_rank_programs' award_size "
                            f"sub-factor uses. Outside roughly 0.5x-2x is worth a rescoping conversation."
                        )
            template = get_grant_writing_template(program_id)
            template_note = (
                f"Budget narrative requirement for this program's template ({template['template_id']}"
                f"{'[VERIFIED]' if template['agency_verified'] else ' [UNVERIFIED/GENERIC]'}): "
                f"{template['page_limits']}"
            )

    return {
        "target_award_amount": target_award_amount,
        "target_project_length_days": target_project_length_days,
        "sf424a_categories": checklist,
        "construction_note": "If this is a construction project, the SF-424C/D family applies "
                              "instead of SF-424A - different category structure, not listed here.",
        "indirect_cost_note": indirect_note,
        "precedent_comparison": precedent_note,
        "template_note": template_note,
        "limitation": "This is a structural checklist and real-precedent sanity check, not a "
                      "generated budget - no source in this project has category-level (personnel/"
                      "travel/equipment/etc.) dollar data to ground specific splits. Filling in "
                      "actual numbers per category is a project-specific judgment call.",
    }


if __name__ == "__main__":
    print("=" * 70)
    print("VALIDATION: Appalachia Woodlands Mission (real-world test case)")
    print("=" * 70)

    matches = match_grant_programs(
        org_type="nonprofit_501c3",
        sector_tags=["hazard_mitigation", "disaster_recovery", "green_infrastructure"],
        recipient_loc_id="USA-NC-021",
        has_government_partner=True,
        has_match_funding=False,
    )

    print(f"\n{len(matches)} matching program(s):\n")
    for m in matches:
        status = "DIRECTLY ELIGIBLE" if m["directly_eligible"] else "BLOCKED"
        print(f"[{status}] {m['program_name']} ({m['program_id']})")
        if m["blockers"]:
            for b in m["blockers"]:
                print(f"    - {b}")
        if m["pathway_note"]:
            print(f"    pathway: {m['pathway_note']}")
        print()

    print("=" * 70)
    print("PRECEDENT CHECK: Cooperative Forestry Assistance (10.664)")
    print("=" * 70)
    precedent = get_grant_precedents("10.664", org_type="nonprofit_501c3")
    for k, v in precedent.items():
        if k == "sample_award_descriptions":
            continue
        print(f"{k}: {v}")

    print("\n" + "=" * 70)
    print("TOP-5 SCORED RANKING: Appalachia Woodlands Mission")
    print("=" * 70)
    result = score_and_rank_programs(
        org_type="nonprofit_501c3",
        sector_tags=["hazard_mitigation", "disaster_recovery", "green_infrastructure"],
        recipient_loc_id="USA-NC-021",
        has_government_partner=True,
        has_match_funding=False,
        org_name="Heart to Heart Foundation",
        top_n=5,
    )
    top5 = result["top_matches"]
    if result["assistance_resources"]:
        print("\nAssistance resources (not ranked, free help-applying contacts):")
        for a in result["assistance_resources"]:
            print(f"  - {a['program_name']} ({a['agency_or_funder']})")

    for i, r in enumerate(top5, 1):
        print(f"\n#{i}: {r['program_name']} ({r['program_id']}) - score {r['score']}/100 "
              f"[precedent confidence: {r['precedent_confidence']}]")
        oo = r["open_opportunity"]
        if oo.get("is_currently_open"):
            print(f"    OPEN NOW: {oo['opportunities'][0]['title']} (closes {oo['opportunities'][0]['close_date']})")
        elif oo.get("checked_live"):
            print(f"    Confirmed live: not currently open.")
        elif oo.get("checked"):
            print(f"    Not currently open (snapshot only, no live confirmation).")
        for factor, detail in r["score_breakdown"].items():
            print(f"    {factor}: {detail['points']}/{detail['max']}")
            for sub_name, sub in detail["sub_factors"].items():
                print(f"        {sub_name}: {sub['points']}/{sub['max']} [{sub['status']}] {sub['note']}")
        if r["action_items"]:
            print("    ACTION ITEMS:")
            for a in r["action_items"]:
                print(f"        - {a}")
        tmpl = r["writing_template"]
        verified = "VERIFIED" if tmpl["agency_verified"] else "UNVERIFIED/GENERIC"
        print(f"    writing template [{verified}]: {tmpl['template_id']}")
        print(f"    sections: {'; '.join(tmpl['narrative_sections'])}")

    print("\n" + "=" * 70)
    print("VALIDATION: International track (university-led disaster reconstruction abroad)")
    print("=" * 70)
    print("Real-world trigger: a university research-network team (GMU/STAR-TIDES-style)")
    print("proposing a 'mid-to-long-term recovery and reconstruction' role after a foreign")
    print("earthquake. Confirms (a) the domestic eligibility filter correctly EXCLUDES")
    print("international-only programs when no target_country_code is given (a domestic")
    print("loc_id is positive evidence of domestic-only work), and (b) a real")
    print("target_country_code surfaces actual USAID/DFC country-level award precedent.")

    intl_result = score_and_rank_programs(
        org_type="higher_ed",
        sector_tags=["capacity_building", "disaster_recovery", "international_development", "higher_ed_partnership"],
        org_name="George Mason University",
        target_country_code="VEN",
        top_n=5,
    )
    for i, r in enumerate(intl_result["top_matches"], 1):
        print(f"\n#{i}: {r['program_name']} ({r['program_id']}) - score {r['score']}/100 "
              f"[precedent confidence: {r['precedent_confidence']}]")
        for factor, detail in r["score_breakdown"].items():
            print(f"    {factor}: {detail['points']}/{detail['max']}")
        if r["action_items"]:
            print("    ACTION ITEMS:")
            for a in r["action_items"]:
                print(f"        - {a}")

    print("\nCountry-level precedent detail (usaid_omnibus / 98.001, Venezuela):")
    country_precedent = get_country_precedent("98.001", "VEN")
    for k, v in country_precedent.items():
        if k == "sample_award_descriptions":
            continue
        print(f"    {k}: {v}")

    print("\n" + "=" * 70)
    print("VALIDATION: build_memo_talking_points (Pipeline Phase 2 - internal buy-in)")
    print("=" * 70)
    memo = build_memo_talking_points(intl_result, top_n=5)
    print(memo["summary"])
    for b in memo["talking_points"]:
        print(f"  - {b['headline']}")
        print(f"    {b['source_url']}")
    print(f"\nMemo paragraph:\n{memo['memo_paragraph']}")

    print("\n" + "=" * 70)
    print("VALIDATION: build_budget_framework (Pipeline Phase 2 - budget development)")
    print("=" * 70)
    budget = build_budget_framework(
        target_award_amount=750000,
        program_id="usaid_university_partnerships",
        target_project_length_days=730,
    )
    print("SF-424A categories:", [c["category"] for c in budget["sf424a_categories"]])
    print("Indirect cost note:", budget["indirect_cost_note"])
    print("Precedent comparison:", budget["precedent_comparison"])
    print("Template note:", budget["template_note"])
