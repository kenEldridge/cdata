"""Parquet storage backend."""

from pathlib import Path
from typing import Any, Optional

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from cdata.models import Record
from cdata.storage.base import StorageBackend


class ParquetStorage(StorageBackend):
    """Parquet file storage backend."""

    @property
    def extension(self) -> str:
        return "parquet"

    def write(
        self,
        records: list[Record],
        name: str,
        partition_by: Optional[list[str]] = None,
    ) -> Path:
        df = self._records_to_dataframe(records)
        if df.empty:
            return self.base_path / name

        table = pa.Table.from_pandas(df)

        if partition_by:
            path = self.base_path / name
            pq.write_to_dataset(
                table,
                root_path=str(path),
                partition_cols=partition_by,
                existing_data_behavior="overwrite_or_ignore",
            )
            return path
        else:
            path = self.base_path / f"{name}.parquet"
            pq.write_table(table, path)
            return path

    def read(
        self,
        name: str,
        filters: Optional[dict[str, Any]] = None,
    ) -> pd.DataFrame:
        file_path = self.base_path / f"{name}.parquet"
        dir_path = self.base_path / name

        if file_path.exists():
            table = pq.read_table(file_path)
        elif dir_path.exists():
            pq_filters = None
            if filters:
                pq_filters = [(k, "=", v) for k, v in filters.items()]
            table = pq.read_table(dir_path, filters=pq_filters)
        else:
            return pd.DataFrame()

        return table.to_pandas()

    def append(
        self,
        records: list[Record],
        name: str,
    ) -> Path:
        df_new = self._records_to_dataframe(records)
        if df_new.empty:
            return self.base_path / name

        file_path = self.base_path / f"{name}.parquet"

        if file_path.exists():
            df_existing = self.read(name)
            df_combined = pd.concat([df_existing, df_new], ignore_index=True)
        else:
            df_combined = df_new

        table = pa.Table.from_pandas(df_combined)
        pq.write_table(table, file_path)
        return file_path
