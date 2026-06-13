from pydantic import BaseModel
from typing import Literal, Optional
from enum import Enum


class EventType(str, Enum):
    sports = "sports"
    tech = "tech"
    business = "business"
    disaster = "disaster"
    cultural = "cultural"
    political = "political"
    other = "other"


class VerificationStatus(str, Enum):
    # Set by the grounding pass (Step 5), not by extraction.
    confirmed = "confirmed"            # supported by 2+ cited sources
    single_source = "single_source"   # supported by exactly 1 cited source
    unverified = "unverified"         # cited excerpts don't support the claim (or no citation)
    conflicted = "conflicted"         # cited sources disagree


class KeyFact(BaseModel):
    label: str
    value: str
    # 1-based ids into TopicPage.sources. Populated by extraction, normalized
    # deterministically, then graded by the grounding pass.
    source_ids: list[int] = []
    verification: VerificationStatus = VerificationStatus.unverified
    note: Optional[str] = None        # e.g. a short conflict explanation


class TimelineEntry(BaseModel):
    date: str
    description: str
    source_ids: list[int] = []
    verification: VerificationStatus = VerificationStatus.unverified
    note: Optional[str] = None


class Entity(BaseModel):
    name: str
    role: str
    type: Literal["person", "org", "location"]


class Source(BaseModel):
    id: int = 0                       # stable citation number, assigned deterministically
    title: str
    url: str
    publisher: str
    date: str


class ScheduleEntry(BaseModel):
    date: str = ""
    matchup: str = ""
    venue: str = ""
    result: Optional[str] = None


class PlayerStat(BaseModel):
    name: str
    team: str
    stat: str


class SportsData(BaseModel):
    schedule: list[ScheduleEntry] = []
    standings: Optional[list[dict]] = None
    key_players: Optional[list[PlayerStat]] = None


class FeatureItem(BaseModel):
    name: str
    description: str


class PricingTier(BaseModel):
    tier: str
    price: str


class TechData(BaseModel):
    features: list[FeatureItem] = []
    pricing: Optional[list[PricingTier]] = None
    availability: Optional[str] = None
    comparison: Optional[str] = None


class CulturalScheduleEntry(BaseModel):
    date: str
    description: str


class CulturalData(BaseModel):
    performers: list[str] = []
    schedule: list[CulturalScheduleEntry] = []
    how_to_watch: Optional[str] = None
    location: Optional[str] = None


# Simple label/value pair for nested event blocks. Deliberately NOT KeyFact:
# per-claim provenance/verification only applies to top-level key_facts and timeline.
class LabelValue(BaseModel):
    label: str
    value: str


class CompanyRef(BaseModel):
    name: str
    ticker: str = ""          # e.g. "NVDA"; empty for private companies
    role: str = ""            # acquirer, target, issuer, regulator...


class BusinessData(BaseModel):
    companies: list[CompanyRef] = []
    key_figures: list[LabelValue] = []     # deal size, % move, EPS, valuation
    market_reaction: Optional[str] = None
    what_it_means: Optional[str] = None


class AffectedArea(BaseModel):
    name: str
    impact: str               # short description of impact in that area


class DisasterData(BaseModel):
    affected_areas: list[AffectedArea] = []
    impact_stats: list[LabelValue] = []    # magnitude, casualties, damage estimate
    response_efforts: list[str] = []
    safety_guidance: Optional[str] = None


class TopicPage(BaseModel):
    title: str
    summary: str
    event_type: EventType
    last_updated: str
    key_facts: list[KeyFact]
    timeline: list[TimelineEntry]
    entities: list[Entity]
    sources: list[Source]
    sports_data: Optional[SportsData] = None
    tech_data: Optional[TechData] = None
    cultural_data: Optional[CulturalData] = None
    business_data: Optional[BusinessData] = None
    disaster_data: Optional[DisasterData] = None


class InputVerdict(str, Enum):
    ok = "ok"               # a single, identifiable real event — proceed
    ambiguous = "ambiguous"  # could mean 2+ events, or too vague — surface interpretations
    refuse = "refuse"        # not a buildable news event (off-topic, fictional, injection)


class ClassificationResult(BaseModel):
    # Input gate (set by Step 1, before any search budget is spent).
    verdict: InputVerdict = InputVerdict.ok
    reason: str = ""                    # user-facing explanation when ambiguous/refused
    interpretations: list[str] = []     # 2-3 concrete rephrasings when ambiguous
    event_type: EventType
    suggested_title: str
    entities: list[Entity]
    confidence: float
