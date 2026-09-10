"""Download and stage the USGS GNIS Domestic Names gazetteer for the offline
geocoder in ``cdata.transforms.geocode``.

The national file is ~600k rows / ~150MB uncompressed - too big to commit,
and USGS refreshes it every other month anyway, so this is a fetch script
(run once per machine, like the-derple-dex's ``scripts/fetch_cache.py``) not
a source under the ``cdata`` registry. It downloads the bulk ZIP from The
National Map's staged-products bucket, filters to the feature classes the
geocoder actually indexes (``Geocoder.GNIS_FEATURE_CLASSES`` -
water/place-adjacent classes only), and writes one pipe-delimited file into
``data/reference/gnis/`` - still keeping the columns the loader expects
(``feature_name``, ``feature_class``, ``state_name``, ``prim_lat_dec``,
``prim_long_dec``).

Usage:
    python scripts/fetch_gnis.py
"""

import csv
import io
import sys
import zipfile
from pathlib import Path

import httpx

NATIONAL_FILE_URL = (
    "https://prd-tnm.s3.amazonaws.com/StagedProducts/GeographicNames/"
    "DomesticNames/DomesticNames_National_Text.zip"
)

REPO_ROOT = Path(__file__).parent.parent
OUTPUT_PATH = REPO_ROOT / "data" / "reference" / "gnis" / "national_filtered.psv"

# Columns kept in the staged file - matches what
# cdata.transforms.geocode.Geocoder._load_gazetteer reads.
OUTPUT_FIELDS = [
    "feature_id", "feature_name", "feature_class", "state_name",
    "county_name", "prim_lat_dec", "prim_long_dec",
]


def main() -> None:
    sys.path.insert(0, str(REPO_ROOT / "src"))
    from cdata.transforms.geocode import GNIS_FEATURE_CLASSES

    print(f"Downloading {NATIONAL_FILE_URL} ...")
    response = httpx.get(NATIONAL_FILE_URL, timeout=180, follow_redirects=True)
    response.raise_for_status()
    print(f"  {len(response.content):,} bytes")

    with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
        text_name = next(n for n in zf.namelist() if n.lower().endswith(".txt"))
        raw_bytes = zf.read(text_name)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    total = 0
    kept = 0
    counts: dict[str, int] = {}
    text = raw_bytes.decode("utf-8-sig", errors="replace")

    with OUTPUT_PATH.open("w", encoding="utf-8", newline="") as fout:
        reader = csv.DictReader(io.StringIO(text), delimiter="|")
        writer = csv.DictWriter(fout, fieldnames=OUTPUT_FIELDS, delimiter="|")
        writer.writeheader()
        for row in reader:
            total += 1
            feature_class = row.get("feature_class", "")
            if feature_class not in GNIS_FEATURE_CLASSES:
                continue
            if not row.get("prim_lat_dec") or not row.get("prim_long_dec"):
                continue
            writer.writerow({k: row.get(k, "") for k in OUTPUT_FIELDS})
            kept += 1
            counts[feature_class] = counts.get(feature_class, 0) + 1

    print(f"\nWrote {OUTPUT_PATH} ({OUTPUT_PATH.stat().st_size:,} bytes)")
    print(f"kept {kept:,} of {total:,} rows")
    for feature_class, n in sorted(counts.items(), key=lambda x: -x[1]):
        print(f"  {feature_class}: {n:,}")


if __name__ == "__main__":
    main()
