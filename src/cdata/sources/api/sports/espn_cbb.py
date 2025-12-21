"""ESPN College Basketball data source."""

from datetime import datetime
from typing import Any

import httpx

from cdata.config import get_settings
from cdata.config.schema import SourceConfig
from cdata.models import FetchResult, Record
from cdata.sources.base import BaseSource


class ESPNCBBSource(BaseSource):
    """ESPN NCAA Men's College Basketball data source."""

    source_type = "espn_cbb"
    BASE_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball"

    def __init__(self, config: SourceConfig):
        super().__init__(config)
        self.settings = get_settings()

    def fetch(self, **kwargs: Any) -> FetchResult:
        """Fetch college basketball data from ESPN.

        Args:
            mode: Data type to fetch (scoreboard, rankings, teams, team)
            date: Date for scoreboard (YYYYMMDD format)
            team_id: Team ID for team mode
        """
        started_at = datetime.utcnow()
        mode = kwargs.get("mode", "scoreboard")

        try:
            if mode == "scoreboard":
                return self._fetch_scoreboard(started_at, kwargs.get("date"))
            elif mode == "rankings":
                return self._fetch_rankings(started_at)
            elif mode == "teams":
                return self._fetch_teams(started_at)
            elif mode == "team":
                team_id = kwargs.get("team_id")
                if not team_id:
                    return self._create_result([], started_at, error="team_id required for team mode")
                return self._fetch_team(started_at, team_id)
            else:
                return self._create_result([], started_at, error=f"Unknown mode: {mode}")
        except httpx.HTTPError as e:
            return self._create_result([], started_at, error=f"HTTP error: {e}")
        except Exception as e:
            return self._create_result([], started_at, error=str(e))

    def _fetch_scoreboard(self, started_at: datetime, date: str | None = None) -> FetchResult:
        """Fetch game scores."""
        url = f"{self.BASE_URL}/scoreboard"
        if date:
            url = f"{url}?dates={date}"

        with httpx.Client(timeout=self.settings.http_timeout) as client:
            response = client.get(url)
            response.raise_for_status()
            data = response.json()

        records: list[Record] = []
        events = data.get("events", [])

        for event in events:
            competition = event.get("competitions", [{}])[0]
            competitors = competition.get("competitors", [])

            home = next((c for c in competitors if c.get("homeAway") == "home"), {})
            away = next((c for c in competitors if c.get("homeAway") == "away"), {})

            home_team = home.get("team", {})
            away_team = away.get("team", {})

            record = self._create_record(
                data={
                    "game_id": event.get("id"),
                    "date": event.get("date"),
                    "name": event.get("name"),
                    "status": event.get("status", {}).get("type", {}).get("description"),
                    "status_detail": event.get("status", {}).get("type", {}).get("detail"),
                    "home_team_id": home_team.get("id"),
                    "home_team": home_team.get("displayName"),
                    "home_abbrev": home_team.get("abbreviation"),
                    "home_score": home.get("score"),
                    "home_rank": home.get("curatedRank", {}).get("current"),
                    "away_team_id": away_team.get("id"),
                    "away_team": away_team.get("displayName"),
                    "away_abbrev": away_team.get("abbreviation"),
                    "away_score": away.get("score"),
                    "away_rank": away.get("curatedRank", {}).get("current"),
                    "venue": competition.get("venue", {}).get("fullName"),
                    "broadcast": self._get_broadcast(competition),
                },
                metadata={"mode": "scoreboard"},
            )
            records.append(record)

        return self._create_result(records, started_at)

    def _fetch_rankings(self, started_at: datetime) -> FetchResult:
        """Fetch rankings (AP Top 25, etc.)."""
        url = f"{self.BASE_URL}/rankings"

        with httpx.Client(timeout=self.settings.http_timeout) as client:
            response = client.get(url)
            response.raise_for_status()
            data = response.json()

        records: list[Record] = []
        rankings = data.get("rankings", [])

        for ranking in rankings:
            poll_name = ranking.get("name")
            for rank in ranking.get("ranks", []):
                team = rank.get("team", {})
                record = self._create_record(
                    data={
                        "poll": poll_name,
                        "rank": rank.get("current"),
                        "previous_rank": rank.get("previous"),
                        "trend": rank.get("trend"),
                        "team_id": team.get("id"),
                        "team": team.get("nickname"),
                        "team_full": team.get("name"),
                        "team_abbrev": team.get("abbreviation"),
                        "record": rank.get("recordSummary"),
                        "points": rank.get("points"),
                        "first_place_votes": rank.get("firstPlaceVotes"),
                    },
                    metadata={"mode": "rankings", "poll": poll_name},
                )
                records.append(record)

        return self._create_result(records, started_at)

    def _fetch_teams(self, started_at: datetime) -> FetchResult:
        """Fetch all teams."""
        url = f"{self.BASE_URL}/teams"

        with httpx.Client(timeout=self.settings.http_timeout) as client:
            response = client.get(url)
            response.raise_for_status()
            data = response.json()

        records: list[Record] = []
        sports = data.get("sports", [])

        for sport in sports:
            for league in sport.get("leagues", []):
                for team in league.get("teams", []):
                    team_data = team.get("team", {})
                    record = self._create_record(
                        data={
                            "team_id": team_data.get("id"),
                            "name": team_data.get("displayName"),
                            "nickname": team_data.get("nickname"),
                            "abbreviation": team_data.get("abbreviation"),
                            "location": team_data.get("location"),
                            "color": team_data.get("color"),
                            "logo": team_data.get("logos", [{}])[0].get("href") if team_data.get("logos") else None,
                        },
                        metadata={"mode": "teams"},
                    )
                    records.append(record)

        return self._create_result(records, started_at)

    def _fetch_team(self, started_at: datetime, team_id: str) -> FetchResult:
        """Fetch specific team details."""
        url = f"{self.BASE_URL}/teams/{team_id}"

        with httpx.Client(timeout=self.settings.http_timeout) as client:
            response = client.get(url)
            response.raise_for_status()
            data = response.json()

        team = data.get("team", {})
        record = self._create_record(
            data={
                "team_id": team.get("id"),
                "name": team.get("displayName"),
                "nickname": team.get("nickname"),
                "abbreviation": team.get("abbreviation"),
                "location": team.get("location"),
                "color": team.get("color"),
                "logo": team.get("logos", [{}])[0].get("href") if team.get("logos") else None,
                "venue": team.get("franchise", {}).get("venue", {}).get("fullName"),
                "conference": self._get_conference(team),
                "record": team.get("record", {}).get("items", [{}])[0].get("summary") if team.get("record") else None,
            },
            metadata={"mode": "team", "team_id": team_id},
        )

        return self._create_result([record], started_at)

    def _get_broadcast(self, competition: dict) -> str | None:
        """Extract broadcast info from competition."""
        broadcasts = competition.get("broadcasts", [])
        if broadcasts:
            names = broadcasts[0].get("names", [])
            return names[0] if names else None
        return None

    def _get_conference(self, team: dict) -> str | None:
        """Extract conference from team data."""
        groups = team.get("groups", {})
        if groups:
            return groups.get("parent", {}).get("name")
        return None

    def test_connection(self) -> bool:
        """Test connection by hitting scoreboard endpoint."""
        try:
            with httpx.Client(timeout=10) as client:
                response = client.get(f"{self.BASE_URL}/scoreboard")
                return response.status_code == 200
        except Exception:
            return False
