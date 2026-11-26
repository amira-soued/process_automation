"""Fetch, validate, and optionally submit meter exchanges through mock APIs.

Install the dependency with: python3 -m pip install httpx
Run from the repository root: python3 fetch_meter_exchanges.py
This reads data/meter_exchange_data.csv. Supply a CSV path to use another file.
"""

import argparse
import csv
import json
import sys
from pathlib import Path
from time import sleep
from typing import Optional

import httpx

from finish_orders import (
    PAYLOAD_TEMPLATE_PATH, mock_destination, submit_eligible_orders, write_run_outputs,
)
from validation import check_columns, validate_batch


SOURCE_URL = "https://field-service.example/meter-exchanges"
SOURCE_RETRY_DELAY_SECONDS = 0.25
DEFAULT_CSV = Path(__file__).resolve().parent / "data" / "meter_exchange_data.csv"


def mock_source(csv_path: Path) -> httpx.MockTransport:
    """Serve the original CSV field names and string values through a mock GET."""
    def handle_request(request: httpx.Request) -> httpx.Response:
        if str(request.url) != SOURCE_URL:
            return httpx.Response(404)
        if request.method != "GET":
            return httpx.Response(405, headers={"Allow": "GET"})
        with csv_path.open(encoding="utf-8", newline="") as source:
            reader = csv.DictReader(source, delimiter=";", strict=True)
            check_columns(reader.fieldnames or [])
            records = list(reader)
        return httpx.Response(200, json=records)

    return httpx.MockTransport(handle_request)


def fetch_meter_exchanges(client: httpx.Client) -> list[dict[str, str]]:
    """Fetch the raw records, with one delayed retry on a connection failure."""
    try:
        response = client.get(SOURCE_URL)
    except (httpx.ConnectError, httpx.ConnectTimeout):
        sleep(SOURCE_RETRY_DELAY_SECONDS)
        response = client.get(SOURCE_URL)
    response.raise_for_status()
    return response.json()


def run_submissions(records: list[dict], output_dir: Path, failed_order: Optional[str]) -> int:
    try:
        template = json.loads(PAYLOAD_TEMPLATE_PATH.read_text(encoding="utf-8"))
        if not isinstance(template, dict):
            raise ValueError("The finish-order template must contain a JSON object.")
        validation_report = validate_batch(records)
        with httpx.Client(transport=mock_destination(failed_order), timeout=10) as client:
            report, example_payload = submit_eligible_orders(client, template, validation_report)
        write_run_outputs(output_dir, report, example_payload)
    except (OSError, ValueError) as error:
        print(f"Could not complete the finish-order run: {error}", file=sys.stderr)
        return 1

    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("csv_path", nargs="?", type=Path, default=DEFAULT_CSV,
                        help="Source CSV (defaults to data/meter_exchange_data.csv)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--validate", action="store_true",
                      help="Print cleaned eligible records, exceptions, warnings, and counts")
    mode.add_argument("--submit", action="store_true",
                      help="Validate and POST one finish-order payload per eligible row")
    parser.add_argument("--fail-order", metavar="ORDER_NO",
                        help="Return HTTP 422 for this order in the mock destination")
    parser.add_argument("--output-dir", type=Path, default=Path("."),
                        help="Directory for files from --submit (defaults to the current directory)")
    args = parser.parse_args()

    try:
        with httpx.Client(transport=mock_source(args.csv_path), timeout=10) as client:
            records = fetch_meter_exchanges(client)
    except (OSError, csv.Error, ValueError, httpx.HTTPError) as error:
        print(f"Could not fetch meter exchanges: {error}", file=sys.stderr)
        return 1

    if args.submit:
        return run_submissions(records, args.output_dir, args.fail_order)

    result = validate_batch(records) if args.validate else records
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
