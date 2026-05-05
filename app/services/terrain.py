import os
from typing import Optional

from groq import Groq
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas import GradientDistribution, SteepestSection, TerrainResponse

# AS 1428.1-2009 Section 5.2, the only gradient threshold used.
# Accessible paths of travel must not exceed 1:20 (5%).
# No other threshold is assumed or sourced from any other standard.
_AS1428_PATH_MAX = 5.0

# Based on the percentage of footpaths within the AS 1428.1 5% standard.
_RATING_RULES = [
    ("mostly_accessible",    lambda w: w >= 80),
    ("partially_accessible", lambda w: w >= 60),
    ("largely_inaccessible", lambda w: True),   # catch-all
]

# Plain-English context passed to the LLM for each rating level.
# All descriptions reference AS 1428.1 Section 5.2 only.
_RATING_CONTEXT = {
    "mostly_accessible": (
        "The majority of footpaths in this area are within the AS 1428.1 Section 5.2 "
        "accessible path standard (maximum 5%). Any sections exceeding this standard "
        "are minor and cover a very small part of the surrounding area."
    ),
    "partially_accessible": (
        "Some footpaths in this area are within the AS 1428.1 Section 5.2 accessible "
        "path standard (maximum 5%), but a notable portion exceed it. Wheelchair users "
        "should expect some challenging sections."
    ),
    "largely_inaccessible": (
        "A significant portion of footpaths in this area exceed the AS 1428.1 Section 5.2 "
        "accessible path standard (maximum 5%). This area may be very difficult for manual "
        "wheelchair users."
    ),
}


def _compute_distribution(records: list[dict]) -> GradientDistribution:
    """
    Compute the percentage of footpath records within and outside the
    AS 1428.1 Section 5.2 accessible path standard (5% maximum).

    Each record is a dict with a 'gradepc' key (gradient as a float).
    Percentages are rounded to 1 decimal place and sum to 100%.
    """
    total   = len(records)
    within  = sum(1 for r in records if r["gradepc"] < _AS1428_PATH_MAX)
    outside = sum(1 for r in records if r["gradepc"] >= _AS1428_PATH_MAX)

    return GradientDistribution(
        within_standard_percent=round(within  / total * 100, 1),
        outside_standard_percent=round(outside / total * 100, 1),
    )


def _compute_rating(dist: GradientDistribution) -> str:
    """
    Derive an overall accessibility rating from the gradient distribution.
    Rules are evaluated in order — first match wins.

    Returns one of: "mostly_accessible", "partially_accessible",
    "largely_inaccessible".
    """
    for label, rule in _RATING_RULES:
        if rule(dist.within_standard_percent):
            return label
    return "partially_accessible"


