"""SPARQL endpoint data source."""

from datetime import datetime
from typing import Any

from SPARQLWrapper import SPARQLWrapper, JSON

from cdata.config.schema import SourceConfig
from cdata.models import FetchResult, Record
from cdata.sources.base import BaseSource


class SPARQLSource(BaseSource):
    """SPARQL endpoint data source."""

    source_type = "sparql"

    def __init__(self, config: SourceConfig):
        super().__init__(config)

    def fetch(self, **kwargs: Any) -> FetchResult:
        """Fetch data from a SPARQL endpoint.

        Args:
            endpoint: SPARQL endpoint URL
            query: SPARQL query string
            default_graph: Optional default graph URI
        """
        started_at = datetime.utcnow()
        records: list[Record] = []

        endpoint = kwargs.get("endpoint")
        query = kwargs.get("query")
        default_graph = kwargs.get("default_graph")

        if not endpoint:
            return self._create_result([], started_at, error="No SPARQL endpoint specified")

        if not query:
            return self._create_result([], started_at, error="No SPARQL query specified")

        try:
            sparql = SPARQLWrapper(endpoint)
            sparql.setQuery(query)
            sparql.setReturnFormat(JSON)

            if default_graph:
                sparql.addDefaultGraph(default_graph)

            results = sparql.query().convert()

            bindings = results.get("results", {}).get("bindings", [])
            variables = results.get("head", {}).get("vars", [])

            for binding in bindings:
                row_data = {}
                for var in variables:
                    if var in binding:
                        value = binding[var].get("value")
                        datatype = binding[var].get("type")
                        row_data[var] = value
                        row_data[f"{var}_type"] = datatype

                record = self._create_record(
                    data=row_data,
                    metadata={"endpoint": endpoint},
                )
                records.append(record)

            return self._create_result(
                records,
                started_at,
                metadata={"variables": variables, "result_count": len(bindings)},
            )

        except Exception as e:
            return self._create_result([], started_at, error=str(e))

    def test_connection(self) -> bool:
        """Test connection to DBpedia."""
        try:
            endpoint = self.config.config.get("endpoint", "https://dbpedia.org/sparql")
            sparql = SPARQLWrapper(endpoint)
            sparql.setQuery("SELECT ?s WHERE { ?s ?p ?o } LIMIT 1")
            sparql.setReturnFormat(JSON)
            results = sparql.query().convert()
            return "results" in results
        except Exception:
            return False
