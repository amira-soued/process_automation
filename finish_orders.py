"""Build finish-order payloads and submit them through the mock destination."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Optional

import httpx

from validation import issue


DESTINATION_URL = "https://order-management.example/finish-order"
PAYLOAD_TEMPLATE_PATH = Path(__file__).resolve().parent / "data" / "meter_exchange_payload.json"
PAYLOAD_FIELDS = {
    "{{ORDER_NO}}": "order_no",
    "{{EXECUTION_DATE_UTC}}": "exchange_date",
    "{{NEW_METER_NUMBER}}": "meter_number_new",
    "{{NEW_READING_180}}": "meter_reading_mount_1.8.0",
    "{{NEW_READING_280}}": "meter_reading_mount_2.8.0",
    "{{OLD_METER_NUMBER}}": "meter_number_old",
    "{{OLD_READING_180}}": "meter_reading_demount_1.8.0",
    "{{OLD_READING_280}}": "meter_reading_demount_2.8.0",
    "{{GATEWAY_NUMBER}}": "smgw_number",
    "{{DEVICE_LOCATION}}": "meter_placement",
}


def build_finish_order_payload(template: dict, record: dict[str, str]) -> dict:
    """Fill all placeholder values in a fresh copy of the template."""
    def fill_placeholders(value):
        if isinstance(value, dict):
            return {key: fill_placeholders(item) for key, item in value.items()}
        if isinstance(value, list):
            return [fill_placeholders(item) for item in value]
        if isinstance(value, str) and value.startswith("{{") and value.endswith("}}"):
            field = PAYLOAD_FIELDS.get(value)
            if field is None:
                raise ValueError(f"Unknown finish-order template placeholder {value}.")
            return record[field]
        return value

    return fill_placeholders(template)


def mock_destination(failed_order: Optional[str]) -> httpx.MockTransport:
    """Accept JSON submissions and reject the configured order with HTTP 422."""
    def handle_request(request: httpx.Request) -> httpx.Response:
        if str(request.url) != DESTINATION_URL:
            return httpx.Response(404)
        if request.method != "POST":
            return httpx.Response(405, headers={"Allow": "POST"})
        try:
            payload = json.loads(request.content)
        except ValueError:
            return httpx.Response(400, json={"message": "Expected a JSON body."})

        order_no = payload.get("orderNo") if isinstance(payload, dict) else None
        if not isinstance(order_no, str) or not order_no:
            return httpx.Response(400, json={"message": "Expected a string orderNo."})
        if order_no == failed_order:
            return httpx.Response(422, json={"message": "Configured mock rejection."})
        return httpx.Response(204)

    return httpx.MockTransport(handle_request)


def post_finish_order(client: httpx.Client, payload: dict) -> Optional[dict]:
    """Attempt one submission and return an issue if it fails."""
    try:
        client.post(DESTINATION_URL, json=payload).raise_for_status()
    except httpx.HTTPStatusError as error:
        response = error.response
        reason = f"Destination returned HTTP {response.status_code} {response.reason_phrase}."
        return {
            **issue("destination", "destination_http_error", reason),
            "http_status": response.status_code,
        }
    except httpx.TimeoutException:
        return issue(
            "destination", "destination_timeout",
            "Destination request timed out. Verify the order status before submitting again.",
        )
    except httpx.RequestError as error:
        return issue("destination", "destination_request_error",
                     f"Destination request failed. {error}")
    return None


def submit_eligible_orders(
    client: httpx.Client, template: dict, validation_report: dict
) -> tuple[dict, Optional[dict]]:
    """Build and post one payload per eligible row, collecting failures by row."""
    eligible_records = validation_report["eligible_records"]
    exceptions = [{**entry, "stage": "validation"} for entry in validation_report["exceptions"]]
    submission_failed = 0
    example_payload = None

    for entry in eligible_records:
        record = entry["record"]
        payload = build_finish_order_payload(template, record)
        submission_issue = post_finish_order(client, payload)
        if submission_issue is not None:
            submission_failed += 1
            exceptions.append({
                "row_number": entry["row_number"],
                "order_no": record["order_no"],
                "stage": "destination",
                "issues": [submission_issue],
            })
        elif example_payload is None:
            example_payload = payload

    report = {
        "summary": {
            **validation_report["summary"],
            "payloads_created": len(eligible_records),
            "submitted": len(eligible_records) - submission_failed,
            "submission_failed": submission_failed,
        },
        "exceptions": sorted(exceptions, key=lambda entry: entry["row_number"]),
        "warnings": validation_report["warnings"],
    }
    return report, example_payload


def write_run_outputs(output_dir: Path, report: dict, example_payload: Optional[dict]) -> None:
    """Write complete JSON documents before replacing the previous output files."""
    documents = {"example-payload.json": example_payload, "run-report.json": report}
    output_dir.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=output_dir, prefix=".finish-order-") as directory:
        staging = Path(directory)
        for filename, document in documents.items():
            contents = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
            (staging / filename).write_text(contents, encoding="utf-8")
        for filename in documents:
            (staging / filename).replace(output_dir / filename)
