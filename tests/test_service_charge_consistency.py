import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


REPO_ROOT = Path(__file__).resolve().parents[1]


class ServiceChargeConsistencyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._old_cwd = os.getcwd()
        cls._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        os.chdir(cls._tmpdir.name)
        sys.path.insert(0, str(REPO_ROOT))
        import main  # noqa: PLC0415

        cls.main = main

    @classmethod
    def tearDownClass(cls):
        os.chdir(cls._old_cwd)
        cls.main.db.engine.dispose()
        if str(REPO_ROOT) in sys.path:
            sys.path.remove(str(REPO_ROOT))
        cls._tmpdir.cleanup()

    def _row_object(self, emp_code, department, gross_service, deposit_deduction, **overrides):
        amounts = self.main.calculate_service_amounts({
            "gross_service": gross_service,
            "sick_days": overrides.get("sick_days", 0),
            "leave_days": overrides.get("leave_days", 0),
            "leave_hours": overrides.get("leave_hours", 0),
            "late_hours": overrides.get("late_hours", 0),
            "evaluation_percent": overrides.get("evaluation_percent", 0),
            "deposit_deduction": deposit_deduction,
        })
        data = {
            "id": overrides.get("id", 1),
            "service_month_id": 1,
            "emp_code": emp_code,
            "first_name": overrides.get("first_name", "Test"),
            "last_name": overrides.get("last_name", "Employee"),
            "department": department,
            "position": "Staff",
            "service_type": "AUTO",
            "service_percent": 100,
            "service_weight": 1,
            "service_rate": gross_service,
            "fixed_amount": 0,
            "gross_service": gross_service,
            "sick_days": overrides.get("sick_days", 0),
            "leave_days": overrides.get("leave_days", 0),
            "leave_hours": overrides.get("leave_hours", 0),
            "late_hours": amounts["late_hours"],
            "evaluation_percent": overrides.get("evaluation_percent", 0),
            "notes": "",
            **amounts,
        }
        return SimpleNamespace(**data)

    def test_service_outputs_share_total_after_and_net_rules(self):
        service_month = SimpleNamespace(
            id=1,
            month="July",
            year=2026,
            room_service=1858,
            fb_service=0,
            zipline_service=0,
            other_service=0,
            manual_service_rate=None,
            note="",
        )
        normal_row = self._row_object(
            "RM-001",
            "RM-ต้อนรับส่วนหน้า",
            1000,
            100,
            id=1,
            sick_days=3,
            first_name="Normal",
        )
        capped_row = self._row_object(
            "FB-001",
            "FB-ครัวผลิต",
            1115,
            500,
            id=2,
            sick_days=5,
            leave_days=10,
            leave_hours=8,
            late_hours=6,
            first_name="Capped",
        )
        rows = [normal_row, capped_row]
        employees = {
            "RM-001": SimpleNamespace(emp_code="RM-001", first_name="Normal", last_name="Employee", department="RM-ต้อนรับส่วนหน้า", position="Staff", start_date="2026-01-01", service_type="AUTO"),
            "FB-001": SimpleNamespace(emp_code="FB-001", first_name="Capped", last_name="Employee", department="FB-ครัวผลิต", position="Staff", start_date="2026-01-01", service_type="AUTO"),
        }

        preview_rows = [vars(row).copy() for row in rows]
        save_summary = self.main.service_summary(service_month, preview_rows)
        reload_rows = [self.main.serialize_service_employee(row) for row in rows]
        reload_summary = self.main.service_summary(service_month, reload_rows)
        self.main.validate_service_summary_consistency(save_summary, reload_summary, preview_rows, reload_rows)

        detail_rows = [
            self.main.serialize_service_detail_report(row, employees[row.emp_code])
            for row in rows
        ]
        summary_row = self.main.serialize_service_summary_report(service_month, rows)
        cash_grand_total = sum(self.main.round_baht(row.get("net_service", 0)) for row in reload_rows)
        slip_rows = [
            self.main.serialize_service_slip(row, service_month, employees[row.emp_code], {})
            for row in rows
        ]
        monthly_jv = self.main.build_service_jv_report(service_month, rows, employees)

        expected_total_after = sum(row["total_after_deduction"] for row in detail_rows)
        expected_net = sum(row.net_service for row in rows)
        department_debit = sum(
            row["debit"]
            for row in monthly_jv["rows"]
            if row["acc_no"] in {"4051201", "4151201"}
        )

        self.assertEqual(save_summary["actual_employee_paid"], expected_total_after)
        self.assertEqual(reload_summary["actual_employee_paid"], expected_total_after)
        self.assertEqual(summary_row["actual_employee_paid"], expected_total_after)
        self.assertEqual(cash_grand_total, expected_net)
        self.assertEqual(department_debit, expected_total_after)
        self.assertTrue(monthly_jv["is_balanced"], monthly_jv)

        capped_detail = next(row for row in detail_rows if row["emp_code"] == "FB-001")
        capped_slip = next(row for row in slip_rows if row["emp_code"] == "FB-001")
        self.assertEqual(capped_detail["deduction_amount"], 1115)
        self.assertEqual(capped_detail["gross_service_amount"], 1115)
        self.assertEqual(capped_detail["income_amount"], 0)
        self.assertEqual(capped_detail["total_after_deduction"], 0)
        self.assertEqual(capped_detail["deposit_deduction"], 0)
        self.assertEqual(capped_detail["net_service"], 0)
        self.assertIn("Deduction capped at service amount", capped_detail["remarks"])
        self.assertEqual(capped_slip["total_after_deduction"], 0)
        self.assertEqual(capped_slip["deposit_deduction"], 0)
        self.assertEqual(capped_slip["net_service"], 0)
        self.assertIn("Deduction capped at service amount", capped_slip["deduction_remarks"])


if __name__ == "__main__":
    unittest.main()
