from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

os.environ.setdefault("ARROW_USER_SIMD_LEVEL", "NONE")

import pyarrow as pa
import pyarrow.parquet as pq


def arrow_type(field_type: str) -> pa.DataType:
    if field_type == "number":
        return pa.float64()
    if field_type == "integer":
        return pa.int64()
    return pa.string()


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: write_parquet_zstd.py OUTPUT_PATH")

    payload = json.load(sys.stdin)
    fields: list[dict[str, str]] = payload["fields"]
    rows: list[dict[str, Any]] = payload["rows"]
    metadata: dict[str, Any] = payload.get("metadata", {})

    arrays = []
    schema_fields = []
    for field in fields:
        name = field["name"]
        dtype = arrow_type(field["type"])
        arrays.append(pa.array([row.get(name) for row in rows], type=dtype))
        schema_fields.append(pa.field(name, dtype))

    schema = pa.schema(schema_fields).with_metadata(
        {key.encode("utf-8"): json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8") for key, value in metadata.items()}
    )
    table = pa.Table.from_arrays(arrays, schema=schema)
    output_path = Path(sys.argv[1])
    pq.write_table(
        table,
        output_path,
        compression="zstd",
        compression_level=9,
        use_dictionary=True,
        row_group_size=100_000,
        write_statistics=True,
    )
    if pq.read_metadata(output_path).num_rows != len(rows):
        raise RuntimeError("Parquet row count mismatch")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
