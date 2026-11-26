import csv
import unittest
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import httpx

import fetch_meter_exchanges
from validation import check_columns, validate_batch


def exchange(**changes):
    record = {
        "order_no": "01234", "exchange_date": "09.11.2026 08:00",
        "street": "Rappenauer Str.", "number": "7a", "postal_code": "06295",
        "city": "Frostleben", "meter_number_old": "SLE00501-17-10056",
        "meter_number_new": "00123", "meter_placement": " EG Links ",
        "meter_reading_demount_1.8.0": "10800,80", "meter_reading_demount_2.8.0": "55",
        "meter_reading_mount_1.8.0": "0", "meter_reading_mount_2.8.0": "0,00",
        "smgw_number": "ETHE4170753645",
    }
    return {**record, **changes}


class ValidationTests(unittest.TestCase):
    def test_normalizes_without_changing_source(self):
        raw = exchange()
        original = deepcopy(raw)
        result = validate_batch([raw])
        self.assertEqual(raw, original)
        self.assertEqual(result["exceptions"], [])
        self.assertEqual(result["warnings"], [])
        self.assertEqual(result["eligible_records"][0]["record"], {
            **original, "exchange_date": "2026-11-09T07:00:00Z", "street": "Rappenauer Straße",
            "meter_number_old": "SLE005011710056", "meter_placement": "EG Links",
            "meter_reading_demount_1.8.0": "10800.80",
            "meter_reading_mount_2.8.0": "0.00",
        })

    def test_missing_fields_reported_together_and_next_row_survives(self):
        raw = exchange(meter_number_old="", smgw_number=" ")
        raw["meter_reading_demount_1.8.0"] = ""
        result = validate_batch([raw, exchange(order_no="22222")])
        exception, = result["exceptions"]
        self.assertEqual((exception["row_number"], exception["order_no"]), (2, "01234"))
        self.assertEqual({i["field"] for i in exception["issues"]},
                         {"meter_number_old", "smgw_number", "meter_reading_demount_1.8.0"})
        self.assertEqual(result["eligible_records"][0]["row_number"], 3)

    def test_bad_measurements_and_identifiers_are_blocked(self):
        for field, value, category in [
            ("order_no", "1234", "invalid_order"),
            ("meter_number_old", "0", "invalid_meter_id"),
            ("meter_number_old", "00-123", "same_meter"),
            ("meter_number_new", "---", "invalid_meter_id"),
            ("meter_reading_mount_1.8.0", "-2", "invalid_reading"),
            ("meter_reading_mount_1.8.0", "1.234", "invalid_reading"),
            ("meter_reading_mount_2.8.0", "1.234,50", "invalid_reading"),
            ("meter_reading_demount_1.8.0", "unknown", "invalid_reading"),
        ]:
            with self.subTest(field=field, value=value):
                result = validate_batch([exchange(**{field: value})])
                self.assertEqual(result["eligible_records"], [])
                self.assertEqual(result["exceptions"][0]["issues"][0]["category"], category)
                self.assertEqual(result["warnings"], [])

    def test_warnings_allow_submission_and_preserve_values(self):
        raw = exchange(postal_code="6295", smgw_number="1234567890")
        result = validate_batch([raw])
        clean = result["eligible_records"][0]["record"]
        self.assertEqual((clean["postal_code"], clean["smgw_number"]), ("6295", "1234567890"))
        self.assertEqual({i["field"] for i in result["warnings"][0]["issues"]},
                         {"postal_code", "smgw_number"})

    def test_positive_installation_readings_warn_and_remain_eligible(self):
        readings = {"meter_reading_mount_1.8.0": "33904,70", "meter_reading_mount_2.8.0": "2"}
        result = validate_batch([exchange(**readings)])
        self.assertEqual(result["exceptions"], [])
        eligible, = result["eligible_records"]
        row_warning, = result["warnings"]
        self.assertEqual(
            {entry["field"]: entry["category"] for entry in row_warning["issues"]},
            dict.fromkeys(readings, "nonzero_installation_reading"),
        )
        self.assertEqual(eligible["record"]["meter_reading_mount_1.8.0"], "33904.70")
        self.assertEqual(eligible["record"]["meter_reading_mount_2.8.0"], "2")

    def test_duplicate_orders_hold_both_rows(self):
        result = validate_batch([exchange(), exchange(order_no="99999"), exchange(order_no=" 01234 ")])
        self.assertEqual([e["row_number"] for e in result["exceptions"]], [2, 4])
        self.assertEqual(result["exceptions"][0]["issues"][0]["category"], "duplicate_order")
        self.assertEqual(result["eligible_records"][0]["row_number"], 3)

    def test_dates_and_daylight_saving(self):
        for date in ("31.02.2026 09:00", "29.03.2026 02:30", "25.10.2026 02:30", "9.11.2026 08:00"):
            with self.subTest(date=date):
                result = validate_batch([exchange(exchange_date=date)])
                self.assertEqual(result["exceptions"][0]["issues"][0]["category"], "invalid_date")
        result = validate_batch([exchange(exchange_date="01.07.2026 08:00")])
        self.assertEqual(result["eligible_records"][0]["record"]["exchange_date"], "2026-07-01T06:00:00Z")

    def test_bad_headers(self):
        columns = list(exchange())
        for bad in ([], columns[1:], columns + ["order_no"]):
            with self.subTest(columns=bad), self.assertRaises(ValueError):
                check_columns(bad)

    def test_source_api_503_reports_failure(self):
        def unavailable(request):
            self.assertEqual(request.method, "GET")
            self.assertEqual(str(request.url), fetch_meter_exchanges.SOURCE_URL)
            return httpx.Response(503)

        transport = httpx.MockTransport(unavailable)
        stdout, stderr = StringIO(), StringIO()
        with (
            patch("sys.argv", ["fetch_meter_exchanges.py", "--validate"]),
            patch.object(fetch_meter_exchanges, "mock_source", return_value=transport),
            patch.object(fetch_meter_exchanges, "validate_batch") as validate,
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            status = fetch_meter_exchanges.main()

        self.assertEqual(status, 1)
        self.assertIn("Could not fetch meter exchanges", stderr.getvalue())
        self.assertIn("503", stderr.getvalue())
        self.assertEqual(stdout.getvalue(), "")
        validate.assert_not_called()

    def test_case_study_csv(self):
        path = Path(__file__).parent / "data" / "meter_exchange_data.csv"
        with path.open(encoding="utf-8", newline="") as source:
            result = validate_batch(list(csv.DictReader(source, delimiter=";")))
        self.assertEqual(result["summary"], {"fetched": 62, "eligible": 58,
                                             "blocked": 4, "rows_with_warnings": 15})
        self.assertEqual([e["row_number"] for e in result["exceptions"]], [16, 32, 40, 63])
        positive_reading_rows = [
            row["row_number"] for row in result["warnings"]
            if any(entry["category"] == "nonzero_installation_reading" for entry in row["issues"])
        ]
        self.assertEqual(positive_reading_rows, [40, 42])


if __name__ == "__main__":
    unittest.main()
