"""Fetch raw meter exchanges from a CSV-backed mock API and print them as JSON.

Install the dependency with: python3 -m pip install httpx
Run from the repository root: python3 fetch_meter_exchanges.py
This reads data/meter_exchange_data.csv. Supply a CSV path to use another file.
"""

import argparse
import csv
import json
import sys
from pathlib import Path

import httpx


SOURCE_URL = "https://field-service.example/meter-exchanges"
DEFAULT_CSV = Path(__file__).resolve().parent / "data" / "meter_exchange_data.csv"


def mock_source(csv_path: Path) -> httpx.MockTransport:
    """Serve the original CSV field names and string values through a mock GET."""
    def handle_request(request: httpx.Request) -> httpx.Response:
        if str(request.url) != SOURCE_URL:
            return httpx.Response(404)
        if request.method != "GET":
            return httpx.Response(405, headers={"Allow": "GET"})
        with csv_path.open(encoding="utf-8", newline="") as source:
            records = list(csv.DictReader(source, delimiter=";", strict=True))
        return httpx.Response(200, json=records)

    return httpx.MockTransport(handle_request)


def fetch_meter_exchanges(client: httpx.Client) -> list[dict[str, str]]:
    """Fetch the JSON list from the source without changing its values."""
    response = client.get(SOURCE_URL)
    response.raise_for_status()
    return response.json()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("csv_path", nargs="?", type=Path, default=DEFAULT_CSV,
                        help="Source CSV (defaults to data/meter_exchange_data.csv)")
    args = parser.parse_args()

    try:
        with httpx.Client(transport=mock_source(args.csv_path), timeout=10) as client:
            records = fetch_meter_exchanges(client)
    except (OSError, csv.Error, UnicodeError, httpx.HTTPError) as error:
        print(f"Could not fetch meter exchanges: {error}", file=sys.stderr)
        return 1

    print(json.dumps(records, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