async def _call_groq(
    destination_name: str,
    dist: GradientDistribution,
    steepest: SteepestSection,
    rating: str,
) -> Optional[str]:
    """
    Call Groq (Llama 3.1) to generate a 2-sentence plain-English terrain
    summary for wheelchair users.

    Returns None (graceful degradation) when:
    - GROQ_API_KEY is not set in the environment
    - The Groq API call fails for any reason

    The terrain card still renders with rating and distribution data
    even when this returns None.

    The rating_context is passed to calibrate the tone — preventing
    contradictions between the overall assessment and the steepest section
    description. Directional advice is explicitly excluded to avoid
    conflicting with OTP routing recommendations on the journey planning page.
    """
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        return None

    try:
        client = Groq(api_key=api_key)

        # Build steepest section line conditionally — avoids "unknown location"
        # appearing in the LLM output when address is missing in source data.
        steepest_line = (
            f"Steepest section near {steepest.address}"
            if steepest.address
            else "Steepest section location not recorded in source data"
        )

        prompt = f"""Write exactly 2 sentences summarising terrain accessibility for wheelchair users visiting {destination_name} in Melbourne.

                            Facts:
                            - {dist.within_standard_percent}% of paths meet AS 1428.1 (Australian accessible path standard)
                            - {dist.outside_standard_percent}% of paths exceed AS 1428.1
                            - Overall rating: {_RATING_CONTEXT[rating]}
                            - {steepest_line}

                            Sentence 1: Overall verdict on accessibility. Mention AS 1428.1. 
                            If outside_standard is above 10%, acknowledge that while the area is 
                            mostly accessible, some sections exceed the standard. 
                            If outside_standard is below 10%, simply state the area is accessible.
                            No numbers.

                            Sentence 2: The outside_standard value is {dist.outside_standard_percent}%.
                            Use exactly this logic:
                            - If the value is under 10: say there is a minor concern affecting a small part of the area
                            - If the value is between 10 and 25: say there is a notable concern affecting a meaningful portion of the area, and warn manual wheelchair users specifically
                            - If the value is over 25: say there is a significant concern affecting a large part of the area which may be very challenging
                            If a specific location is provided in the steepest section info, mention it naturally — for example "particularly near Collins Street".
                            If no location is provided, do not mention location at all and do not say it is unspecified.

                            Rules:
                            - EXACTLY 2 sentences — stop writing after the second sentence
                            - No percentages or numbers of any kind
                            - When referencing AS 1428.1, say "Australian wheelchair accessibility standard" instead, do not use the code name AS 1428.1
                            - No word "gradient" or "footpath"
                            - Do not mention that location data is missing or unspecified
                            - No alternative routes or approach directions
                            - Plain English only"""

        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=200,
        )
        return response.choices[0].message.content.strip()

    except Exception as e:
        # Swallow all Groq errors, terrain card renders without summary
        print(f"[Groq ERROR] {type(e).__name__}: {e}")
        return None


async def get_terrain(
    destination_id: int,
    destination_name: str,
    dest_lat: float,
    dest_lon: float,
    radius_m: int,
    session: AsyncSession,
) -> TerrainResponse:
    """
    Main service function for terrain assessment.

    Steps:
    1. Query footpath_steepness for all valid records within radius_m of
       the destination using ST_DWithin (GIST-indexed, metres via geography cast).
    2. If no records found, return data_available=False, destination is outside
       City of Melbourne LGA coverage (5 of 56 destinations have no data).
    3. Compute distribution of footpaths within vs outside AS 1428.1 standard.
    4. Derive overall rating from distribution.
    5. Identify the steepest recorded section (max gradient_percent record).
    6. Call Groq for a plain-English summary (degrades gracefully on failure).
    7. Return the assembled TerrainResponse.
    """

    # ST_DWithin with ::geography cast computes true metres, not degrees.
    # The GIST index on footpath_steepness.geom makes this query fast even
    # across 28,783 records.
    result = await session.execute(
        text("""
            SELECT gradient_percent, address
            FROM footpath_steepness
            WHERE ST_DWithin(
                geom::geography,
                ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography,
                :radius
            )
        """),
        {"lat": dest_lat, "lon": dest_lon, "radius": radius_m},
    )
    rows = result.mappings().all()

    # No records means this destination is outside City of Melbourne LGA, the footpath steepness dataset only covers the CoM boundary.
    if not rows:
        return TerrainResponse(
            data_available=False,
            radius_m=radius_m,
            rating=None,
            gradient_distribution=None,
            steepest_section=None,
            summary=None,
        )

    # Normalise rows into plain dicts for classification functions
    records = [
        {"gradepc": row["gradient_percent"], "address": row["address"]}
        for row in rows
    ]

    dist   = _compute_distribution(records)
    rating = _compute_rating(dist)

    # Steepest section, used in both the structured response and the Groq prompt
    steepest_record = max(records, key=lambda r: r["gradepc"])
    steepest = SteepestSection(
        gradient_percent=round(steepest_record["gradepc"], 1),
        address=steepest_record["address"],
    )

    # Groq call is last, all structured data is available regardless of outcome
    summary = await _call_groq(destination_name, dist, steepest, rating)

    return TerrainResponse(
        data_available=True,
        radius_m=radius_m,
        rating=rating,
        gradient_distribution=dist,
        steepest_section=steepest,
        summary=summary,
    )