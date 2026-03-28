"""ACLED (Armed Conflict Location & Event Data) source."""

from datetime import datetime, timedelta
from typing import Any, Optional

import httpx

from cdata.config.env import get_settings
from cdata.config.schema import SourceConfig
from cdata.models import FetchResult, Record
from cdata.sources.base import BaseSource

ACLED_TOKEN_URL = "https://acleddata.com/oauth/token"
ACLED_API_URL = "https://acleddata.com/api/acled/read"

# Fields to preserve from the ACLED API response.
ACLED_FIELDS = [
    "event_id_cnty",
    "event_date",
    "year",
    "time_precision",
    "disorder_type",
    "event_type",
    "sub_event_type",
    "actor1",
    "actor2",
    "assoc_actor_1",
    "assoc_actor_2",
    "country",
    "admin1",
    "admin2",
    "location",
    "latitude",
    "longitude",
    "fatalities",
    "source",
    "source_scale",
    "notes",
    "civilian_targeting",
]


class ACLEDSource(BaseSource):
    """ACLED conflict event data source."""

    source_type = "acled"

    def __init__(self, config: SourceConfig):
        super().__init__(config)
        self._token: Optional[str] = None

    def _authenticate(self, client: httpx.Client) -> str:
        """Exchange credentials for an OAuth access token."""
        if self._token is not None:
            return self._token

        settings = get_settings()
        if not settings.acled_email or not settings.acled_password:
            raise ValueError(
                "ACLED credentials not set. "
                "Set CDATA_ACLED_EMAIL and CDATA_ACLED_PASSWORD in your .env file."
            )

        resp = client.post(
            ACLED_TOKEN_URL,
            data={
                "grant_type": "password",
                "client_id": "acled",
                "username": settings.acled_email,
                "password": settings.acled_password,
            },
        )
        resp.raise_for_status()
        self._token = resp.json()["access_token"]
        return self._token

    def fetch(self, **kwargs: Any) -> FetchResult:
        """Fetch conflict events from ACLED.

        Config keys (via SourceConfig.config):
            countries: list of country names to filter
            event_types: list of event types to filter
            lookback_days: rolling window size (default 90)
        """
        started_at = datetime.utcnow()
        records: list[Record] = []
        errors: list[str] = []

        countries = kwargs.get("countries", [])
        event_types = kwargs.get("event_types", [])
        lookback_days = int(kwargs.get("lookback_days", 90))

        start_date = (datetime.utcnow() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
        today = datetime.utcnow().strftime("%Y-%m-%d")

        try:
            with httpx.Client(timeout=60) as client:
                token = self._authenticate(client)
                headers = {"Authorization": f"Bearer {token}"}

                params: dict[str, Any] = {
                    "_format": "json",
                    "event_date": f"{start_date}|{today}",
                    "event_date_where": "BETWEEN",
                    "limit": 5000,
                    "fields": "|".join(ACLED_FIELDS),
                }

                if countries:
                    params["country"] = "|".join(countries)
                if event_types:
                    params["event_type"] = "|".join(event_types)

                page = 1
                while True:
                    params["page"] = page
                    resp = client.get(ACLED_API_URL, params=params, headers=headers)
                    resp.raise_for_status()
                    body = resp.json()

                    events = body.get("data", [])
                    if not events:
                        break

                    for event in events:
                        # Coerce numeric fields
                        for field in ("latitude", "longitude"):
                            if field in event and event[field] is not None:
                                try:
                                    event[field] = float(event[field])
                                except (ValueError, TypeError):
                                    pass
                        if "fatalities" in event and event["fatalities"] is not None:
                            try:
                                event["fatalities"] = int(event["fatalities"])
                            except (ValueError, TypeError):
                                pass

                        record = self._create_record(
                            data={k: event.get(k) for k in ACLED_FIELDS},
                            metadata={"source": "ACLED"},
                        )
                        records.append(record)

                    if len(events) < params["limit"]:
                        break
                    page += 1

        except Exception as e:
            errors.append(f"ACLED fetch error: {e}")

        error_msg = "; ".join(errors) if errors else None
        return self._create_result(records, started_at, error=error_msg)

    def test_connection(self) -> bool:
        """Test connection by fetching a single event."""
        try:
            with httpx.Client(timeout=30) as client:
                token = self._authenticate(client)
                headers = {"Authorization": f"Bearer {token}"}
                resp = client.get(
                    ACLED_API_URL,
                    params={"_format": "json", "limit": 1},
                    headers=headers,
                )
                resp.raise_for_status()
                data = resp.json().get("data", [])
                return len(data) > 0
        except Exception:
            return False
