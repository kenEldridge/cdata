"""CSV storage backend."""

from pathlib import Path
from typing import Any, Optional

import pandas as pd

from cdata.models import Record
from cdata.storage.base import StorageBackend


class CSVStorage(StorageBackend):
    """CSV file storage backend."""

    @property
    def extension(self) -> str:
        return "csv"

    def write(
        self,
        records: list[Record],
        name: str,
        partition_by: Optional[list[str]] = None,
    ) -> Path:
        df = self._records_to_dataframe(records)
        if df.empty:
            return self.base_path / f"{name}.csv"

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
                group.to_csv(partition_path / "data.csv", index=False)
            return path
        else:
            path = self.base_path / f"{name}.csv"
            df.to_csv(path, index=False)
            return path

    def read(
        self,
        name: str,
        filters: Optional[dict[str, Any]] = None,
    ) -> pd.DataFrame:
        file_path = self.base_path / f"{name}.csv"
        dir_path = self.base_path / name

        if file_path.exists():
            df = pd.read_csv(file_path)
        elif dir_path.exists():
            dfs = []
            for csv_file in dir_path.rglob("*.csv"):
                dfs.append(pd.read_csv(csv_file))
            df = pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()
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
    ) -> Path:
        df_new = self._records_to_dataframe(records)
        if df_new.empty:
            return self.base_path / f"{name}.csv"

        file_path = self.base_path / f"{name}.csv"

        if file_path.exists():
            df_new.to_csv(file_path, mode="a", header=False, index=False)
        else:
            df_new.to_csv(file_path, index=False)

        return file_path
