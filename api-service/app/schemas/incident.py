from datetime import datetime

from pydantic import BaseModel


class IncidentOut(BaseModel):
    label: str
    location: str | None = None
    severity: str
    report_count: int
    customers_est: int
    first_report: datetime
    recommended: str
    samples: list[str]
    ticket_ids: list[str]


class IncidentOverviewOut(BaseModel):
    source: str  # "local" (embedding model) | "fallback" (lexical)
    total_complaints: int
    clustered: int
    incident_count: int
    noise_count: int
    customers_est: int
    incidents: list[IncidentOut]
    noise_samples: list[str]
