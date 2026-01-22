"""JSON storage backend."""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from cdata.models import Record
from cdata.storage.base import StorageBackend


class JSONEncoder(json.JSONEncoder):
    """Custom JSON encoder for datetime objects."""

    def default(self, obj: Any) -> Any:
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)


class JSONStorage(StorageBackend):
    """JSON file storage backend."""

    @property
    def extension(self) -> str:
        return "json"

    def write(
        self,
        records: list[Record],
        name: str,
        partition_by: Optional[list[str]] = None,
    ) -> Path:
        df = self._records_to_dataframe(records)
        if df.empty:
            return self.base_path / f"{name}.json"

        if partition_by:
            path = self.base_path / name
            path.mkdir(parents=True, exist_ok=True)
            for keys, group in df.groupby(partition_by):
                if not isinstance(keys, tuple):
                    keys = (keys,)
                partition_path = path
                for col, val in zip(partition_by, keys):
                    partition_path = partition_path / f"{col}={val}"
                partition_path.mkdir(parents=True, exist_ok=True)
                data = group.to_dict(orient="records")
                with open(partition_path / "data.json", "w") as f:
                    json.dump(data, f, cls=JSONEncoder, indent=2)
            return path
        else:
            path = self.base_path / f"{name}.json"
            data = df.to_dict(orient="records")
            with open(path, "w") as f:
                json.dump(data, f, cls=JSONEncoder, indent=2)
            return path

    def read(
        self,
        name: str,
        filters: Optional[dict[str, Any]] = None,
    ) -> pd.DataFrame:
        file_path = self.base_path / f"{name}.json"
        dir_path = self.base_path / name

        if file_path.exists():
            with open(file_path) as f:
                data = json.load(f)
            df = pd.DataFrame(data)
        elif dir_path.exists():
            all_data = []
            for json_file in dir_path.rglob("*.json"):
                with open(json_file) as f:
                    all_data.extend(json.load(f))
            df = pd.DataFrame(all_data) if all_data else pd.DataFrame()
        else:
            return pd.DataFrame()

        if filters and not df.empty:
            for col, val in filters.items():
                if col in df.columns:
                    df = df[df[col] == val]

        return df

    def append(
        self,
        records: list[Record],
        name: str,
        primary_keys: Optional[list[str]] = None,
    ) -> Path:
        df_new = self._records_to_dataframe(records)
        if df_new.empty:
            return self.base_path / f"{name}.json"

        file_path = self.base_path / f"{name}.json"

        if file_path.exists():
            df_existing = self.read(name)
            df_combined = pd.concat([df_existing, df_new], ignore_index=True)
        else:
            df_combined = df_new

        # Deduplicate if primary keys specified
        df_combined = self._deduplicate(df_combined, primary_keys)

        data = df_combined.to_dict(orient="records")
        with open(file_path, "w") as f:
            json.dump(data, f, cls=JSONEncoder, indent=2)

        return file_path
