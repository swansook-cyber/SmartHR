import streamlit as st
import pandas as pd
import requests
import io
import datetime
import html
import base64
import mimetypes
import streamlit.components.v1 as components
from reportlab.lib.pagesizes import letter, A4, landscape
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib import colors
import os
import re
import math
from decimal import Decimal, ROUND_HALF_UP

API_URL = "http://localhost:8000"
REQUEST_TIMEOUT = 10
SERVICE_API_PREFIX = "/api/service"

st.set_page_config(page_title="Aonang Fiore HRMS", layout="wide", page_icon="🌴")

DEPARTMENT_ORDER = [
    "AM-บริหารส่วนกลาง",
    "HR-ทรัพยากรบุคคล",
    "AC-บัญชี",
    "SM-การตลาด",
    "RM-ต้อนรับส่วนหน้า",
    "RM-แม่บ้าน",
    "FB-ครัวผลิต",
    "FB-ห้องอาหาร",
    "EN-ช่างทั่วไป",
    "GN-สวน-ภูมิทัศน์",
    "TU-Zipline",
    "MY-เรือ MY Lalida",
]
DEPARTMENT_ORDER_INDEX = {dept: index for index, dept in enumerate(DEPARTMENT_ORDER)}


def ordered_department_names(grouped_departments):
    first_seen = {dept: index for index, dept in enumerate(grouped_departments.keys())}
    return sorted(
        grouped_departments.keys(),
        key=lambda dept: (
            DEPARTMENT_ORDER_INDEX.get(dept, len(DEPARTMENT_ORDER)),
            first_seen.get(dept, len(first_seen)),
        ),
    )


def employee_report_order_key(row, fallback_index=0):
    payroll_order = row.get("payroll_order")
    if payroll_order not in [None, ""]:
        return (0, int(payroll_order))
    emp_code = str(row.get("emp_code", "") or "")
    return (1, emp_code, fallback_index)

@st.cache_data(ttl=30, show_spinner=False)
def api_get_json(path):
    res = requests.get(f"{API_URL}{path}", timeout=REQUEST_TIMEOUT)
    res.raise_for_status()
    return res.json()

def clear_api_cache():
    api_get_json.clear()

def current_username():
    return st.session_state.get("emp_name") or st.session_state.get("role") or "-"

def audit_event(action, module, reference_id="", details="", username=None):
    payload = {
        "username": str(username or current_username()),
        "action": str(action),
        "module": str(module),
        "reference_id": str(reference_id or ""),
        "details": str(details or "")
    }
    try:
        requests.post(f"{API_URL}/audit-logs/", json=payload, timeout=2)
        api_get_json.clear()
    except:
        pass

def payroll_lock_status(cycle_name):
    if not cycle_name:
        return {"is_locked": False}
    try:
        return api_get_json(f"/payroll/cycles/{cycle_name}/lock-status")
    except Exception:
        return {"is_locked": False}

def render_payroll_lock_badge(lock_status):
    if lock_status.get("is_locked"):
        st.error(
            f"🔒 Payroll month is locked by {lock_status.get('locked_by') or '-'} "
            f"at {lock_status.get('locked_at') or '-'}"
        )
        if lock_status.get("lock_note"):
            st.caption(f"Lock note: {lock_status.get('lock_note')}")
    else:
        st.success("🔓 Payroll month is unlocked")

def logout_user():
    audit_event("Logout", "Authentication")
    for key in ["authenticated", "role", "emp_code", "emp_name"]:
        st.session_state.pop(key, None)

def employee_edit_key(emp_code, field):
    safe_code = re.sub(r"[^A-Za-z0-9_]", "_", str(emp_code))
    return f"edit_emp_{safe_code}_{field}"

def clear_employee_edit_state(emp_code):
    prefix = employee_edit_key(emp_code, "")
    for key in list(st.session_state.keys()):
        if str(key).startswith(prefix):
            st.session_state.pop(key, None)

def service_api_path(path=""):
    return f"{SERVICE_API_PREFIX}{path}"

@st.cache_data(show_spinner=False)
def read_uploaded_table(file_name, file_bytes):
    buffer = io.BytesIO(file_bytes)
    if file_name.lower().endswith(".csv"):
        return pd.read_csv(buffer)
    return pd.read_excel(buffer)

def record_log(action):
    if not st.session_state.get("authenticated"):
        return

    user_name = st.session_state.get("emp_name") or st.session_state.get("role")
    payload = {
        "user": str(user_name),
        "action": str(action),
        "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    try:
        requests.post(f"{API_URL}/logs/", json=payload, timeout=2)
        api_get_json.clear()
    except:
        pass

def round_baht(value):
    return int(Decimal(str(value or 0)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))

def sanitize_service_payload_value(value, path="service_payload"):
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            print(f"unsafe {path} = {value}; converted to 0 before service save")
            return 0
        return value
    if isinstance(value, Decimal):
        if value.is_nan() or value.is_infinite():
            print(f"unsafe {path} = {value}; converted to 0 before service save")
            return 0
        return float(value)
    if isinstance(value, dict):
        return {
            key: sanitize_service_payload_value(item, f"{path}.{key}")
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [
            sanitize_service_payload_value(item, f"{path}[{index}]")
            for index, item in enumerate(value)
        ]
    if hasattr(value, "item") and value.__class__.__module__.split(".", 1)[0] in {"numpy", "pandas"}:
        try:
            return sanitize_service_payload_value(value.item(), path)
        except Exception:
            print(f"unsafe {path} = {type(value).__name__}; converted to 0 before service save")
            return 0
    try:
        if value is not None and pd.isna(value):
            print(f"unsafe {path} = {value}; converted to 0 before service save")
            return 0
    except Exception:
        pass
    return value

def service_month_label(item):
    return f"{item['month']}-{item['year']}"

def service_total_signature(employee_pool, actual_paid):
    employee_pool = round_baht(employee_pool)
    actual_paid = round_baht(actual_paid)
    return {
        "employee_pool": employee_pool,
        "actual_employee_paid": actual_paid,
        "balance_returned_to_resort": round_baht(employee_pool - actual_paid),
    }

def service_summary_signature(summary):
    return {
        "employee_pool": round_baht(summary.get("employee_pool", 0)),
        "actual_employee_paid": round_baht(summary.get("actual_employee_paid", 0)),
        "balance_returned_to_resort": round_baht(summary.get("balance_returned_to_resort", 0)),
    }

def assert_service_total_consistency(preview_totals, saved_summary, reloaded_summary=None):
    saved_totals = service_summary_signature(saved_summary)
    if preview_totals != saved_totals:
        raise ValueError(f"Preview totals {preview_totals} do not match saved totals {saved_totals}")
    if reloaded_summary is not None:
        reloaded_totals = service_summary_signature(reloaded_summary)
        if preview_totals != reloaded_totals:
            raise ValueError(f"Preview totals {preview_totals} do not match reloaded totals {reloaded_totals}")

def service_row_total_after_deduction(row):
    # Mirror the backend Service Charge total helper. Calculation, reports,
    # cash preparation, JV, and slips must not invent separate total formulas.
    if "total_after_deduction" in row:
        return round_baht(row.get("total_after_deduction", 0))
    deduction_amount = (
        round_baht(row.get("sick_deduction", 0))
        + round_baht(row.get("leave_day_deduction", 0))
        + round_baht(row.get("leave_hour_deduction", 0))
        + round_baht(row.get("late_deduction", 0))
        + round_baht(row.get("evaluation_deduction", 0))
    )
    if "gross_service" in row:
        gross_service = round_baht(row.get("gross_service", 0))
        return max(0, gross_service - min(gross_service, deduction_amount))
    return round_baht(row.get("net_service", 0)) + round_baht(row.get("deposit_deduction", 0))

def recalculate_service_rows(rows, service_rate):
    # Frontend preview uses the same deduction cap order as main.calculate_service_amounts.
    # Save/reload validation expects these totals to match the backend exactly.
    recalculated = []
    for row in rows:
        service_weight = float(row.get("service_weight", 0) or 0)
        sick_days = float(row.get("sick_days", 0) or 0)
        leave_days = float(row.get("leave_days", 0) or 0)
        leave_hours = float(row.get("leave_hours", 0) or 0)
        late_hours = float(row.get("late_hours", 0) or 0)
        evaluation_percent = float(row.get("evaluation_percent", 0) or 0)
        deposit_deduction = round_baht(row.get("deposit_deduction", 0))
        prior_deposit_total = round_baht(row.get("prior_deposit_total", 0))
        service_type = str(row.get("service_type", "AUTO") or "AUTO").upper()
        if service_type != "AUTO" or service_weight <= 0 or prior_deposit_total >= 1500:
            deposit_deduction = 0
        else:
            deposit_deduction = min(deposit_deduction, 1500 - prior_deposit_total)
        gross_service = round_baht(service_rate * service_weight)
        sick_deduction = round_baht(gross_service / 30 * sick_days)
        leave_day_deduction = round_baht(gross_service / 30 * leave_days)
        leave_hour_deduction = round_baht(gross_service / 30 / 8 * leave_hours)
        late_deduction = round_baht(gross_service * late_hours * 0.10) if late_hours <= 5 else gross_service
        evaluation_deduction = round_baht(gross_service * evaluation_percent / 100)
        raw_deduction_total = sick_deduction + leave_day_deduction + leave_hour_deduction + late_deduction + evaluation_deduction
        applied_deduction = min(gross_service, raw_deduction_total)
        total_after_deduction = max(0, round_baht(gross_service - applied_deduction))
        if total_after_deduction <= 0:
            deposit_deduction = 0
        else:
            deposit_deduction = min(deposit_deduction, total_after_deduction)
        net_service = max(0, round_baht(total_after_deduction - deposit_deduction))
        new_row = dict(row)
        new_row.update({
            "service_rate": float(service_rate or 0),
            "gross_service": gross_service,
            "sick_days": sick_days,
            "leave_days": leave_days,
            "leave_day_deduction": leave_day_deduction,
            "sick_deduction": sick_deduction,
            "leave_hours": leave_hours,
            "leave_hour_deduction": leave_hour_deduction,
            "late_hours": late_hours,
            "late_deduction": late_deduction,
            "evaluation_percent": evaluation_percent,
            "evaluation_deduction": evaluation_deduction,
            "deduction_amount": applied_deduction,
            "total_after_deduction": total_after_deduction,
            "deduction_capped": raw_deduction_total > gross_service,
            "deposit_deduction": deposit_deduction,
            "net_service": net_service,
            "notes": row.get("notes", "")
        })
        recalculated.append(new_row)
    return recalculated

def service_distribution_summary(rows):
    distribution = {}
    for row in rows:
        amount = round_baht(row.get("net_service", 0))
        distribution[amount] = distribution.get(amount, 0) + 1
    return [{"Net Service Amount": amount, "Employee Count": count} for amount, count in sorted(distribution.items(), reverse=True)]

def service_cash_report(total_amount):
    remaining = round_baht(total_amount)
    rows = []
    for denom in [1000, 500, 100, 50, 20]:
        qty = remaining // denom
        amount = qty * denom
        rows.append({"Denomination": denom, "Quantity": qty, "Amount": amount})
        remaining -= amount
    rows.append({"Denomination": "coins/remainder", "Quantity": remaining, "Amount": remaining})
    return rows

def format_baht(value):
    return f"{round_baht(value):,.0f}"

def service_report_rates(rows, summary):
    service_rate = float(summary.get("service_rate", 0) or summary.get("calculated_service_rate", 0) or 0)
    if service_rate > 0:
        full_rate = round_baht(service_rate)
        return round_baht(full_rate * 0.50), full_rate
    derived_rates = []
    for row in rows:
        service_percent = float(row.get("service_percent", 0) or 0)
        gross_amount = round_baht(row.get("gross_service_amount", row.get("income_amount", 0)))
        if service_percent > 0 and gross_amount > 0:
            derived_rates.append(gross_amount / (service_percent / 100.0))
    full_rate = round_baht(derived_rates[0]) if derived_rates else round_baht(summary.get("service_rate", 0))
    return round_baht(full_rate * 0.50), full_rate

def service_detail_report_html(reports, selected_month):
    rows = reports.get("service_detail", [])
    summary = reports.get("summary", {})
    half_rate, full_rate = service_report_rates(rows, summary)
    title = f"Service Charge {selected_month['month']} {selected_month['year']}"
    printed_at = datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    columns = [
        ("no", "No."),
        ("name", "Name/Surname"),
        ("position", "Position"),
        ("start_date", "Starting Date"),
        ("service_percent", "Service %"),
        ("income_amount", "Income Amount"),
        ("deduction_amount", "Deduction Amount"),
        ("total_after_deduction", "Total After Deduction"),
        ("deposit_refund", "Deposit Refund"),
        ("deposit_deduction", "Deposit Deduction"),
        ("net_service", "Net Service"),
        ("remarks", "Remarks")
    ]
    numeric_columns = [
        "income_amount", "deduction_amount", "total_after_deduction",
        "deposit_refund", "deposit_deduction", "net_service"
    ]
    total_fields = numeric_columns

    grouped = {}
    for row in rows:
        grouped.setdefault(row.get("department") or "ไม่ระบุแผนก", []).append(row)

    body_rows = []
    grand_totals = {field: 0 for field in total_fields}
    employee_no = 1
    for department in ordered_department_names(grouped):
        dept_fallback_order = {id(row): index for index, row in enumerate(grouped[department])}
        dept_rows = sorted(
            grouped[department],
            key=lambda row: employee_report_order_key(row, dept_fallback_order.get(id(row), 0)),
        )
        body_rows.append(f"<tr class='dept-row'><td colspan='{len(columns)}'>แผนก: {html.escape(str(department))}</td></tr>")
        dept_totals = {field: 0 for field in total_fields}
        for row in dept_rows:
            name = " ".join([str(row.get("first_name", "") or ""), str(row.get("last_name", "") or "")]).strip()
            cells = []
            for key, _label in columns:
                if key == "no":
                    cells.append(f"<td class='center'>{employee_no}</td>")
                elif key == "name":
                    cells.append(f"<td>{html.escape(name)}</td>")
                elif key == "service_percent":
                    cells.append(f"<td class='num'>{format_baht(row.get(key, 0))}%</td>")
                elif key in numeric_columns:
                    cells.append(f"<td class='num'>{format_baht(row.get(key, 0))}</td>")
                else:
                    cells.append(f"<td>{html.escape(str(row.get(key, '') or ''))}</td>")
            body_rows.append("<tr>" + "".join(cells) + "</tr>")
            for field in total_fields:
                dept_totals[field] += round_baht(row.get(field, 0))
                grand_totals[field] += round_baht(row.get(field, 0))
            employee_no += 1

        subtotal_cells = []
        for key, _label in columns:
            if key == "name":
                subtotal_cells.append(f"<td class='subtotal-label'>TOTAL {html.escape(str(department))} ({len(dept_rows)} คน)</td>")
            elif key in total_fields:
                subtotal_cells.append(f"<td class='num subtotal'>{format_baht(dept_totals[key])}</td>")
            elif key == "no":
                subtotal_cells.append("<td></td>")
            else:
                subtotal_cells.append("<td></td>")
        body_rows.append("<tr class='subtotal-row'>" + "".join(subtotal_cells) + "</tr>")

    grand_cells = []
    for key, _label in columns:
        if key == "name":
            grand_cells.append(f"<td class='subtotal-label'>GRAND TOTAL ({len(rows)} คน)</td>")
        elif key in total_fields:
            grand_cells.append(f"<td class='num subtotal'>{format_baht(grand_totals[key])}</td>")
        elif key == "no":
            grand_cells.append("<td></td>")
        else:
            grand_cells.append("<td></td>")

    header_cells = "".join(f"<th>{html.escape(label)}</th>" for _key, label in columns)
    signature_html = (
        '<div class="signature-row">'
        '<div>_________________<br>Prepared By (HR)</div>'
        '<div>_________________<br>Checked By (ACC)</div>'
        '<div>_________________<br>Checked By (GM)</div>'
        '<div>_________________<br>Approved By (VP)</div>'
        '<div>_________________<br>Authorized By (President)</div>'
        '</div>'
    )
    return f"""<style>
        .service-print-actions {{
            margin: 0.5rem 0 1rem 0;
        }}
        .service-report-print-btn {{
            border: 1px solid #2f6f5e;
            background: #2f6f5e;
            color: white;
            padding: 0.45rem 0.8rem;
            border-radius: 6px;
            cursor: pointer;
            font-size: 0.95rem;
        }}
        .service-report {{
            background: white;
            color: #111;
            padding: 18px;
            border: 1px solid #d8d8d8;
            overflow-x: auto;
            font-family: Arial, sans-serif;
        }}
        .service-report h2 {{
            margin: 0;
            font-size: 22px;
            letter-spacing: 0;
        }}
        .service-report h3 {{
            margin: 2px 0 4px 0;
            font-size: 17px;
            font-weight: 500;
        }}
        .service-report .printed {{
            font-size: 12px;
            margin-bottom: 10px;
        }}
        .service-detail-table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 11px;
        }}
        .service-detail-table th,
        .service-detail-table td {{
            border-bottom: 1px solid #e2e2e2;
            padding: 5px 4px;
            vertical-align: top;
        }}
        .service-detail-table th {{
            border-top: 1px solid #111;
            border-bottom: 1px solid #111;
            text-align: left;
            font-weight: 700;
        }}
        .service-detail-table .num {{
            text-align: right;
            white-space: nowrap;
        }}
        .service-detail-table .center {{
            text-align: center;
        }}
        .dept-row td {{
            font-weight: 700;
            background: #f3f6f5;
            border-top: 1px solid #777;
        }}
        .subtotal-row td {{
            font-weight: 700;
            border-top: 1px solid #999;
            border-bottom: 1px solid #999;
        }}
        .grand-total td {{
            font-weight: 700;
            border-top: 2px solid #111;
            border-bottom: 3px double #111;
        }}
        .summary-block {{
            margin-top: 18px;
            font-size: 13px;
            line-height: 1.7;
        }}
        .signature-row {{
            display: grid;
            grid-template-columns: repeat(5, 1fr);
            gap: 12px;
            margin-top: 70px;
            text-align: center;
            font-size: 12px;
        }}
        @media print {{
            body * {{
                visibility: hidden;
            }}
            .service-report, .service-report * {{
                visibility: visible;
            }}
            .service-report {{
                position: absolute;
                left: 0;
                top: 0;
                width: 100%;
                border: 0;
                padding: 0;
                overflow: visible;
            }}
            .service-print-actions {{
                display: none;
            }}
            @page {{
                size: A4 landscape;
                margin: 10mm;
            }}
        }}
    </style>
    <div class="service-print-actions">
        <button class="service-report-print-btn" onclick="window.print()">Print Service Detail Report</button>
    </div>
    <div class="service-report">
        <h2>AONANG FIORE RESORT</h2>
        <h3>{html.escape(title)}</h3>
        <div class="printed">Printed Date: {html.escape(printed_at)}</div>
        <table class="service-detail-table">
            <thead><tr>{header_cells}</tr></thead>
            <tbody>
                {''.join(body_rows)}
                <tr class="grand-total">{''.join(grand_cells)}</tr>
            </tbody>
        </table>
        <div class="summary-block">
            <div>50% Service Rate: {format_baht(half_rate)} Baht</div>
            <div>100% Service Rate: {format_baht(full_rate)} Baht</div>
            <div>Total Employees: {len(rows)}</div>
            <div>Actual Employee Paid: {format_baht(summary.get('actual_employee_paid', grand_totals['net_service']))} Baht</div>
        </div>
        {signature_html}
    </div>"""

def render_service_detail_report(reports, selected_month):
    report_html = service_detail_report_html(reports, selected_month)
    components.html(report_html, height=900, scrolling=True)

def service_report_signature_html():
    return (
        '<div class="signature-row">'
        '<div>_________________<br>Prepared By (HR)</div>'
        '<div>_________________<br>Checked By (ACC)</div>'
        '<div>_________________<br>Checked By (GM)</div>'
        '<div>_________________<br>Approved By (VP)</div>'
        '<div>_________________<br>Authorized By (President)</div>'
        '</div>'
    )

def service_summary_report_html(summary_report):
    rows = summary_report.get("rows", [])
    total = summary_report.get("yearly_total", {})
    year = summary_report.get("year", "")
    title = f"Service Charge Summary {year}"
    printed_at = datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    columns = [
        ("month", "Month"),
        ("room_revenue", "Room Revenue"),
        ("fb_revenue", "F&B Revenue"),
        ("zipline_revenue", "Zipline Revenue"),
        ("other_revenue", "Other Revenue"),
        ("total_revenue", "Total Revenue"),
        ("service_charge_10", "Service Charge 10%"),
        ("employee_pool", "Employee Pool (60%)"),
        ("actual_employee_paid", "Actual Employee Paid"),
        ("welfare_fund", "Welfare Fund (20%)"),
        ("employee_deposit_total", "Employee Deposit Total"),
        ("resort_fund", "Resort Fund (20%)")
    ]
    numeric_columns = {key for key, _label in columns if key != "month"}
    header_cells = "".join(f"<th>{html.escape(label)}</th>" for _key, label in columns)
    body_rows = []
    for row in rows:
        cells = []
        for key, _label in columns:
            if key in numeric_columns:
                cells.append(f"<td class='num'>{format_baht(row.get(key, 0))}</td>")
            else:
                cells.append(f"<td>{html.escape(str(row.get(key, '') or ''))}</td>")
        body_rows.append("<tr>" + "".join(cells) + "</tr>")

    total_cells = []
    for key, _label in columns:
        if key == "month":
            total_cells.append("<td class='subtotal-label'>Yearly Total</td>")
        elif key in numeric_columns:
            total_cells.append(f"<td class='num subtotal'>{format_baht(total.get(key, 0))}</td>")
        else:
            total_cells.append("<td></td>")

    return f"""<style>
        .service-print-actions {{
            margin: 0.5rem 0 1rem 0;
        }}
        .service-report-print-btn {{
            border: 1px solid #2f6f5e;
            background: #2f6f5e;
            color: white;
            padding: 0.45rem 0.8rem;
            border-radius: 6px;
            cursor: pointer;
            font-size: 0.95rem;
        }}
        .service-report {{
            background: white;
            color: #111;
            padding: 18px;
            border: 1px solid #d8d8d8;
            overflow-x: auto;
            font-family: Arial, sans-serif;
        }}
        .service-report h2 {{
            margin: 0;
            font-size: 22px;
            letter-spacing: 0;
        }}
        .service-report h3 {{
            margin: 2px 0 4px 0;
            font-size: 17px;
            font-weight: 500;
        }}
        .service-report .printed {{
            font-size: 12px;
            margin-bottom: 10px;
        }}
        .service-summary-table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 11px;
        }}
        .service-summary-table th,
        .service-summary-table td {{
            border-bottom: 1px solid #e2e2e2;
            padding: 5px 4px;
            vertical-align: top;
        }}
        .service-summary-table th {{
            border-top: 1px solid #111;
            border-bottom: 1px solid #111;
            text-align: left;
            font-weight: 700;
        }}
        .service-summary-table .num {{
            text-align: right;
            white-space: nowrap;
        }}
        .grand-total td {{
            font-weight: 700;
            border-top: 2px solid #111;
            border-bottom: 3px double #111;
        }}
        .signature-row {{
            display: grid;
            grid-template-columns: repeat(5, 1fr);
            gap: 12px;
            margin-top: 70px;
            text-align: center;
            font-size: 12px;
        }}
        @media print {{
            body * {{
                visibility: hidden;
            }}
            .service-report, .service-report * {{
                visibility: visible;
            }}
            .service-report {{
                position: absolute;
                left: 0;
                top: 0;
                width: 100%;
                border: 0;
                padding: 0;
                overflow: visible;
            }}
            .service-print-actions {{
                display: none;
            }}
            @page {{
                size: A4 landscape;
                margin: 10mm;
            }}
        }}
    </style>
    <div class="service-print-actions">
        <button class="service-report-print-btn" onclick="window.print()">Print Service Summary Report</button>
    </div>
    <div class="service-report">
        <h2>AONANG FIORE RESORT</h2>
        <h3>{html.escape(title)}</h3>
        <div class="printed">Printed Date: {html.escape(printed_at)}</div>
        <table class="service-summary-table">
            <thead><tr>{header_cells}</tr></thead>
            <tbody>
                {''.join(body_rows)}
                <tr class="grand-total">{''.join(total_cells)}</tr>
            </tbody>
        </table>
        {service_report_signature_html()}
    </div>"""

def render_service_summary_report(summary_report):
    report_html = service_summary_report_html(summary_report)
    components.html(report_html, height=760, scrolling=True)

def cash_preparation_report_html(reports, selected_month):
    distribution_rows = reports.get("distribution_summary", [])
    cash_rows = reports.get("cash_preparation", [])
    total_employees = reports.get("total_employees", 0)
    grand_total = round_baht(reports.get("cash_grand_total", 0))
    title = f"Cash Preparation Report - Service Charge {selected_month['month']} {selected_month['year']}"
    printed_at = datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S")

    distribution_body = []
    for row in distribution_rows:
        amount = round_baht(row.get("Net Service Amount", 0))
        count = int(row.get("Employee Count", 0) or 0)
        total_amount = round_baht(row.get("Total Amount", amount * count))
        distribution_body.append(
            "<tr>"
            f"<td class='num'>{format_baht(amount)}</td>"
            f"<td class='num'>{count:,}</td>"
            f"<td class='num'>{format_baht(total_amount)}</td>"
            "</tr>"
        )

    cash_body = []
    for row in cash_rows:
        denomination = row.get("Denomination", "")
        label = "Coins / remainder" if str(denomination).lower() == "coins/remainder" else str(denomination)
        cash_body.append(
            "<tr>"
            f"<td>{html.escape(label)}</td>"
            f"<td class='num'>{format_baht(row.get('Quantity', 0))}</td>"
            f"<td class='num'>{format_baht(row.get('Amount', 0))}</td>"
            "</tr>"
        )

    return f"""<style>
        .service-print-actions {{
            margin: 0.5rem 0 1rem 0;
        }}
        .service-report-print-btn {{
            border: 1px solid #2f6f5e;
            background: #2f6f5e;
            color: white;
            padding: 0.45rem 0.8rem;
            border-radius: 6px;
            cursor: pointer;
            font-size: 0.95rem;
        }}
        .service-report {{
            background: white;
            color: #111;
            padding: 18px;
            border: 1px solid #d8d8d8;
            overflow-x: auto;
            font-family: Arial, sans-serif;
        }}
        .service-report h2 {{
            margin: 0;
            font-size: 22px;
            letter-spacing: 0;
        }}
        .service-report h3 {{
            margin: 2px 0 4px 0;
            font-size: 17px;
            font-weight: 500;
        }}
        .service-report h4 {{
            margin: 0 0 6px 0;
            font-size: 14px;
        }}
        .service-report .printed {{
            font-size: 12px;
            margin-bottom: 10px;
        }}
        .cash-report-grid {{
            display: grid;
            grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
            gap: 14px;
            align-items: start;
            page-break-inside: avoid;
            break-inside: avoid;
        }}
        .cash-report-panel {{
            border: 1px solid #d4d4d4;
            padding: 10px;
            page-break-inside: avoid;
            break-inside: avoid;
            min-width: 0;
        }}
        .cash-report-table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 11px;
        }}
        .cash-report-table th,
        .cash-report-table td {{
            border-bottom: 1px solid #e2e2e2;
            padding: 5px 4px;
            vertical-align: top;
            page-break-inside: avoid;
            break-inside: avoid;
        }}
        .cash-report-table th {{
            border-top: 1px solid #111;
            border-bottom: 1px solid #111;
            text-align: left;
            font-weight: 700;
        }}
        .cash-report-table tr {{
            page-break-inside: avoid;
            break-inside: avoid;
        }}
        .cash-report-table .num {{
            text-align: right;
            white-space: nowrap;
        }}
        .grand-total td {{
            font-weight: 700;
            border-top: 2px solid #111;
            border-bottom: 3px double #111;
        }}
        .summary-block {{
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 12px;
            margin-top: 14px;
            padding-top: 8px;
            border-top: 1px solid #777;
            font-size: 13px;
            line-height: 1.7;
            page-break-inside: avoid;
            break-inside: avoid;
        }}
        .signature-row {{
            display: grid;
            grid-template-columns: repeat(5, 1fr);
            gap: 12px;
            margin-top: 46px;
            text-align: center;
            font-size: 12px;
            page-break-inside: avoid;
            break-inside: avoid;
        }}
        @media print {{
            body * {{
                visibility: hidden;
            }}
            .service-report, .service-report * {{
                visibility: visible;
            }}
            .service-report {{
                position: absolute;
                left: 0;
                top: 0;
                width: 100%;
                border: 0;
                padding: 0;
                overflow: visible;
            }}
            .service-print-actions {{
                display: none;
            }}
            .cash-report-grid,
            .cash-report-panel,
            .summary-block,
            .signature-row,
            .grand-total {{
                page-break-inside: avoid;
                break-inside: avoid;
            }}
            @page {{
                size: A4 landscape;
                margin: 10mm;
            }}
        }}
    </style>
    <div class="service-print-actions">
        <button class="service-report-print-btn" onclick="window.print()">Print Cash Preparation Report</button>
    </div>
    <div class="service-report">
        <h2>AONANG FIORE RESORT</h2>
        <h3>{html.escape(title)}</h3>
        <div class="printed">Printed Date: {html.escape(printed_at)}</div>

        <div class="cash-report-grid">
            <section class="cash-report-panel">
                <h4>Service Amount Distribution</h4>
                <table class="cash-report-table">
                    <thead>
                        <tr>
                            <th>Net Service Amount</th>
                            <th>Employee Count</th>
                            <th>Total Amount</th>
                        </tr>
                    </thead>
                    <tbody>
                        {''.join(distribution_body)}
                        <tr class="grand-total">
                            <td>Total</td>
                            <td class="num">{int(total_employees or 0):,}</td>
                            <td class="num">{format_baht(grand_total)}</td>
                        </tr>
                    </tbody>
                </table>
            </section>

            <section class="cash-report-panel">
                <h4>Cash Denomination Summary</h4>
                <table class="cash-report-table">
                    <thead>
                        <tr>
                            <th>Denomination</th>
                            <th>Quantity</th>
                            <th>Amount</th>
                        </tr>
                    </thead>
                    <tbody>
                        {''.join(cash_body)}
                        <tr class="grand-total">
                            <td>Grand Total</td>
                            <td></td>
                            <td class="num">{format_baht(grand_total)}</td>
                        </tr>
                    </tbody>
                </table>
            </section>
        </div>

        <div class="summary-block">
            <div>Total Employees: {int(total_employees or 0):,}</div>
            <div>Grand Total: {format_baht(grand_total)} Baht</div>
        </div>
        {service_report_signature_html()}
    </div>"""

def render_cash_preparation_report(reports, selected_month):
    report_html = cash_preparation_report_html(reports, selected_month)
    components.html(report_html, height=820, scrolling=True)

def monthly_jv_report_html(reports, selected_month):
    jv_report = reports.get("monthly_jv", {})
    rows = jv_report.get("rows", [])
    total_debit = round_baht(jv_report.get("total_debit", 0))
    total_credit = round_baht(jv_report.get("total_credit", 0))
    net_total = round_baht(jv_report.get("net", total_debit - total_credit))
    is_balanced = bool(jv_report.get("is_balanced", total_debit == total_credit))
    title = f"Monthly JV Report - Service Charge {selected_month['month']} {selected_month['year']}"
    printed_at = datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S")

    body_rows = []
    for row in rows:
        body_rows.append(
            "<tr>"
            f"<td>{html.escape(str(row.get('acc_no', '') or ''))}</td>"
            f"<td>{html.escape(str(row.get('name', '') or ''))}</td>"
            f"<td class='num'>{format_baht(row.get('debit', 0))}</td>"
            f"<td class='num'>{format_baht(row.get('credit', 0))}</td>"
            f"<td class='num'>{format_baht(row.get('net', 0))}</td>"
            "</tr>"
        )

    balance_class = "balanced" if is_balanced else "unbalanced"
    balance_text = "Debit and Credit are balanced." if is_balanced else "Warning: Total Debit does not equal Total Credit."
    return f"""<style>
        .service-print-actions {{
            margin: 0.5rem 0 1rem 0;
        }}
        .service-report-print-btn {{
            border: 1px solid #2f6f5e;
            background: #2f6f5e;
            color: white;
            padding: 0.45rem 0.8rem;
            border-radius: 6px;
            cursor: pointer;
            font-size: 0.95rem;
        }}
        .service-report {{
            background: white;
            color: #111;
            padding: 18px;
            border: 1px solid #d8d8d8;
            overflow-x: auto;
            font-family: Arial, sans-serif;
        }}
        .service-report h2 {{
            margin: 0;
            font-size: 22px;
            letter-spacing: 0;
        }}
        .service-report h3 {{
            margin: 2px 0 4px 0;
            font-size: 17px;
            font-weight: 500;
        }}
        .service-report .printed {{
            font-size: 12px;
            margin-bottom: 10px;
        }}
        .jv-table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 12px;
        }}
        .jv-table th,
        .jv-table td {{
            border-bottom: 1px solid #e2e2e2;
            padding: 7px 6px;
            vertical-align: top;
        }}
        .jv-table th {{
            border-top: 1px solid #111;
            border-bottom: 1px solid #111;
            text-align: left;
            font-weight: 700;
        }}
        .jv-table .num {{
            text-align: right;
            white-space: nowrap;
        }}
        .grand-total td {{
            font-weight: 700;
            border-top: 2px solid #111;
            border-bottom: 3px double #111;
        }}
        .jv-balance {{
            margin-top: 14px;
            padding: 9px 10px;
            border: 1px solid #777;
            font-size: 13px;
        }}
        .jv-balance.unbalanced {{
            border-color: #b91c1c;
            color: #7f1d1d;
            background: #fef2f2;
            font-weight: 700;
        }}
        .jv-balance.balanced {{
            border-color: #2f6f5e;
            color: #164e3f;
            background: #f0f8f5;
        }}
        .signature-row {{
            display: grid;
            grid-template-columns: repeat(5, 1fr);
            gap: 12px;
            margin-top: 70px;
            text-align: center;
            font-size: 12px;
        }}
        @media print {{
            body * {{
                visibility: hidden;
            }}
            .service-report, .service-report * {{
                visibility: visible;
            }}
            .service-report {{
                position: absolute;
                left: 0;
                top: 0;
                width: 100%;
                border: 0;
                padding: 0;
                overflow: visible;
            }}
            .service-print-actions {{
                display: none;
            }}
            @page {{
                size: A4 portrait;
                margin: 12mm;
            }}
        }}
    </style>
    <div class="service-print-actions">
        <button class="service-report-print-btn" onclick="window.print()">Print Monthly JV Report</button>
    </div>
    <div class="service-report">
        <h2>AONANG FIORE RESORT</h2>
        <h3>{html.escape(title)}</h3>
        <div class="printed">Printed Date: {html.escape(printed_at)}</div>
        <table class="jv-table">
            <thead>
                <tr>
                    <th>ACC NO.</th>
                    <th>NAME</th>
                    <th>DEBIT</th>
                    <th>CREDIT</th>
                    <th>NET</th>
                </tr>
            </thead>
            <tbody>
                {''.join(body_rows)}
                <tr class="grand-total">
                    <td></td>
                    <td>Total</td>
                    <td class="num">{format_baht(total_debit)}</td>
                    <td class="num">{format_baht(total_credit)}</td>
                    <td class="num">{format_baht(net_total)}</td>
                </tr>
            </tbody>
        </table>
        <div class="jv-balance {balance_class}">{html.escape(balance_text)}</div>
        {service_report_signature_html()}
    </div>"""

def render_monthly_jv_report(reports, selected_month):
    report_html = monthly_jv_report_html(reports, selected_month)
    components.html(report_html, height=760, scrolling=True)

def service_slip_v2_html(slips, title_suffix="", print_all=False):
    if isinstance(slips, dict):
        slips = [slips]
    slips = slips or []
    printed_at = datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    button_label = "Print All Slips" if print_all else "Print Slip"

    def money(value):
        return format_baht(value)

    def number(value):
        try:
            value = float(value or 0)
            return f"{value:,.2f}".rstrip("0").rstrip(".")
        except Exception:
            return "0"

    def service_month_text(slip):
        return slip.get("service_month") or f"{slip.get('month', '')}-{slip.get('year', '')}".strip("-")

    slip_blocks = []
    for slip in slips:
        employee_name = " ".join([
            str(slip.get("first_name", "") or ""),
            str(slip.get("last_name", "") or ""),
        ]).strip()
        total_deductions = (
            round_baht(slip.get("sick_deduction", 0))
            + round_baht(slip.get("leave_day_deduction", 0))
            + round_baht(slip.get("leave_hour_deduction", 0))
            + round_baht(slip.get("late_deduction", 0))
            + round_baht(slip.get("evaluation_deduction", 0))
        )
        auto_remarks = slip.get("deduction_remarks") or "No deductions"
        manual_notes = str(slip.get("notes", "") or "").strip()
        late_minutes = slip.get("late_mins")
        if late_minutes in [None, ""]:
            late_minutes = round_baht(float(slip.get("late_hours", 0) or 0) * 60)

        def row(label, value, highlight=False):
            cls = " class='highlight'" if highlight else ""
            return f"<tr{cls}><td>{html.escape(label)}</td><td class='num'>{html.escape(str(value))}</td></tr>"

        calculation_rows = "".join([
            row("Service Weight", number(slip.get("service_weight", 0))),
            row("Service Rate", money(slip.get("service_rate", 0))),
            row("Gross Service", money(slip.get("gross_service", 0)), True),
        ])
        deduction_rows = "".join([
            row("Sick Leave Deduction", money(slip.get("sick_deduction", 0))),
            row("Leave Day Deduction", money(slip.get("leave_day_deduction", 0))),
            row("Leave Hour Deduction", money(slip.get("leave_hour_deduction", 0))),
            row("Late Deduction", money(slip.get("late_deduction", 0))),
            row("Evaluation Deduction", money(slip.get("evaluation_deduction", 0))),
            row("Deposit Deduction", money(slip.get("deposit_deduction", 0))),
        ])
        summary_rows = "".join([
            row("Total After Deduction", money(slip.get("total_after_deduction", round_baht(slip.get("gross_service", 0)) - total_deductions))),
            row("Deposit Deduction", money(slip.get("deposit_deduction", 0))),
            row("Deposit Refund", money(slip.get("deposit_refund", 0))),
            row("Net Service", money(slip.get("net_service", 0)), True),
        ])
        attendance_rows = "".join([
            row("Sick Days", number(slip.get("sick_days", 0))),
            row("Leave Days", number(slip.get("leave_days", 0))),
            row("Leave Hours", number(slip.get("leave_hours", 0))),
            row("Late Minutes", number(late_minutes)),
            row("Evaluation %", f"{number(slip.get('evaluation_percent', 0))}%"),
        ])

        slip_blocks.append(f"""
        <section class="service-slip-page">
            <header class="slip-header">
                <div>
                    <h2>AONANG FIORE RESORT</h2>
                    <h1>SERVICE CHARGE SLIP</h1>
                </div>
                <div class="slip-month">
                    <span>Service Month</span>
                    <strong>{html.escape(service_month_text(slip))}</strong>
                </div>
            </header>
            <div class="employee-grid">
                <div><span>Employee Code</span><strong>{html.escape(str(slip.get('emp_code', '') or ''))}</strong></div>
                <div><span>Employee Name</span><strong>{html.escape(employee_name)}</strong></div>
                <div><span>Department</span><strong>{html.escape(str(slip.get('department', '') or '-'))}</strong></div>
            </div>
            <div class="slip-grid">
                <section>
                    <h3>Calculation</h3>
                    <table>{calculation_rows}</table>
                </section>
                <section>
                    <h3>Deductions</h3>
                    <table>{deduction_rows}</table>
                </section>
                <section>
                    <h3>Summary</h3>
                    <table>{summary_rows}</table>
                </section>
                <section>
                    <h3>Attendance</h3>
                    <table>{attendance_rows}</table>
                </section>
            </div>
            <section class="remarks">
                <h3>Remarks</h3>
                <div><strong>Auto-generated attendance remarks:</strong> {html.escape(auto_remarks)}</div>
                <div><strong>HR manual notes:</strong> {html.escape(manual_notes if manual_notes else "-")}</div>
            </section>
            <footer class="slip-signature">
                <div>
                    <span>Employee Signature</span>
                    <strong>____________________________</strong>
                </div>
                <div>
                    <span>Date</span>
                    <strong>____________________________</strong>
                </div>
            </footer>
        </section>""")

    return f"""<style>
        .service-slip-actions {{
            margin: 0.5rem 0 1rem 0;
        }}
        .service-slip-print-btn {{
            border: 1px solid #2f6f5e;
            background: #2f6f5e;
            color: white;
            padding: 0.5rem 0.9rem;
            border-radius: 6px;
            cursor: pointer;
            font-size: 0.95rem;
        }}
        .service-slip-print-area {{
            background: #f5f6f4;
            padding: 12px;
            color: #111;
            font-family: Arial, sans-serif;
        }}
        .service-slip-page {{
            background: white;
            border: 1px solid #d7d7d7;
            padding: 22px;
            margin: 0 auto 16px auto;
            max-width: 920px;
            page-break-after: always;
        }}
        .service-slip-page:last-child {{
            page-break-after: auto;
        }}
        .slip-header {{
            display: flex;
            justify-content: space-between;
            gap: 18px;
            align-items: flex-start;
            border-bottom: 3px solid #2f6f5e;
            padding-bottom: 12px;
        }}
        .slip-header h2 {{
            margin: 0;
            font-size: 22px;
            letter-spacing: 0;
            color: #2f6f5e;
        }}
        .slip-header h1 {{
            margin: 4px 0 0 0;
            font-size: 18px;
            letter-spacing: 0;
        }}
        .slip-month {{
            text-align: right;
            font-size: 12px;
        }}
        .slip-month span,
        .employee-grid span,
        .slip-signature span {{
            display: block;
            color: #555;
            font-size: 11px;
            margin-bottom: 3px;
        }}
        .slip-month strong {{
            font-size: 16px;
        }}
        .employee-grid {{
            display: grid;
            grid-template-columns: 1fr 2fr 2fr;
            gap: 10px;
            margin: 14px 0;
            padding: 10px;
            border: 1px solid #dddddd;
            background: #fbfbfb;
        }}
        .employee-grid strong {{
            font-size: 13px;
        }}
        .slip-grid {{
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 12px;
        }}
        .slip-grid section,
        .remarks {{
            border: 1px solid #dddddd;
            padding: 10px;
            break-inside: avoid;
            page-break-inside: avoid;
        }}
        .slip-grid h3,
        .remarks h3 {{
            margin: 0 0 7px 0;
            font-size: 13px;
            color: #2f6f5e;
        }}
        .slip-grid table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 12px;
        }}
        .slip-grid td {{
            border-bottom: 1px solid #eeeeee;
            padding: 5px 0;
        }}
        .slip-grid .num {{
            text-align: right;
            font-weight: 600;
            white-space: nowrap;
        }}
        .slip-grid tr.highlight td {{
            border-top: 1px solid #777;
            border-bottom: 2px double #777;
            font-weight: 700;
        }}
        .remarks {{
            margin-top: 12px;
            font-size: 12px;
            line-height: 1.7;
        }}
        .slip-signature {{
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 40px;
            margin-top: 48px;
            text-align: center;
            font-size: 12px;
        }}
        .printed {{
            max-width: 920px;
            margin: 0 auto 8px auto;
            font-size: 11px;
            color: #555;
            text-align: right;
        }}
        @media print {{
            body * {{
                visibility: hidden;
            }}
            .service-slip-print-area, .service-slip-print-area * {{
                visibility: visible;
            }}
            .service-slip-print-area {{
                position: absolute;
                left: 0;
                top: 0;
                width: 100%;
                background: white;
                padding: 0;
            }}
            .service-slip-actions {{
                display: none;
            }}
            .service-slip-page {{
                border: 0;
                max-width: none;
                margin: 0;
                padding: 0;
            }}
            @page {{
                size: A4 portrait;
                margin: 12mm;
            }}
        }}
    </style>
    <div class="service-slip-actions">
        <button class="service-slip-print-btn" onclick="window.print()">{html.escape(button_label)}</button>
    </div>
    <div class="service-slip-print-area">
        <div class="printed">Printed Date: {html.escape(printed_at)} {html.escape(title_suffix)}</div>
        {''.join(slip_blocks)}
    </div>"""

def render_service_slip_v2(slip):
    components.html(service_slip_v2_html(slip), height=980, scrolling=True)

def render_service_slips_v2(slips, selected_month):
    month_text = f"{selected_month.get('month', '')}-{selected_month.get('year', '')}"
    components.html(service_slip_v2_html(slips, f"| {month_text}", print_all=True), height=980, scrolling=True)

def employee_full_name(employee):
    return " ".join([
        str(employee.get("first_name", "") or ""),
        str(employee.get("last_name", "") or ""),
    ]).strip()

def employment_status_text(employee):
    return "Active" if employee.get("is_active", True) else "Resigned"

def latest_payroll_salary(emp_code):
    try:
        cycles = list(dict.fromkeys(api_get_json("/payroll/cycles")))
    except Exception:
        cycles = []
    for cycle_name in sorted(cycles, reverse=True):
        try:
            payroll_data = api_get_json(f"/payroll/{cycle_name}")
            transaction = next(
                (row for row in payroll_data.get("transactions", []) if str(row.get("emp_code")) == str(emp_code)),
                None
            )
            if transaction:
                return transaction.get("base_salary", 0), payroll_data.get("cycle_name", cycle_name)
        except Exception:
            continue
    return None, ""

DEFAULT_COMPANY_SETTINGS = {
    "logo_path": "logo.png",
    "company_thai_name": "โรงแรม อ่าวนางฟิโอเร่ รีสอร์ท แอนด์ สปา",
    "company_english_name": "Aonang Fiore Resort & Spa",
    "address": "764 หมู่ 2 ต.อ่าวนาง อ.เมือง จ.กระบี่ 81180",
    "tax_id": "3-9203-00294-00-6",
    "phone": "075-695522",
    "authorized_signer_name": "",
    "authorized_signer_position_thai": "ผู้จัดการฝ่ายบุคคล",
    "authorized_signer_position_english": "Human Resources Manager",
}

def get_company_settings():
    try:
        settings = api_get_json("/company-settings/")
    except Exception:
        settings = {}
    merged = dict(DEFAULT_COMPANY_SETTINGS)
    merged.update({key: value for key, value in settings.items() if value not in [None, ""]})
    return merged

def logo_data_uri(logo_path):
    path_value = str(logo_path or "logo.png").strip() or "logo.png"
    candidates = [path_value]
    if not os.path.isabs(path_value):
        candidates.append(os.path.join(os.getcwd(), path_value))
    for candidate in candidates:
        if os.path.exists(candidate) and os.path.isfile(candidate):
            mime_type = mimetypes.guess_type(candidate)[0] or "image/png"
            with open(candidate, "rb") as logo_file:
                encoded = base64.b64encode(logo_file.read()).decode("ascii")
            return f"data:{mime_type};base64,{encoded}"
    return ""

def thai_baht_text(value):
    value = round_baht(value)
    numbers = ["ศูนย์", "หนึ่ง", "สอง", "สาม", "สี่", "ห้า", "หก", "เจ็ด", "แปด", "เก้า"]
    positions = ["", "สิบ", "ร้อย", "พัน", "หมื่น", "แสน"]

    def read_group(group):
        group = int(group)
        if group == 0:
            return ""
        text = ""
        digits = list(map(int, str(group)))
        length = len(digits)
        for index, digit in enumerate(digits):
            pos = length - index - 1
            if digit == 0:
                continue
            if pos == 1 and digit == 1:
                text += "สิบ"
            elif pos == 1 and digit == 2:
                text += "ยี่สิบ"
            elif pos == 0 and digit == 1 and length > 1:
                text += "เอ็ด"
            else:
                text += numbers[digit] + positions[pos]
        return text

    if value == 0:
        return "ศูนย์บาทถ้วน"
    groups = []
    while value > 0:
        groups.insert(0, value % 1000000)
        value //= 1000000
    text = ""
    for index, group in enumerate(groups):
        group_text = read_group(group)
        if group_text:
            text += group_text
            if index < len(groups) - 1:
                text += "ล้าน"
    return f"{text}บาทถ้วน"

def dotted_value(value, min_width="auto"):
    return f"<span class='dynamic-value' style='min-width:{html.escape(min_width)}'>{html.escape(str(value or '-'))}</span>"

def thai_date_text(value):
    if value in [None, ""]:
        return "-"
    if hasattr(value, "strftime"):
        date_value = value
    else:
        text_value = str(value or "").strip()
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
            try:
                date_value = datetime.datetime.strptime(text_value, fmt).date()
                break
            except ValueError:
                date_value = None
        if not date_value:
            return text_value
    thai_months = [
        "มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน",
        "กรกฎาคม", "สิงหาคม", "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม",
    ]
    return f"{date_value.day} {thai_months[date_value.month - 1]} {date_value.year + 543}"

def clean_certificate_text(value, default="เพื่อใช้เป็นหลักฐาน"):
    text_value = str(value or "").strip()
    if not text_value or text_value == "-":
        return default
    if text_value.lower() in {"none", "null", "0"}:
        return default
    return text_value

def clean_addressed_to(value):
    text_value = str(value or "").strip()
    if not text_value or text_value == "-" or text_value.lower() in {"none", "null", "0", "to whom it may concern"}:
        return "ผู้เกี่ยวข้อง"
    return text_value

def should_show_addressed_to(value):
    text_value = str(value or "").strip()
    return bool(text_value and text_value != "-" and text_value != "ผู้เกี่ยวข้อง" and text_value.lower() not in {"none", "null", "0"})

def signer_display_name(value):
    text_value = str(value or "").strip()
    if not text_value or text_value.lower() in {"none", "null", "0"}:
        return "..........................................."
    return html.escape(text_value)

def hr_document_html(employee, document_type, issue_date, purpose, addressed_to, company_settings, current_salary=None, salary_source="", end_date=None):
    issue_date_text = thai_date_text(issue_date)
    start_date_text = thai_date_text(employee.get("start_date", ""))
    end_date_text = thai_date_text(end_date)
    name = employee_full_name(employee)
    status = employment_status_text(employee)
    is_salary = document_type == "Salary Certificate"
    title = "หนังสือรับรองเงินเดือน" if is_salary else "หนังสือรับรองการทำงาน"
    printed_at = datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    purpose_text = clean_certificate_text(purpose)
    addressed_text = clean_addressed_to(addressed_to)
    addressed_line = f"<br>เรียน/ถึง {dotted_value(addressed_text)}" if should_show_addressed_to(addressed_to) else ""
    company = dict(DEFAULT_COMPANY_SETTINGS)
    company.update(company_settings or {})
    logo_uri = logo_data_uri(company.get("logo_path"))
    logo_html = f"<img src='{logo_uri}' alt='Company logo'>" if logo_uri else ""
    salary_amount = round_baht(current_salary or employee.get("base_salary", 0))
    is_active_employee = bool(employee.get("is_active", True))
    period_end = end_date_text if not is_active_employee and end_date_text != "-" else "จนถึงปัจจุบัน"
    status_line = "" if is_active_employee else f" โดยมีสถานภาพการจ้างงาน {dotted_value(status)}"
    signer_name = signer_display_name(company.get("authorized_signer_name"))

    if is_salary:
        document_body = f"""
            <p>หนังสือฉบับนี้ออกให้เพื่อรับรองว่า {dotted_value(name)}
            รหัสพนักงาน {dotted_value(employee.get('emp_code', ''))} ปฏิบัติงานในตำแหน่ง {dotted_value(employee.get('position', '') or '-')}
            แผนก {dotted_value(employee.get('department', '') or '-')} เริ่มงานเมื่อวันที่ {dotted_value(start_date_text)}
            {period_end}{status_line}</p>
            <p>พนักงานดังกล่าวได้รับเงินเดือนประจำเดือนละ {dotted_value(format_baht(salary_amount))} บาท
            ({dotted_value(thai_baht_text(salary_amount))}) ซึ่งอัตรานี้ไม่รวมค่าตอบแทนและเงินพิเศษอื่น ๆ</p>
            <p>หนังสือรับรองฉบับนี้ออกให้เพื่อ {dotted_value(purpose_text)}<br>
            {addressed_line}</p>
        """
        source_line = ""
    else:
        document_body = f"""
            <p>หนังสือฉบับนี้ออกให้เพื่อรับรองว่า {dotted_value(name)}
            รหัสพนักงาน {dotted_value(employee.get('emp_code', ''))} ได้ปฏิบัติงานกับบริษัทในตำแหน่ง {dotted_value(employee.get('position', '') or '-')}
            แผนก {dotted_value(employee.get('department', '') or '-')} ตั้งแต่วันที่ {dotted_value(start_date_text)}
            ถึงวันที่ {dotted_value(period_end)}{status_line}</p>
            <p>หนังสือรับรองฉบับนี้ออกให้เพื่อ {dotted_value(purpose_text)}<br>
            {addressed_line}</p>
        """
        source_line = ""

    return f"""<style>
        .hr-doc-actions {{
            margin: 0.5rem 0 1rem 0;
        }}
        .hr-doc-print-btn {{
            border: 1px solid #2f6f5e;
            background: #2f6f5e;
            color: white;
            padding: 0.5rem 0.9rem;
            border-radius: 6px;
            cursor: pointer;
            font-size: 0.95rem;
        }}
        .hr-document {{
            background: white;
            color: #111;
            max-width: 820px;
            margin: 0 auto;
            padding: 24px 38px 26px 38px;
            border: 1px solid #d7d7d7;
            font-family: 'TH Sarabun New', 'Sarabun', Arial, sans-serif;
        }}
        .company-header {{
            display: grid;
            grid-template-columns: 112px 1fr;
            gap: 18px;
            align-items: center;
            border-bottom: 2px solid #2f6f5e;
            padding-bottom: 10px;
            margin-bottom: 12px;
        }}
        .company-header img {{
            max-width: 108px;
            max-height: 108px;
            object-fit: contain;
        }}
        .company-header h2 {{
            margin: 0;
            font-size: 22px;
            color: #2f6f5e;
            letter-spacing: 0;
        }}
        .company-header .meta {{
            margin-top: 2px;
            font-size: 19px;
            line-height: 1.25;
        }}
        .company-header .meta.secondary {{
            font-size: 16px;
            line-height: 1.3;
        }}
        .hr-document h1 {{
            text-align: center;
            margin: 16px 0 14px 0;
            font-size: 30px;
            letter-spacing: 0;
            text-decoration: underline;
        }}
        .hr-document .printed {{
            font-size: 11px;
            color: #555;
            text-align: right;
        }}
        .hr-doc-body {{
            font-size: 20px;
            line-height: 2.0;
            text-align: left;
            width: 92%;
            margin: 0 auto;
        }}
        .hr-doc-body p {{
            margin: 7px 0 10px 0;
            text-indent: 38px;
        }}
        .dynamic-value {{
            display: inline;
            border-bottom: none;
            text-decoration: none;
            font-weight: 600;
            line-height: 1.1;
            text-align: center;
            padding: 0 2px;
        }}
        .source-line {{
            margin-top: 8px;
            font-size: 12px;
            color: #666;
            text-align: right;
        }}
        .authorized-signature {{
            width: 300px;
            margin: 86px 7% 0 auto;
            text-align: center;
            font-size: 18px;
            line-height: 1.45;
        }}
        .issue-date {{
            margin: 4px 0 10px 0;
            text-align: right;
            font-size: 20px;
            width: 92%;
            margin-left: auto;
            margin-right: auto;
        }}
        @media print {{
            body * {{
                visibility: hidden;
            }}
            .hr-document, .hr-document * {{
                visibility: visible;
            }}
            .hr-document {{
                position: absolute;
                left: 0;
                top: 0;
                width: 100%;
                max-width: none;
                border: 0;
                padding: 0;
                page-break-after: avoid;
                break-after: avoid;
            }}
            .hr-doc-actions {{
                display: none;
            }}
            @page {{
                size: A4 portrait;
                margin: 14mm;
            }}
        }}
    </style>
    <div class="hr-doc-actions">
        <button class="hr-doc-print-btn" onclick="window.print()">Print</button>
    </div>
    <article class="hr-document">
        <header>
            <div class="printed">Printed Date: {html.escape(printed_at)}</div>
            <div class="company-header">
                <div>{logo_html}</div>
                <div>
                    <h2>{html.escape(str(company.get('company_thai_name', '')))}</h2>
                    <div class="meta">{html.escape(str(company.get('company_english_name', '')))}</div>
                    <div class="meta secondary">{html.escape(str(company.get('address', '')))}</div>
                    <div class="meta secondary">เลขประจำตัวผู้เสียภาษี {html.escape(str(company.get('tax_id', '')))} โทร. {html.escape(str(company.get('phone', '')))}</div>
                </div>
            </div>
            <h1>{html.escape(title)}</h1>
        </header>
        <section class="hr-doc-body">
            <div class="issue-date">วันที่ออกหนังสือ {dotted_value(issue_date_text, "160px")}</div>
            {document_body}
            <p>จึงออกหนังสือรับรองฉบับนี้ไว้เป็นหลักฐาน</p>
            {source_line}
        </section>
        <footer class="authorized-signature">
            <div>ลงชื่อ ______________________</div>
            <div>({signer_name})</div>
            <div>{html.escape(str(company.get('authorized_signer_position_thai') or ''))}</div>
            <div>{html.escape(str(company.get('authorized_signer_position_english') or ''))}</div>
        </footer>
    </article>"""

def render_hr_documents_page():
    st.title("HR Documents")
    st.caption("Generate printable employee certificates")

    try:
        employees = api_get_json("/employees/")
    except Exception as e:
        st.error(f"ไม่สามารถโหลดข้อมูลพนักงานได้: {e}")
        return

    if not employees:
        st.info("ยังไม่มีข้อมูลพนักงาน")
        return
    company_settings = get_company_settings()

    employee_options = {
        f"{emp.get('emp_code', '')} - {employee_full_name(emp)}": emp
        for emp in employees
    }
    with st.form("hr_documents_form"):
        col1, col2 = st.columns(2)
        with col1:
            selected_employee_label = st.selectbox("Select employee", list(employee_options.keys()))
            document_type = st.selectbox(
                "Select document type",
                ["Salary Certificate", "Employment Certificate / Work Certificate"],
            )
            issue_date = st.date_input("Issue date", value=datetime.date.today())
        with col2:
            addressed_to = st.text_input("Addressed to", value="")
            purpose = st.text_area("Purpose", value="", height=92)
            selected_employee = employee_options[selected_employee_label]
            end_date = None
            if not selected_employee.get("is_active", True):
                end_date = st.date_input("End date if resigned", value=datetime.date.today())

        generate_clicked = st.form_submit_button("Preview printable document", type="primary", use_container_width=True)

    if not generate_clicked:
        return

    selected_employee = employee_options[selected_employee_label]
    salary_value = selected_employee.get("base_salary", 0)
    salary_source = "Employee master"
    if document_type == "Salary Certificate":
        latest_salary, payroll_cycle = latest_payroll_salary(selected_employee.get("emp_code"))
        if latest_salary is not None:
            salary_value = latest_salary
            salary_source = f"Latest payroll cycle: {payroll_cycle}"
        audit_event("Generate Salary Certificate", "HR Documents", selected_employee.get("emp_code"), f"purpose={purpose}, addressed_to={addressed_to}")
        normalized_type = "Salary Certificate"
    else:
        audit_event("Generate Employment Certificate", "HR Documents", selected_employee.get("emp_code"), f"purpose={purpose}, addressed_to={addressed_to}")
        normalized_type = "Employment Certificate"

    st.markdown("### Preview")
    components.html(
        hr_document_html(
            selected_employee,
            normalized_type,
            issue_date,
            purpose,
            addressed_to,
            company_settings,
            current_salary=salary_value,
            salary_source=salary_source,
            end_date=end_date,
        ),
        height=920,
        scrolling=True,
    )

def render_company_settings_page():
    st.title("System > Company Settings")
    st.caption("Company profile used in HR documents and certificates")

    settings = get_company_settings()
    logo_path = st.text_input("Company logo", value=settings.get("logo_path", "logo.png"))
    logo_uri = logo_data_uri(logo_path)
    if logo_uri:
        st.image(logo_uri, width=120)
    else:
        st.info("Logo file not found. Default path can be `logo.png` in the project folder.")

    with st.form("company_settings_form"):
        company_thai_name = st.text_input("Company Thai name", value=settings.get("company_thai_name", ""))
        company_english_name = st.text_input("Company English name", value=settings.get("company_english_name", ""))
        address = st.text_area("Address", value=settings.get("address", ""), height=80)
        col1, col2 = st.columns(2)
        with col1:
            tax_id = st.text_input("Tax ID", value=settings.get("tax_id", ""))
            authorized_signer_name = st.text_input("Authorized signer name", value=settings.get("authorized_signer_name", ""))
        with col2:
            phone = st.text_input("Phone", value=settings.get("phone", ""))
            authorized_signer_position_thai = st.text_input("Authorized signer position Thai", value=settings.get("authorized_signer_position_thai", ""))
        authorized_signer_position_english = st.text_input("Authorized signer position English", value=settings.get("authorized_signer_position_english", ""))

        if st.form_submit_button("Save Company Settings", type="primary", use_container_width=True):
            payload = {
                "logo_path": logo_path,
                "company_thai_name": company_thai_name,
                "company_english_name": company_english_name,
                "address": address,
                "tax_id": tax_id,
                "phone": phone,
                "authorized_signer_name": authorized_signer_name,
                "authorized_signer_position_thai": authorized_signer_position_thai,
                "authorized_signer_position_english": authorized_signer_position_english,
                "audit_username": current_username(),
            }
            try:
                res = requests.post(f"{API_URL}/company-settings/", json=payload, timeout=REQUEST_TIMEOUT)
                if res.status_code == 200:
                    clear_api_cache()
                    st.success("Company settings updated.")
                    st.rerun()
                else:
                    st.error(f"เกิดข้อผิดพลาด: {res.text}")
            except Exception as e:
                st.error(f"ไม่สามารถบันทึก Company Settings ได้: {e}")

def render_service_setup():
    st.title("🧾 Service Charge (Beta)")
    st.caption("Service setup, calculation, and reports")

    month_options = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
    current_year = datetime.date.today().year

    try:
        service_months = api_get_json(service_api_path("/months"))
    except:
        service_months = []

    setup_tab, calculation_tab, reports_tab = st.tabs(["Service Setup", "Service Calculation", "Reports"])

    with setup_tab:
        col_month, col_year = st.columns(2)
        with col_month:
            month = st.selectbox("Month", month_options, index=datetime.date.today().month - 1, key="service_month")
        with col_year:
            year = st.selectbox("Year", [str(y) for y in range(current_year, current_year + 6)], key="service_year")

        existing = {}
        try:
            existing = api_get_json(service_api_path(f"/months/{year}/{month}"))
        except:
            existing = {}

        with st.form("service_setup_form"):
            col1, col2 = st.columns(2)
            with col1:
                room_service = st.number_input("Room Service", min_value=0.0, step=1000.0, value=float(existing.get("room_service", 0.0)))
                fb_service = st.number_input("F&B Service", min_value=0.0, step=1000.0, value=float(existing.get("fb_service", 0.0)))
            with col2:
                zipline_service = st.number_input("Zipline Service", min_value=0.0, step=1000.0, value=float(existing.get("zipline_service", 0.0)))
                other_service = st.number_input("Other Service", min_value=0.0, step=1000.0, value=float(existing.get("other_service", 0.0)))
            note = st.text_area("Note", value=existing.get("note", ""), height=80)

            total_service = room_service + fb_service + zipline_service + other_service
            st.markdown("---")
            metric1, metric2, metric3, metric4 = st.columns(4)
            with metric1: st.metric("Total Service", f"{total_service:,.2f}")
            with metric2: st.metric("Employee Pool (60%)", f"{total_service * 0.60:,.2f}")
            with metric3: st.metric("Welfare Fund (20%)", f"{total_service * 0.20:,.2f}")
            with metric4: st.metric("Resort Fund (20%)", f"{total_service * 0.20:,.2f}")

            if st.form_submit_button("💾 Save Service Setup", type="primary", use_container_width=True):
                payload = {
                    "month": month,
                    "year": int(year),
                    "room_service": room_service,
                    "fb_service": fb_service,
                    "zipline_service": zipline_service,
                    "other_service": other_service,
                    "note": note,
                    "audit_username": current_username()
                }
                try:
                    res = requests.post(f"{API_URL}{service_api_path('/months')}", json=payload, timeout=REQUEST_TIMEOUT)
                    if res.status_code == 200:
                        clear_api_cache()
                        st.success("✅ บันทึก Service Setup สำเร็จ")
                        st.rerun()
                    else:
                        st.error(f"❌ เกิดข้อผิดพลาด: {res.text}")
                except Exception as e:
                    st.error(f"❌ ไม่สามารถเชื่อมต่อระบบหลังบ้านได้: {e}")

        try:
            history = api_get_json(service_api_path("/months"))
            if history:
                st.markdown("---")
                st.subheader("Service Setup History")
                st.dataframe(pd.DataFrame(history), use_container_width=True)
        except:
            pass

    with calculation_tab:
        st.subheader("Service Calculation")
        if not service_months:
            st.info("กรุณาสร้าง Service Setup ก่อน")
        else:
            service_options = {service_month_label(item): item for item in service_months}
            selected_label = st.selectbox("Select Service Month", list(service_options.keys()), key="calc_service_month")
            selected_month = service_options[selected_label]

            manual_rate_value = selected_month.get("manual_service_rate")
            manual_rate = st.number_input(
                "Manual Service Rate Override",
                min_value=0.0,
                value=float(manual_rate_value or 0.0),
                step=100.0,
                key="manual_service_rate"
            )
            manual_rate_payload = manual_rate if manual_rate > 0 else None
            refresh_key = f"service_calc_refresh_inputs_{selected_month['id']}"
            force_refresh_key = f"service_calc_force_eligibility_refresh_{selected_month['id']}"
            force_refresh_eligibility = st.session_state.pop(force_refresh_key, False)

            try:
                preview_url = service_api_path(f"/calculate/{selected_month['id']}")
                if manual_rate_payload is not None:
                    preview_url += f"?manual_service_rate={manual_rate_payload}"
                if force_refresh_eligibility:
                    preview_url += "&refresh_eligibility=true" if "?" in preview_url else "?refresh_eligibility=true"
                preview = api_get_json(preview_url)
                rows = preview.get("employees", [])
                summary = preview.get("summary", {})
                preserved_inputs = st.session_state.pop(refresh_key, None)
                if preserved_inputs:
                    for row in rows:
                        emp_inputs = preserved_inputs.get(str(row.get("emp_code")), {})
                        for field in [
                            "evaluation_percent", "notes"
                        ]:
                            if field in emp_inputs:
                                row[field] = emp_inputs[field]
            except Exception as e:
                rows = []
                summary = {}
                st.error(f"❌ ไม่สามารถโหลดข้อมูลคำนวณได้: {e}")

            service_rate = summary.get("service_rate", 0)
            if rows:
                editor_columns = [
                    "emp_code", "employee_name", "department", "start_date", "service_type",
                    "service_percent", "eligible_service_month", "source", "imported_from_payroll",
                    "payroll_cycle_id", "payroll_month", "payroll_year",
                    "prior_deposit_total", "service_weight", "service_rate", "gross_service", "sick_days",
                    "leave_days",
                    "sick_deduction", "leave_day_deduction", "leave_hours", "leave_hour_deduction", "late_hours", "late_deduction",
                    "evaluation_percent", "evaluation_deduction", "deposit_deduction",
                    "net_service", "notes"
                ]
                df_calc = pd.DataFrame(rows)
                df_calc["employee_name"] = (df_calc.get("first_name", "").fillna("").astype(str) + " " + df_calc.get("last_name", "").fillna("").astype(str)).str.strip()
                for col in editor_columns:
                    if col not in df_calc.columns:
                        df_calc[col] = ""
                edited_df = st.data_editor(
                    df_calc[editor_columns],
                    use_container_width=True,
                    num_rows="fixed",
                    disabled=[
                        "emp_code", "employee_name", "department", "start_date", "service_type",
                        "service_percent", "eligible_service_month", "source", "imported_from_payroll",
                        "payroll_cycle_id", "payroll_month", "payroll_year",
                        "prior_deposit_total", "service_weight", "service_rate", "gross_service",
                        "sick_deduction", "leave_day_deduction", "leave_hour_deduction", "late_deduction", "evaluation_deduction", "net_service"
                    ],
                    column_config={
                        "emp_code": st.column_config.TextColumn("Employee Code"),
                        "employee_name": st.column_config.TextColumn("Employee Name"),
                        "department": st.column_config.TextColumn("Department"),
                        "start_date": st.column_config.TextColumn("Start Date"),
                        "service_type": st.column_config.TextColumn("Service Type"),
                        "source": st.column_config.TextColumn("Source"),
                        "imported_from_payroll": st.column_config.CheckboxColumn("Imported from Payroll"),
                        "payroll_cycle_id": st.column_config.NumberColumn("Payroll Cycle ID", format="%d"),
                        "payroll_month": st.column_config.NumberColumn("Payroll Month", format="%d"),
                        "payroll_year": st.column_config.NumberColumn("Payroll Year", format="%d"),
                        "prior_deposit_total": st.column_config.NumberColumn("Prior Deposit Total", format="%d"),
                        "service_weight": st.column_config.NumberColumn("Service Weight", format="%.2f"),
                        "service_rate": st.column_config.NumberColumn("Service Rate", format="%.2f"),
                        "gross_service": st.column_config.NumberColumn("Gross Service", format="%d"),
                        "sick_days": st.column_config.NumberColumn("Sick Days", min_value=0.0, step=0.5),
                        "leave_days": st.column_config.NumberColumn("Leave Days", min_value=0.0, step=0.5),
                        "sick_deduction": st.column_config.NumberColumn("Sick Deduction", format="%d"),
                        "leave_day_deduction": st.column_config.NumberColumn("Leave Day Deduction", format="%d"),
                        "leave_hours": st.column_config.NumberColumn("Leave Hours", min_value=0.0, step=0.5),
                        "leave_hour_deduction": st.column_config.NumberColumn("Leave Hour Deduction", format="%d"),
                        "late_hours": st.column_config.NumberColumn("Late Hours", min_value=0.0, step=0.5),
                        "late_deduction": st.column_config.NumberColumn("Late Deduction", format="%d"),
                        "evaluation_percent": st.column_config.NumberColumn("Evaluation Deduction %", min_value=0.0, max_value=100.0, step=1.0),
                        "evaluation_deduction": st.column_config.NumberColumn("Evaluation Deduction", format="%d"),
                        "deposit_deduction": st.column_config.NumberColumn("Deposit Deduction", min_value=0.0, step=100.0),
                        "net_service": st.column_config.NumberColumn("Net Service", format="%d"),
                        "notes": st.column_config.TextColumn("Notes")
                    },
                    key=f"service_calc_editor_{selected_month['id']}"
                )

                original_by_code = {str(row.get("emp_code")): row for row in rows}
                edited_rows = []
                for row_index, edited_row in enumerate(edited_df.to_dict(orient="records")):
                    edited_row = sanitize_service_payload_value(edited_row, f"service_rows[{row_index}]")
                    source_row = dict(original_by_code.get(str(edited_row.get("emp_code")), {}))
                    source_row.update(edited_row)
                    edited_rows.append(source_row)

                recalc_clicked = st.button("🔄 Recalculate", use_container_width=True)
                if recalc_clicked:
                    st.session_state[refresh_key] = {
                        str(row.get("emp_code")): {
                            "evaluation_percent": row.get("evaluation_percent", 0),
                            "notes": row.get("notes", "")
                        }
                        for row in edited_rows
                    }
                    clear_api_cache()
                    st.session_state[force_refresh_key] = True
                    st.rerun()

                recalculated_rows = recalculate_service_rows(edited_rows, service_rate)

                actual_paid = sum(service_row_total_after_deduction(row) for row in recalculated_rows)
                employee_pool = round_baht(summary.get("employee_pool", 0))
                balance_returned = employee_pool - actual_paid

                st.dataframe(
                    pd.DataFrame(recalculated_rows)[[
                        "emp_code", "employee_name", "department", "source", "gross_service", "sick_deduction",
                        "leave_day_deduction", "leave_hour_deduction", "late_deduction", "evaluation_deduction", "deposit_deduction", "net_service", "notes"
                    ]],
                    use_container_width=True
                )

                st.markdown("---")
                c1, c2, c3 = st.columns(3)
                with c1: st.metric("Employee Pool", f"{employee_pool:,.0f}")
                with c2: st.metric("Total Weight", f"{summary.get('total_weight', 0):,.2f}")
                with c3: st.metric("Calculated Service Rate", f"{float(summary.get('calculated_service_rate', 0) or 0):,.2f}")
                c4, c5, c6 = st.columns(3)
                with c4: st.metric("Manual Service Rate", f"{float(manual_rate_payload or 0):,.2f}")
                with c5: st.metric("Actual Employee Paid", f"{actual_paid:,.0f}")
                with c6: st.metric("Balance Returned To Resort", f"{balance_returned:,.0f}")

                if actual_paid > employee_pool:
                    st.warning("⚠️ Actual Employee Paid exceeds Employee Pool. Please reduce manual rate or deductions before saving.")

                if st.button("💾 Save Service Calculation", type="primary", use_container_width=True, disabled=actual_paid > employee_pool):
                    payload = {"manual_service_rate": manual_rate_payload, "employees": recalculated_rows, "audit_username": current_username()}
                    payload = sanitize_service_payload_value(payload)
                    preview_totals = service_total_signature(employee_pool, actual_paid)
                    try:
                        save_path = service_api_path(f"/calculate/{selected_month['id']}/save")
                        res = requests.post(f"{API_URL}{save_path}", json=payload, timeout=REQUEST_TIMEOUT)
                        if res.status_code == 200:
                            save_result = res.json()
                            clear_api_cache()
                            reloaded_reports = api_get_json(service_api_path(f"/reports/{selected_month['id']}"))
                            assert_service_total_consistency(
                                preview_totals,
                                save_result.get("summary", {}),
                                reloaded_reports.get("summary", {})
                            )
                            st.success(save_result["message"])
                            st.rerun()
                        else:
                            st.error(f"❌ เกิดข้อผิดพลาด: {res.text}")
                    except Exception as e:
                        st.error(f"❌ ไม่สามารถบันทึกได้: {e}")

    with reports_tab:
        st.subheader("Service Reports")
        if not service_months:
            st.info("กรุณาสร้าง Service Setup ก่อน")
        else:
            service_options = {service_month_label(item): item for item in service_months}
            year_options = sorted({int(item["year"]) for item in service_months}, reverse=True)
            selected_summary_year = st.selectbox("Select Year", year_options, key="summary_service_year")
            try:
                summary_report = api_get_json(service_api_path(f"/reports/summary/{selected_summary_year}"))
                st.markdown("### Service Summary Report")
                render_service_summary_report(summary_report)
            except Exception as e:
                st.info(f"ยังไม่มีข้อมูล Service Summary สำหรับปีนี้: {e}")

            st.markdown("---")
            selected_report_label = st.selectbox("Select Service Month", list(service_options.keys()), key="report_service_month")
            selected_report_month = service_options[selected_report_label]
            try:
                reports = api_get_json(service_api_path(f"/reports/{selected_report_month['id']}"))
                st.markdown("### Service Detail Report")
                render_service_detail_report(reports, selected_report_month)

                st.markdown("### Distribution Summary")
                st.dataframe(pd.DataFrame(reports.get("distribution_summary", [])), use_container_width=True)
                st.metric("Total Employees", reports.get("total_employees", 0))

                st.markdown("### Cash Preparation Report")
                render_cash_preparation_report(reports, selected_report_month)

                st.markdown("### Monthly JV Report")
                monthly_jv = reports.get("monthly_jv", {})
                if monthly_jv and not monthly_jv.get("is_balanced", False):
                    st.warning(
                        "Monthly JV Report warning: Total Debit does not equal Total Credit "
                        f"(Debit {format_baht(monthly_jv.get('total_debit', 0))}, "
                        f"Credit {format_baht(monthly_jv.get('total_credit', 0))})."
                    )
                render_monthly_jv_report(reports, selected_report_month)

                st.markdown("### Service Charge Slips")
                all_slips = api_get_json(service_api_path("/slips"))
                month_slips = [
                    slip for slip in all_slips
                    if int(slip.get("service_month_id", 0) or 0) == int(selected_report_month["id"])
                ]
                if month_slips:
                    render_service_slips_v2(month_slips, selected_report_month)
                else:
                    st.info("No service charge record for this month.")
            except Exception as e:
                st.info(f"ยังไม่มีข้อมูล Service Calculation สำหรับเดือนนี้: {e}")

def render_audit_logs_page():
    st.title("System > Audit Logs")
    st.caption("Track important SmartHR user actions")

    col1, col2, col3, col4 = st.columns(4)
    today = datetime.date.today()
    with col1:
        start_date = st.date_input("Start Date", value=today - datetime.timedelta(days=30), key="audit_start_date")
    with col2:
        end_date = st.date_input("End Date", value=today, key="audit_end_date")
    with col3:
        username_filter = st.text_input("Username", key="audit_username_filter")
    with col4:
        module_filter = st.selectbox("Module", ["All", "Authentication", "Employee", "Payroll", "Service Charge", "HR Documents", "System"], key="audit_module_filter")

    if st.button("Refresh Audit Logs", use_container_width=True):
        api_get_json.clear()

    try:
        params = {
            "start_date": str(start_date),
            "end_date": str(end_date),
            "module": module_filter,
            "limit": 1000
        }
        if username_filter.strip():
            params["username"] = username_filter.strip()
        res = requests.get(f"{API_URL}/audit-logs/", params=params, timeout=REQUEST_TIMEOUT)
        res.raise_for_status()
        logs = res.json()
        if not logs:
            st.info("No audit logs found for the selected filters.")
            return

        df_audit = pd.DataFrame(logs)
        df_audit = df_audit.rename(columns={
            "timestamp": "Timestamp",
            "username": "User",
            "module": "Module",
            "action": "Action",
            "reference_id": "Reference",
            "details": "Details"
        })
        display_columns = ["Timestamp", "User", "Module", "Action", "Reference", "Details"]
        for col in display_columns:
            if col not in df_audit.columns:
                df_audit[col] = ""
        st.dataframe(df_audit[display_columns], use_container_width=True)
        st.download_button(
            "Export CSV",
            data=df_audit[display_columns].to_csv(index=False).encode("utf-8-sig"),
            file_name=f"Audit_Logs_{datetime.date.today()}.csv",
            mime="text/csv",
            use_container_width=True
        )
    except Exception as e:
        st.error(f"ไม่สามารถโหลด Audit Logs ได้: {e}")

def render_backups_page():
    st.title("System > Backups")
    st.caption("Database backup status and manual backup tools")

    try:
        status = api_get_json("/backups/")
    except Exception as e:
        st.error(f"ไม่สามารถโหลดข้อมูล Backup ได้: {e}")
        return

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Database Found", "Yes" if status.get("database_exists") else "No")
    with col2:
        st.metric("Manual Script", "Found" if status.get("manual_script_exists") else "Missing")
    with col3:
        st.metric("Auto Backup Day", status.get("auto_backup_day", "-"))

    st.info(
        f"Backup folder: {status.get('backup_dir', '-')}\n\n"
        "Existing `Backup_HRMS.bat` is still available. New manual backups use timestamped files in the backup folder."
    )

    if st.button("Create Manual Backup Now", type="primary", use_container_width=True):
        try:
            res = requests.post(
                f"{API_URL}/backups/create",
                json={"audit_username": current_username()},
                timeout=REQUEST_TIMEOUT
            )
            if res.status_code == 200:
                api_get_json.clear()
                backup_name = res.json().get("backup", {}).get("file_name", "")
                st.success(f"Backup created: {backup_name}")
                st.rerun()
            else:
                st.error(f"Backup failed: {res.text}")
        except Exception as e:
            st.error(f"Backup failed: {e}")

    backups = status.get("backups", [])
    st.markdown("### Backup Files")
    if backups:
        df_backups = pd.DataFrame(backups)
        st.dataframe(
            df_backups,
            column_config={
                "file_name": "File Name",
                "path": "Path",
                "size_bytes": "Size (bytes)",
                "modified_at": "Modified At"
            },
            use_container_width=True
        )
    else:
        st.info("No timestamped backup files found yet.")

def apply_custom_css():
    st.markdown("""
    <style>
        .stApp {
            background:
                linear-gradient(135deg, rgba(235, 248, 244, 0.92) 0%, rgba(246, 251, 249, 0.92) 42%, rgba(240, 247, 252, 0.92) 100%),
                repeating-linear-gradient(90deg, rgba(46, 123, 91, 0.035) 0, rgba(46, 123, 91, 0.035) 1px, transparent 1px, transparent 52px);
            color: #12382E;
            font-size: 16.5px;
        }
        html, body, [class*="css"] {
            font-size: 16.5px;
        }
        .stMarkdown, .stText, label, p {
            font-size: 1.03rem;
        }
        .stDataFrame, div[data-testid="stTable"] {
            font-size: 1rem;
        }
        .block-container {
            padding-top: 2rem;
        }
        header[data-testid="stHeader"] {
            background: rgba(246, 251, 249, 0.82);
            backdrop-filter: blur(10px);
            border-bottom: 1px solid rgba(46, 123, 91, 0.12);
        }
        section[data-testid="stSidebar"] > div {
            background: linear-gradient(180deg, #EAF6F1 0%, #F7FAFD 100%);
            border-right: 1px solid rgba(46, 123, 91, 0.14);
        }
        div[data-testid="stMetric"] {
            background: rgba(255, 255, 255, 0.9); border-radius: 12px; padding: 20px;
            box-shadow: 0 12px 28px -22px rgba(18, 56, 46, 0.45), 0 1px 0 rgba(255, 255, 255, 0.75) inset;
            border: 1px solid rgba(46, 123, 91, 0.10);
            border-left: 6px solid #2E7B5B; transition: transform 0.2s ease-in-out;
        }
        div[data-testid="stMetric"]:hover { transform: translateY(-5px); }
        div.stButton > button:first-child { border-radius: 8px; font-weight: bold; transition: all 0.3s ease; }
        div.stButton > button:first-child:hover { box-shadow: 0 4px 12px rgba(46, 123, 91, 0.3); border-color: #2E7B5B; }
        h1, h2, h3 { color: #1B4D3E !important; font-family: 'Kanit', sans-serif; }
        h1 { font-size: 2.35rem !important; }
        h2 { font-size: 1.8rem !important; }
        h3 { font-size: 1.35rem !important; }
        div[data-testid="stAlert"] { border-radius: 10px; }
        button[data-baseweb="tab"] > div[data-testid="stMarkdownContainer"] > p {
            font-size: 18px !important; font-weight: 600 !important; color: #1B4D3E; 
        }
        div[data-baseweb="tab-highlight"] { background-color: #2E7B5B !important; }
    </style>
    """, unsafe_allow_html=True)

apply_custom_css()

if "authenticated" not in st.session_state: st.session_state["authenticated"] = False
if "role" not in st.session_state: st.session_state["role"] = None
if "emp_code" not in st.session_state: st.session_state["emp_code"] = None
if "emp_name" not in st.session_state: st.session_state["emp_name"] = None

try:
    pdfmetrics.registerFont(TTFont('THSarabun', 'THSarabunNew.ttf'))
    if os.path.exists('THSarabunNew Bold.ttf'):
        pdfmetrics.registerFont(TTFont('THSarabun-Bold', 'THSarabunNew Bold.ttf'))
        font_bold = 'THSarabun-Bold'
    else: 
        font_bold = 'THSarabun'
    font_regular = 'THSarabun'
except: 
    font_regular, font_bold = 'Helvetica', 'Helvetica-Bold'

def _normalize_employee_id(value):
    if value is None or pd.isna(value):
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    text = str(value).strip()
    if re.fullmatch(r"\d+\.0+", text):
        return str(int(float(text)))
    return re.sub(r"\s+", "", text)

def _cell_to_time(value):
    if value is None or pd.isna(value):
        return None
    if isinstance(value, datetime.time):
        return value
    if isinstance(value, datetime.datetime):
        return value.time()
    if isinstance(value, pd.Timestamp):
        return value.time()

    match = re.search(r"\b(\d{1,2}):(\d{2})(?::(\d{2}))?\b", str(value).strip())
    if not match:
        return None
    hour, minute, second = match.groups()
    try:
        return datetime.time(int(hour), int(minute), int(second or 0))
    except ValueError:
        return None

def _extract_enroll_id(df_raw, sheet_name):
    candidates = [sheet_name]

    for row_idx in range(min(10, len(df_raw))):
        for col_idx, value in enumerate(df_raw.iloc[row_idx]):
            if str(value).strip().lower().replace(" ", "") == "enrollid":
                for next_col in range(col_idx + 1, min(col_idx + 5, len(df_raw.columns))):
                    next_value = df_raw.iat[row_idx, next_col]
                    if pd.notna(next_value):
                        candidates.insert(0, next_value)
                        break

    for candidate in candidates:
        employee_id = _normalize_employee_id(candidate)
        if employee_id:
            return employee_id
    return ""

def _sheet_punch_days(df_raw):
    date_row_idx = None
    for idx, value in enumerate(df_raw.iloc[:, 0]):
        if str(value).strip().lower() == "date":
            date_row_idx = idx
            break

    if date_row_idx is None:
        date_row_idx = 4

    days = []
    current_times = []

    def flush_day():
        nonlocal current_times
        if current_times:
            days.append(current_times)
        current_times = []

    for row_idx in range(date_row_idx + 1, len(df_raw)):
        row = df_raw.iloc[row_idx]
        first_cell = "" if pd.isna(row.iloc[0]) else str(row.iloc[0]).strip()
        is_date_row = bool(re.search(r"\d{1,2}[-/]\d{1,2}[-/]\d{2,4}", first_cell))
        row_times = [t for t in (_cell_to_time(value) for value in row.iloc[1:]) if t]

        if is_date_row:
            flush_day()
            current_times = row_times
        elif first_cell.startswith("...") and current_times:
            current_times.extend(row_times)
        elif not first_cell and current_times and row_times:
            current_times.extend(row_times)

    flush_day()
    return days

def _money_2(value):
    return Decimal(str(value or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

def _account_last4(value):
    return re.sub(r"\D", "", str(value or ""))[-4:]

def _clean_bank_text(value, max_len=120):
    text = re.sub(r"[\r\n\t|]+", " ", str(value or ""))
    return " ".join(text.split())[:max_len]

def _scb_account_no(value):
    digits = re.sub(r"\D", "", str(value or ""))
    if not digits:
        return ""
    if len(digits) < 10:
        digits = digits.zfill(10)
    if len(digits) != 10 or digits == "0000000000":
        return ""
    return digits

def process_attendance(file_path, mapping, s_in, s_out, quota):
    summary = []
    normalized_mapping = {
        employee_id: emp
        for emp in mapping.values()
        for employee_id in (
            _normalize_employee_id(emp.get('machine_id', '')),
            _normalize_employee_id(emp.get('emp_code', ''))
        )
        if employee_id
    }

    if hasattr(file_path, "seek"):
        file_path.seek(0)
    xls = pd.ExcelFile(file_path)
    
    for sheet_name in xls.sheet_names:
        df_sheet = pd.read_excel(xls, sheet_name=sheet_name, header=None)
        eid_str = _extract_enroll_id(df_sheet, sheet_name)
            
        if eid_str not in normalized_mapping:
            continue
            
        emp = normalized_mapping[eid_str]
        total_late_min = 0; total_early_min = 0; work_days = 0

        for punches in _sheet_punch_days(df_sheet):
            work_days += 1
            in_time = min(punches); out_time = max(punches)
            
            if in_time > s_in:
                diff = (datetime.datetime.combine(datetime.date.today(), in_time) - 
                        datetime.datetime.combine(datetime.date.today(), s_in)).total_seconds() / 60
                if diff >= 6: total_late_min += (diff - 5)
            
            if out_time < s_out:
                diff_out = (datetime.datetime.combine(datetime.date.today(), s_out) - 
                            datetime.datetime.combine(datetime.date.today(), out_time)).total_seconds() / 60
                total_early_min += diff_out

        net_late = max(0, total_late_min - quota)
        summary.append({
            "แผนก": emp.get('department', '-'),
            "รหัสพนักงาน": emp['emp_code'],
            "ชื่อ-นามสกุล": f"{emp['first_name']} {emp['last_name']}",
            "วันทำงาน (วัน)": work_days,
            "สายสะสม (นาที)": int(total_late_min),
            "หักเงินสาย (นาที)": int(net_late),
            "ออกก่อน (นาที)": int(total_early_min)
        })
    return pd.DataFrame(summary)

@st.cache_data(ttl=300, show_spinner=False)
def generate_pdf_payslips(payroll_data, cycle_name):
    buffer = io.BytesIO(); c = canvas.Canvas(buffer, pagesize=letter); width, height = letter
    for emp in payroll_data:
        c.setFillColorRGB(0.15, 0.45, 0.35); c.rect(0, height - 100, width, 100, fill=1, stroke=0)
        c.setFillColor(colors.white); c.setFont(font_bold, 28); c.drawString(50, height - 45, "AONANG FIORE RESORT")
        c.setFont(font_regular, 18); c.drawString(50, height - 75, f"สลิปเงินเดือน (Payslip) | ประจำรอบ {cycle_name}")
        c.setFillColor(colors.black); c.setFont(font_bold, 16); c.drawString(50, height - 140, "ข้อมูลพนักงาน")
        c.setStrokeColor(colors.lightgrey); c.rect(50, height - 210, width - 100, 60, fill=0, stroke=1)
        c.setFont(font_regular, 14); c.drawString(60, height - 165, f"ชื่อ-นามสกุล: {emp['first_name']} {emp['last_name']}")
        c.drawString(60, height - 185, f"รหัสพนักงาน: {emp['emp_code']}"); c.drawString(250, height - 165, f"แผนก: {emp.get('department', '-')}")
        c.drawString(250, height - 185, f"ตำแหน่ง: {emp.get('position', '-')}"); c.drawString(450, height - 165, f"เลขบัญชี: {emp['account_no']}")
        c.setFont(font_bold, 16); c.drawString(50, height - 250, "รายรับ (EARNINGS)"); c.drawString(320, height - 250, "รายการหัก (DEDUCTIONS)")
        c.setStrokeColor(colors.black); c.line(50, height - 260, width - 50, height - 260)
        
        c.setFont(font_regular, 14); y_earn = height - 285; c.drawString(50, y_earn, "เงินเดือน (Base Salary)")
        c.drawRightString(280, y_earn, f"{emp['base_salary']:,.2f}"); y_earn -= 20
        
        if emp.get('ot_15_amount', 0) > 0: 
            c.drawString(50, y_earn, "ค่าล่วงเวลา (OT 1.5x)")
            c.drawRightString(280, y_earn, f"{emp['ot_15_amount']:,.2f}"); y_earn -= 20
        if emp.get('ot_1_amount', 0) > 0: 
            c.drawString(50, y_earn, "ค่าทำงานวันหยุด (OT 1.0x)")
            c.drawRightString(280, y_earn, f"{emp['ot_1_amount']:,.2f}"); y_earn -= 20

        if emp['other_benefits'] > 0: c.drawString(50, y_earn, "สวัสดิการอื่นๆ"); c.drawRightString(280, y_earn, f"{emp['other_benefits']:,.2f}"); y_earn -= 20
        if emp['backpay'] > 0: c.drawString(50, y_earn, "เงินเดือนย้อนหลัง"); c.drawRightString(280, y_earn, f"{emp['backpay']:,.2f}"); y_earn -= 20
        y_deduct = height - 285
        if emp['leave_deduction'] > 0: c.drawString(320, y_deduct, "หักขาด/ลา/มาสาย"); c.drawRightString(width - 50, y_deduct, f"{emp['leave_deduction']:,.2f}"); y_deduct -= 20
        if emp['company_loan'] > 0: c.drawString(320, y_deduct, "หักเงินกู้บริษัท"); c.drawRightString(width - 50, y_deduct, f"{emp['company_loan']:,.2f}"); y_deduct -= 20
        if emp['student_loan'] > 0: c.drawString(320, y_deduct, "หัก กยศ."); c.drawRightString(width - 50, y_deduct, f"{emp['student_loan']:,.2f}"); y_deduct -= 20
        if emp['sso_deduction'] > 0: c.drawString(320, y_deduct, "เงินสมทบประกันสังคม (5%)"); c.drawRightString(width - 50, y_deduct, f"{emp['sso_deduction']:,.2f}"); y_deduct -= 20
        c.line(50, height - 400, width - 50, height - 400); c.setFont(font_bold, 14); c.drawString(50, height - 425, "รวมรายรับ")
        c.drawRightString(280, height - 425, f"{emp['gross_salary']:,.2f}")
        total_deduct = emp['leave_deduction'] + emp['company_loan'] + emp['student_loan'] + emp['sso_deduction']
        c.drawString(320, height - 425, "รวมรายการหัก"); c.drawRightString(width - 50, height - 425, f"{total_deduct:,.2f}")
        c.setFillColorRGB(0.9, 0.95, 0.9); c.setStrokeColorRGB(0.15, 0.45, 0.35); c.rect(50, height - 500, width - 100, 50, fill=1, stroke=1)
        c.setFillColor(colors.black); c.setFont(font_bold, 18); c.drawString(70, height - 470, "เงินเดือนสุทธิ (NET PAY)")
        c.setFont(font_bold, 22); c.drawRightString(width - 70, height - 472, f"{emp['net_salary']:,.2f} บาท")
        c.setFont(font_regular, 12); c.setFillColor(colors.gray); c.drawCentredString(width / 2.0, 50, "เอกสารฉบับนี้จัดทำขึ้นโดยระบบคอมพิวเตอร์ ไม่จำเป็นต้องมีลายเซ็นผู้มีอำนาจ"); c.showPage() 
    c.save(); buffer.seek(0); return buffer.getvalue()

@st.cache_data(ttl=300, show_spinner=False)
def generate_pdf_emp_report(emp_data):
    buffer = io.BytesIO(); c = canvas.Canvas(buffer, pagesize=landscape(A4)); width, height = landscape(A4)
    def draw_emp_header(c):
        c.setFont(font_bold, 20); c.drawString(40, height - 40, "AONANG FIORE RESORT"); c.setFont(font_regular, 16)
        c.drawString(40, height - 60, "รายงานข้อมูลพนักงาน (Employee Database Report)"); c.setFont(font_bold, 13); c.line(30, height - 80, width - 30, height - 80)
        c.drawString(35, height - 95, "รหัส"); c.drawString(90, height - 95, "ชื่อ-นามสกุล"); c.drawString(230, height - 95, "แผนก"); c.drawString(350, height - 95, "ตำแหน่ง")
        c.drawString(470, height - 95, "เบอร์โทรศัพท์"); c.drawString(560, height - 95, "เลขบัญชี"); c.drawRightString(700, height - 95, "ฐานเงินเดือน"); c.drawString(730, height - 95, "สถานะ")
        c.line(30, height - 105, width - 30, height - 105); return height - 125
    y = draw_emp_header(c); c.setFont(font_regular, 13)
    for emp in emp_data:
        if y < 50: c.showPage(); y = draw_emp_header(c); c.setFont(font_regular, 13)
        c.drawString(35, y, emp.get('emp_code', '-')); c.drawString(90, y, f"{emp.get('first_name', '')} {emp.get('last_name', '')}")
        c.drawString(230, y, emp.get('department', '-')); c.drawString(350, y, emp.get('position', '-'))
        c.drawString(470, y, emp.get('phone', '-')); c.drawString(560, y, emp.get('account_no', '-')); c.drawRightString(700, y, f"{emp.get('base_salary', 0):,.2f}")
        status = "ปกติ" if emp.get('is_active', True) else "ลาออก"; c.drawString(730, y, status)
        y -= 20; c.setStrokeColorRGB(0.9, 0.9, 0.9); c.line(30, y + 15, width - 30, y + 15); c.setStrokeColorRGB(0, 0, 0)
    c.save(); buffer.seek(0); return buffer.getvalue()

@st.cache_data(ttl=300, show_spinner=False)
def generate_pdf_payroll_summary(payroll_data, cycle_name):
    buffer = io.BytesIO(); c = canvas.Canvas(buffer, pagesize=landscape(A4)); width, height = landscape(A4)
    def draw_payroll_header(c):
        c.setFont(font_bold, 20); c.drawString(15, height - 40, "AONANG FIORE RESORT"); c.setFont(font_regular, 16)
        c.drawString(15, height - 60, f"SUMMARY OF PAYROLL : {cycle_name}"); c.setFont(font_bold, 12); c.line(15, height - 80, width - 15, height - 80)
        c.drawString(15, height - 95, "No."); c.drawString(35, height - 95, "Name/Surname"); c.drawString(140, height - 95, "Position")
        c.drawRightString(265, height - 95, "Salary"); c.drawRightString(305, height - 95, "OT"); c.drawRightString(350, height - 95, "Benefits")
        c.drawRightString(420, height - 95, "Gross Tot."); c.drawRightString(470, height - 95, "Leave/Late")
        c.drawRightString(515, height - 95, "Loan"); c.drawRightString(555, height - 95, "Edu."); c.drawRightString(595, height - 95, "SSO")
        c.drawRightString(650, height - 95, "Deduct Tot."); c.drawRightString(705, height - 95, "Net Pay"); c.drawString(715, height - 95, "Remark")
        c.line(15, height - 105, width - 15, height - 105); return height - 125
    y = draw_payroll_header(c)
    departments = {}
    for emp in payroll_data:
        dept = emp.get('department', 'ไม่ระบุแผนก')
        if dept not in departments: departments[dept] = []
        departments[dept].append(emp)
    g_sal = g_ot = g_ben = g_back = g_gross = g_leave = g_loan = g_edu = g_sso = g_deduct = g_net = 0; emp_no = 1
    for dept_name in ordered_department_names(departments):
        emps = departments[dept_name]
        if y < 120: c.showPage(); y = draw_payroll_header(c)
        c.setFont(font_bold, 12); c.drawString(15, y, f"แผนก: {dept_name}"); y -= 20; c.setFont(font_regular, 12)
        d_sal = d_ot = d_ben = d_back = d_gross = d_leave = d_loan = d_edu = d_sso = d_deduct = d_net = 0
        for emp in emps:
            if y < 100: c.showPage(); y = draw_payroll_header(c); c.setFont(font_regular, 12)
            c.drawString(15, y, str(emp_no)); c.drawString(35, y, f"{emp['first_name']} {emp['last_name']}"); c.drawString(140, y, str(emp.get('position', '-'))[:22])
            c.drawRightString(265, y, f"{emp['base_salary']:,.2f}"); c.drawRightString(305, y, f"{emp['ot_amount']:,.2f}"); c.drawRightString(350, y, f"{emp['other_benefits']:,.2f}")
            c.drawRightString(420, y, f"{emp['gross_salary']:,.2f}"); c.drawRightString(470, y, f"{emp['leave_deduction']:,.2f}")
            c.drawRightString(515, y, f"{emp['company_loan']:,.2f}"); c.drawRightString(555, y, f"{emp['student_loan']:,.2f}"); c.drawRightString(595, y, f"{emp['sso_deduction']:,.2f}")
            tot_deduct = emp['leave_deduction'] + emp['company_loan'] + emp['student_loan'] + emp['sso_deduction']
            c.drawRightString(650, y, f"{tot_deduct:,.2f}"); c.drawRightString(705, y, f"{emp['net_salary']:,.2f}")
            rem_texts = []
            if emp.get('ot_15_hours', 0) > 0: rem_texts.append(f"OT1.5:{emp['ot_15_hours']:g}")
            if emp.get('ot_1_hours', 0) > 0: rem_texts.append(f"OT1.0:{emp['ot_1_hours']:g}")
            if emp.get('late_mins', 0) > 0: rem_texts.append(f"สาย:{emp['late_mins']}น.")
            if emp.get('unpaid_leave_days', 0) > 0: rem_texts.append(f"ขาด:{emp['unpaid_leave_days']:g}ว.")
            if emp.get('leave_hours', 0) > 0: rem_texts.append(f"ลา:{emp['leave_hours']:g}ช.")
            c.setFont(font_regular, 11); c.drawString(715, y, ", ".join(rem_texts)[:50]); c.setFont(font_regular, 12) 
            d_sal += emp['base_salary']; d_ot += emp['ot_amount']; d_ben += emp['other_benefits']; d_back += emp['backpay']; d_gross += emp['gross_salary']
            d_leave += emp['leave_deduction']; d_loan += emp['company_loan']; d_edu += emp['student_loan']; d_sso += emp['sso_deduction']; d_deduct += tot_deduct; d_net += emp['net_salary']
            y -= 20; c.setStrokeColorRGB(0.9, 0.9, 0.9); c.line(15, y + 15, width - 15, y + 15); c.setStrokeColorRGB(0, 0, 0); emp_no += 1
        if y < 100: c.showPage(); y = draw_payroll_header(c)
        c.setFont(font_bold, 12)
        c.drawString(35, y, f"TOTAL {dept_name} ({len(emps)} คน)")
        c.drawRightString(265, y, f"{d_sal:,.2f}"); c.drawRightString(305, y, f"{d_ot:,.2f}"); c.drawRightString(350, y, f"{d_ben:,.2f}")
        c.drawRightString(420, y, f"{d_gross:,.2f}"); c.drawRightString(470, y, f"{d_leave:,.2f}")
        c.drawRightString(515, y, f"{d_loan:,.2f}"); c.drawRightString(555, y, f"{d_edu:,.2f}"); c.drawRightString(595, y, f"{d_sso:,.2f}")
        c.drawRightString(650, y, f"{d_deduct:,.2f}"); c.drawRightString(705, y, f"{d_net:,.2f}")
        y -= 20; c.setStrokeColorRGB(0.6, 0.6, 0.6); c.line(15, y + 15, width - 15, y + 15); c.setStrokeColorRGB(0, 0, 0); c.setFont(font_regular, 12)
        g_sal += d_sal; g_ot += d_ot; g_ben += d_ben; g_back += d_back; g_gross += d_gross
        g_leave += d_leave; g_loan += d_loan; g_edu += d_edu; g_sso += d_sso; g_deduct += d_deduct; g_net += d_net
    if y < 150: c.showPage(); y = draw_payroll_header(c)
    c.setFont(font_bold, 12); c.line(15, y+10, width-15, y+10)
    c.drawString(35, y - 5, f"GRAND TOTAL ({len(payroll_data)} คน)")
    c.drawRightString(265, y - 5, f"{g_sal:,.2f}"); c.drawRightString(305, y - 5, f"{g_ot:,.2f}"); c.drawRightString(350, y - 5, f"{g_ben:,.2f}")
    c.drawRightString(420, y - 5, f"{g_gross:,.2f}"); c.drawRightString(470, y - 5, f"{g_leave:,.2f}")
    c.drawRightString(515, y - 5, f"{g_loan:,.2f}"); c.drawRightString(555, y - 5, f"{g_edu:,.2f}"); c.drawRightString(595, y - 5, f"{g_sso:,.2f}")
    c.drawRightString(650, y - 5, f"{g_deduct:,.2f}"); c.drawRightString(705, y - 5, f"{g_net:,.2f}")
    c.line(15, y-15, width-15, y-15); c.line(15, y-17, width-15, y-17) 
    y -= 80
    c.drawCentredString(100, y, "_________________"); c.drawCentredString(100, y - 20, "Prepared By (HR)")
    c.drawCentredString(260, y, "_________________"); c.drawCentredString(260, y - 20, "Checked By (ACC)")
    c.drawCentredString(420, y, "_________________"); c.drawCentredString(420, y - 20, "Checked By (GM)")
    c.drawCentredString(580, y, "_________________"); c.drawCentredString(580, y - 20, "Approved By (VP)")
    c.drawCentredString(740, y, "_________________"); c.drawCentredString(740, y - 20, "Authorized By (President)")
    c.save(); buffer.seek(0); return buffer.getvalue()
@st.cache_data(ttl=300, show_spinner=False)
def generate_pdf_jv(jv_data, cycle_name):
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    
    # --- หัวเอกสาร (Header) ---
    c.setFont(font_bold, 20)
    c.drawCentredString(width/2, height - 50, "AONANG FIORE RESORT")
    c.setFont(font_bold, 16)
    c.drawCentredString(width/2, height - 75, "JOURNAL VOUCHER (JV)")
    c.setFont(font_regular, 14)
    c.drawCentredString(width/2, height - 95, f"JV For The Month Of: {cycle_name}")
    c.setFont(font_regular, 12)
    c.drawString(50, height - 115, f"Printed Date: {datetime.datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
    
    # --- หัวตาราง ---
    y = height - 140
    c.line(50, y, width - 50, y)
    c.setFont(font_bold, 12)
    c.drawString(60, y - 15, "ACC. NO.")
    c.drawString(140, y - 15, "ACCOUNT NAME")
    c.drawRightString(420, y - 15, "DEBIT")
    c.drawRightString(530, y - 15, "CREDIT")
    c.line(50, y - 22, width - 50, y - 22)
    
    y -= 40
    c.setFont(font_regular, 12)
    total_debit = 0.0
    total_credit = 0.0
    
    # --- เนื้อหาตาราง ---[cite: 3]
    for _, row in jv_data.iterrows():
        if y < 100: # ขึ้นหน้าใหม่หากพื้นที่ไม่พอ
            c.showPage()
            y = height - 50
            # (ทำหัวตารางซ้ำในหน้าใหม่ได้ถ้าต้องการ)
            
        c.drawString(60, y, str(row['ACC. NO.']))
        c.drawString(140, y, str(row['NAME']))
        c.drawRightString(420, y, f"{row['DEBIT']:,.2f}")
        c.drawRightString(530, y, f"{row['CREDIT']:,.2f}")
        
        total_debit += float(row['DEBIT'])
        total_credit += float(row['CREDIT'])
        y -= 20
        
    # --- สรุปท้ายตาราง (Grand Total) ---[cite: 3]
    c.line(50, y + 10, width - 50, y + 10)
    c.setFont(font_bold, 12)
    c.drawString(140, y - 5, "GRAND TOTAL")
    c.drawRightString(420, y - 5, f"{total_debit:,.2f}")
    c.drawRightString(530, y - 5, f"{total_credit:,.2f}")
    c.line(50, y - 12, width - 50, y - 12)
    c.line(50, y - 14, width - 50, y - 14)
    
    # --- ส่วนลายเซ็น (Signatures) ---[cite: 3]
    y -= 80
    c.setFont(font_regular, 12)
    c.drawCentredString(150, y, "_______________________")
    c.drawCentredString(150, y - 20, "Prepared By")
    c.drawCentredString(width - 150, y, "_______________________")
    c.drawCentredString(width - 150, y - 20, "Approved By")
    
    c.save()
    buffer.seek(0)
    return buffer.getvalue()

# หน้าจอ Login
if not st.session_state["authenticated"]:
    col1, col2, col3 = st.columns(3)
    with col2:
        if os.path.exists("logo.png"):
            col_logo1, col_logo2, col_logo3 = st.columns([1, 1.5, 1])
            with col_logo2: st.image("logo.png", use_container_width=True)
        elif os.path.exists("logo.jpg"):
            col_logo1, col_logo2, col_logo3 = st.columns([1, 1.5, 1])
            with col_logo2: st.image("logo.jpg", use_container_width=True)
        else: st.markdown("<h1 style='text-align: center;'>🌴</h1>", unsafe_allow_html=True)
        
        st.markdown("<h1 style='text-align: center;'>Aonang Fiore HRMS</h1>", unsafe_allow_html=True)
        st.markdown("<p style='text-align: center;'>ระบบบริหารจัดการเงินเดือนบุคลากร</p>", unsafe_allow_html=True)
        st.info("💡 **คำแนะนำการเข้าสู่ระบบ:**\n\nพนักงานทั่วไป: กรอก **รหัสพนักงาน** และ **เลขบัญชีธนาคาร 4 ตัวท้าย**")
        
        with st.form("login_form"):
            username = st.text_input("👤 ชื่อผู้ใช้งาน / รหัสพนักงาน"); password = st.text_input("🔑 รหัสผ่าน / เลขบัญชี 4 ตัวท้าย", type="password", max_chars=5)
            submit_login = st.form_submit_button("เข้าสู่ระบบ", type="primary", use_container_width=True)
            if submit_login:
                username_clean = username.strip()
                password_clean = password.strip()
                if username_clean.lower() == "admin" and password_clean == "13579":
                    st.session_state["authenticated"] = True; st.session_state["role"] = "admin"
                    audit_event("Login", "Authentication", username="admin")
                    st.rerun()
                else:
                    try:
                        emps = api_get_json("/employees/")
                        valid_emp = next((e for e in emps if str(e["emp_code"]) == username_clean and _account_last4(e.get("account_no", "")) == password_clean), None)
                        if valid_emp:
                            st.session_state["authenticated"] = True; st.session_state["role"] = "employee"
                            st.session_state["emp_code"] = valid_emp["emp_code"]; st.session_state["emp_name"] = f"{valid_emp['first_name']} {valid_emp['last_name']}"
                            audit_event("Login", "Authentication", valid_emp["emp_code"], username=st.session_state["emp_name"])
                            st.rerun()
                        else: st.error("❌ ข้อมูลไม่ถูกต้อง")
                    except: st.error("❌ ไม่สามารถเชื่อมต่อเซิร์ฟเวอร์")

# หน้าจอ พนักงานทั่วไป
elif st.session_state["role"] == "employee":
    col_title, col_logout = st.columns([8, 2])
    with col_title: st.title(f"👨‍💼 ยินดีต้อนรับ, คุณ {st.session_state['emp_name']}")
    with col_logout:
        if st.button("🚪 ออกจากระบบ", use_container_width=True):
            logout_user()
            st.rerun()
    st.markdown("---")
    payroll_slip_tab, service_slip_tab = st.tabs(["📄 Payroll Slip", "🧾 Service Charge Slip"])

    with payroll_slip_tab:
        st.subheader("📄 ดาวน์โหลดสลิปเงินเดือนของคุณ")
        try:
            available_cycles = list(dict.fromkeys(api_get_json("/payroll/cycles")))
        except: available_cycles = []

        if not available_cycles: st.info("📌 ยังไม่มีรอบการจ่ายเงินเดือน")
        else:
            search_cycle = st.selectbox("📂 เลือกรอบเดือน", available_cycles)
            if st.button("🔍 ดูสลิปเงินเดือน", type="primary"):
                try:
                    record_log(f"พนักงานเข้าดูสลิปรอบ: {search_cycle}")
                    data = api_get_json(f"/payroll/{search_cycle}"); payroll_list = data["transactions"]
                    my_data = next((t for t in payroll_list if str(t['emp_code']) == str(st.session_state["emp_code"])), None)
                    if my_data:
                        st.success(f"✅ พบข้อมูลรอบ {data['cycle_name']}")
                        col1, col2, col3 = st.columns(3)
                        with col1: st.info(f"**💵 รายรับรวม:**\n### {my_data['gross_salary']:,.2f} บาท")
                        with col2: st.warning(f"**📉 รายการหักรวม:**\n### {my_data['leave_deduction']+my_data['company_loan']+my_data['student_loan']+my_data['sso_deduction']:,.2f} บาท")
                        with col3: st.success(f"**💰 รับสุทธิ:**\n### {my_data['net_salary']:,.2f} บาท")
                        pdf_payslip = generate_pdf_payslips([my_data], data['cycle_name'])
                        st.download_button(
                            "📥 โหลดสลิปฉบับเต็ม (PDF)",
                            data=pdf_payslip,
                            file_name=f"Payslip_{search_cycle}.pdf",
                            mime="application/pdf",
                            type="primary",
                            on_click=record_log,
                            args=(f"พนักงานดาวน์โหลดสลิปรอบ: {search_cycle}",)
                        )
                    else: st.warning("⚠️ ไม่พบข้อมูลของคุณในรอบนี้")
                except: st.error("❌ ขัดข้อง")

    with service_slip_tab:
        st.subheader("🧾 Service Charge Slip")
        try:
            service_months = api_get_json(service_api_path("/months"))
            my_service_slips = api_get_json(service_api_path(f"/slips/{st.session_state['emp_code']}"))
        except:
            service_months = []
            my_service_slips = []
            st.error("❌ ไม่สามารถโหลดข้อมูล Service Charge ได้")

        if not service_months:
            st.info("No service charge record for this month.")
        else:
            service_options = {service_month_label(item): item for item in service_months}
            selected_service_label = st.selectbox("📂 เลือกเดือน Service Charge", list(service_options.keys()), key="employee_service_slip_month")
            selected_service_month = service_options[selected_service_label]
            my_service_data = next(
                (item for item in my_service_slips if int(item.get("service_month_id", 0)) == int(selected_service_month["id"])),
                None
            )

            if not my_service_data:
                st.info("No service charge record for this month.")
            else:
                record_log(f"พนักงานเข้าดูสลิป Service Charge รอบ: {my_service_data['service_month']}")
                st.success(f"✅ พบข้อมูล Service Charge รอบ {my_service_data['service_month']}")
                render_service_slip_v2(my_service_data)

# หน้าจอ Admin (เจ้าหน้าที่ HR)
elif st.session_state["role"] == "admin":
    col_title, col_logout = st.columns([8, 1])
    with col_title: st.title("🌴 ระบบจัดการเงินเดือน (HR Dashboard)")
    with col_logout:
        if st.button("🚪 ออกจากระบบ", use_container_width=True):
            logout_user()
            st.rerun()

    admin_menu = st.sidebar.radio("Menu", ["HR Dashboard", "Service Charge (Beta)", "HR Documents", "System > Audit Logs", "System > Backups", "System > Company Settings"], key="admin_menu")
    if admin_menu == "Service Charge (Beta)":
        render_service_setup()
        st.stop()
    if admin_menu == "HR Documents":
        render_hr_documents_page()
        st.stop()
    if admin_menu == "System > Audit Logs":
        render_audit_logs_page()
        st.stop()
    if admin_menu == "System > Backups":
        render_backups_page()
        st.stop()
    if admin_menu == "System > Company Settings":
        render_company_settings_page()
        st.stop()

    tab0, tab1, tab2, tab3, tab4, tab5 = st.tabs(["📊 0. ภาพรวมสถิติ", "👥 1. ฐานข้อมูลพนักงาน", "💰 2. ประมวลผลเงินเดือน", "📥 3. ออกเอกสารและรายงาน", "⏱️ 4. ประมวลผลเวลา (Check-in)", "📜 5. ประวัติการใช้งาน"])

    with tab0:
        st.header("📊 Dashboard วิเคราะห์ข้อมูล")
        try:
            emps_data = api_get_json("/employees/")
            active_emps = [e for e in emps_data if e.get("is_active", True)]
            
            available_cycles = api_get_json("/payroll/cycles")

            st.subheader("👥 สถิติพนักงาน (ณ ปัจจุบัน)")
            col1, col2 = st.columns(2)
            with col1: st.metric("พนักงานที่กำลังทำงาน", f"{len(active_emps)} คน")
            with col2:
                total_base = sum([e.get("base_salary", 0) for e in active_emps])
                st.metric("ฐานเงินเดือนรวมรายเดือน (Fix Cost)", f"{total_base:,.2f} บาท")
            
            st.markdown("---")
            st.subheader("🔍 เจาะลึกข้อมูลรายเดือน")
            if available_cycles:
                selected_dash_cycle = st.selectbox("📅 เลือกเดือนที่ต้องการดูข้อมูล:", available_cycles, key="dash_cycle")
                cycle_data = api_get_json(f"/payroll/{selected_dash_cycle}").get("transactions", [])
                total_net = sum([t.get("net_salary", 0) for t in cycle_data])
                total_sso = sum([t.get("sso_deduction", 0) for t in cycle_data])
                
                col_m1, col_m2 = st.columns(2)
                with col_m1: st.metric(f"💸 ยอดจ่ายสุทธิ (Net Pay) รอบ {selected_dash_cycle}", f"{total_net:,.2f} บาท")
                with col_m2: st.metric(f"🏥 ยอดหักประกันสังคม (SSO) รอบ {selected_dash_cycle}", f"{total_sso:,.2f} บาท")

                col_chart1, col_chart2 = st.columns(2)
                with col_chart1:
                    if active_emps:
                        df_emps = pd.DataFrame(active_emps)
                        dept_counts = df_emps['department'].value_counts().reset_index()
                        dept_counts.columns = ['แผนก', 'จำนวนพนักงาน']
                        st.write("**จำนวนพนักงานแยกตามแผนก**")
                        st.bar_chart(data=dept_counts.set_index('แผนก'))
                
                with col_chart2:
                    if cycle_data:
                        df_pay = pd.DataFrame(cycle_data)
                        df_pay['department'] = df_pay['department'].fillna('ไม่ระบุ')
                        dept_expense = df_pay.groupby('department')['net_salary'].sum().reset_index()
                        dept_expense.columns = ['แผนก', 'รายจ่ายรวม (Net)']
                        st.write(f"**รายจ่ายเงินเดือนตามแผนก (รอบ {selected_dash_cycle})**")
                        st.bar_chart(data=dept_expense.set_index('แผนก'))
            else: st.info("ยังไม่มีข้อมูลรอบการจ่ายเงินเดือนในระบบ")

            st.markdown("---")
            st.subheader("📈 แนวโน้มรายจ่ายเงินเดือนทั้งหมด (Payroll Trend)")
            trend_data = api_get_json("/dashboard/trend")
            if trend_data:
                df_trend = pd.DataFrame(trend_data)
                df_trend.set_index("รอบเงินเดือน", inplace=True)
                st.line_chart(df_trend)
            else:
                st.info("ระบบจะสร้างกราฟเส้นอัตโนมัติ เมื่อมีการรันเงินเดือนอย่างน้อย 1 รอบขึ้นไปครับ")

        except Exception as e: st.error("ไม่สามารถเชื่อมต่อระบบหลังบ้านได้")

    with tab1:
        st.header("👥 จัดการฐานข้อมูลพนักงาน")
        mode = st.radio("เลือกโหมดการทำงาน:", ["➕ เพิ่มพนักงานใหม่", "📊 นำเข้าจาก Excel", "✏️ ค้นหา/แก้ไข", "📄 โหลดรายงานพนักงาน"], horizontal=True)
        dept_options = DEPARTMENT_ORDER

        if mode == "➕ เพิ่มพนักงานใหม่":
            st.subheader("➕ เพิ่มพนักงานใหม่")
            with st.form("add_emp_form"):
                col1, col2 = st.columns(2)
                with col1:
                    emp_code = st.text_input("รหัสพนักงาน *")
                    machine_id = st.text_input("รหัสเครื่องสแกนนิ้ว (Machine ID) 👈")
                    first_name = st.text_input("ชื่อจริง *")
                    last_name = st.text_input("นามสกุล *")
                    position = st.text_input("ตำแหน่ง")
                    department = st.selectbox("แผนก", dept_options)
                with col2:
                    start_date = st.date_input("วันที่เริ่มงาน")
                    phone = st.text_input("เบอร์โทรศัพท์")
                    address = st.text_area("ที่อยู่")
                    tax_info = st.text_input("ข้อมูลภาษี (เลขประจำตัวผู้เสียภาษี)")
                    base_salary = st.number_input("ฐานเงินเดือน", min_value=0.0, step=1000.0)
                    account_no = st.text_input("เลขที่บัญชี")
                    is_sso = st.checkbox("หักประกันสังคม", value=True)
                    service_type = st.selectbox("Service Type", ["AUTO", "FIXED_50", "FIXED", "NONE"])
                    service_percent = st.number_input("Service Percent", min_value=0.0, max_value=100.0, value=100.0, step=5.0)
                
                submit_btn = st.form_submit_button("💾 บันทึกข้อมูล")
                if submit_btn:
                    if not emp_code or not first_name or not last_name:
                        st.warning("กรุณากรอกข้อมูลที่มีเครื่องหมาย * ให้ครบถ้วน")
                    else:
                        payload = {
                            "emp_code": emp_code,
                            "machine_id": machine_id,
                            "first_name": first_name,
                            "last_name": last_name,
                            "position": position,
                            "department": department,
                            "phone": phone,
                            "start_date": str(start_date),
                            "address": address,
                            "tax_info": tax_info,
                            "base_salary": base_salary,
                            "account_no": account_no,
                            "is_sso": is_sso,
                            "service_type": service_type,
                            "service_percent": service_percent,
                            "audit_username": current_username()
                        }
                        res = requests.post(f"{API_URL}/employees/", json=payload, timeout=REQUEST_TIMEOUT)
                        if res.status_code == 200:
                            clear_api_cache()
                            st.success("✅ เพิ่มพนักงานสำเร็จ!")
                        else:
                            st.error(f"❌ เกิดข้อผิดพลาด: {res.text}")

        elif mode == "📊 นำเข้าจาก Excel":
            st.info("💡 ไฟล์ Excel ควรมีคอลัมน์: emp_code, first_name, last_name, position, department, machine_id, phone, start_date, address, tax_info, base_salary, account_no, service_type, service_percent")
            uploaded_file = st.file_uploader("ลากไฟล์มาวาง", type=["xlsx", "csv"])
            if uploaded_file is not None:
                df_bulk = read_uploaded_table(uploaded_file.name, uploaded_file.getvalue())
                df_bulk = df_bulk.fillna("") 
                
                if 'account_no' in df_bulk.columns: df_bulk['account_no'] = df_bulk['account_no'].astype(str).str.replace(r'\.0$', '', regex=True)
                if 'emp_code' in df_bulk.columns: df_bulk['emp_code'] = df_bulk['emp_code'].astype(str).str.replace(r'\.0$', '', regex=True)
                if 'start_date' in df_bulk.columns: df_bulk['start_date'] = pd.to_datetime(df_bulk['start_date'], errors='coerce').dt.strftime('%Y-%m-%d').fillna(str(datetime.date.today()))
                if 'is_sso' not in df_bulk.columns: df_bulk['is_sso'] = True 
                if 'service_type' not in df_bulk.columns: df_bulk['service_type'] = "AUTO"
                if 'service_percent' not in df_bulk.columns: df_bulk['service_percent'] = 100.0
                
                if st.button("💾 ยืนยันการนำเข้าข้อมูล", type="primary"):
                    try:
                        bulk_rows = df_bulk.to_dict(orient="records")
                        for row in bulk_rows:
                            row["audit_username"] = current_username()
                        res = requests.post(f"{API_URL}/employees/bulk", json=bulk_rows, timeout=REQUEST_TIMEOUT)
                        if res.status_code == 200: 
                            clear_api_cache()
                            st.success(res.json()["message"])
                        else:
                            st.error(f"❌ หลังบ้านปฏิเสธข้อมูล: {res.text}")
                    except Exception as e:
                        st.error(f"❌ ไม่สามารถเชื่อมต่อระบบหลังบ้านได้: {e}")

        elif mode == "✏️ ค้นหา/แก้ไข":
            try:
                emp_list = api_get_json("/employees/")
                if not emp_list: st.warning("⚠️ ยังไม่มีข้อมูลพนักงานในระบบ")
                else:
                    emp_options = {f"{e['emp_code']} : {e['first_name']} {e['last_name']}": e for e in emp_list}
                    selected_emp_label = st.selectbox("🔍 ค้นหาพนักงานที่ต้องการแก้ไข", list(emp_options.keys()), key="edit_employee_select")
                    emp_data = emp_options[selected_emp_label]
                    emp_code_key = str(emp_data["emp_code"])

                    if st.session_state.get("active_edit_emp_code") != emp_code_key:
                        previous_emp_code = st.session_state.get("active_edit_emp_code")
                        if previous_emp_code:
                            clear_employee_edit_state(previous_emp_code)
                        clear_employee_edit_state(emp_code_key)
                        st.session_state["active_edit_emp_code"] = emp_code_key

                    with st.form(f"edit_emp_form_{emp_code_key}"):
                        col1, col2, col3 = st.columns(3)
                        with col1: 
                            st.text_input("รหัสพนักงาน", emp_data["emp_code"], disabled=True, key=employee_edit_key(emp_code_key, "emp_code"))
                            edit_first_name = st.text_input("ชื่อจริง", value=emp_data.get("first_name", ""), key=employee_edit_key(emp_code_key, "first_name"))
                            edit_last_name = st.text_input("นามสกุล", value=emp_data.get("last_name", ""), key=employee_edit_key(emp_code_key, "last_name"))
                            edit_machine_id = st.text_input("รหัสเครื่องสแกนนิ้ว (Machine ID)", value=emp_data.get("machine_id", ""), key=employee_edit_key(emp_code_key, "machine_id"))
                        with col2:
                            try: default_dept_index = dept_options.index(emp_data["department"])
                            except: default_dept_index = 0
                            edit_department = st.selectbox("แผนก", dept_options, index=default_dept_index, key=employee_edit_key(emp_code_key, "department"))
                            edit_position = st.text_input("ตำแหน่ง", value=emp_data.get("position", ""), key=employee_edit_key(emp_code_key, "position"))
                            edit_phone = st.text_input("เบอร์โทรศัพท์", value=emp_data.get("phone", ""), key=employee_edit_key(emp_code_key, "phone"))
                        with col3: 
                            edit_status = st.checkbox("สถานะ (ทำงานอยู่)", value=emp_data.get("is_active", True), key=employee_edit_key(emp_code_key, "is_active"))
                            edit_sso = st.checkbox("หักประกันสังคม (SSO 5%)", value=emp_data.get("is_sso", True), key=employee_edit_key(emp_code_key, "is_sso")) 
                            edit_address = st.text_area("ที่อยู่", value=emp_data.get("address", ""), height=68, key=employee_edit_key(emp_code_key, "address"))
                            # 🟢 เพิ่ม วันเริ่มงาน เข้าไปในส่วนแก้ไข
                            try: current_start = datetime.datetime.strptime(emp_data.get('start_date', str(datetime.date.today())), '%Y-%m-%d').date()
                            except: current_start = datetime.date.today()
                            edit_start_date = st.date_input("วันที่เริ่มงาน", value=current_start, key=employee_edit_key(emp_code_key, "start_date"))
                            
                        col4, col5 = st.columns(2)
                        with col4: edit_base_salary = st.number_input("ฐานเงินเดือน", value=float(emp_data.get("base_salary", 0.0)), min_value=0.0, step=1000.0, key=employee_edit_key(emp_code_key, "base_salary"))
                        with col5: 
                            edit_account_no = st.text_input("เลขบัญชี", value=emp_data.get("account_no", ""), key=employee_edit_key(emp_code_key, "account_no"))
                            edit_tax_info = st.text_input("ลดหย่อนภาษี", value=emp_data.get("tax_info", ""), key=employee_edit_key(emp_code_key, "tax_info"))

                        col_service1, col_service2 = st.columns(2)
                        service_options = ["AUTO", "FIXED_50", "FIXED", "NONE"]
                        try: service_index = service_options.index(emp_data.get("service_type", "AUTO"))
                        except: service_index = 0
                        with col_service1:
                            edit_service_type = st.selectbox("Service Type", service_options, index=service_index, key=employee_edit_key(emp_code_key, "service_type"))
                        with col_service2:
                            edit_service_percent = st.number_input("Service Percent", value=float(emp_data.get("service_percent", 100.0)), min_value=0.0, max_value=100.0, step=5.0, key=employee_edit_key(emp_code_key, "service_percent"))
                            
                        if st.form_submit_button("🔄 อัปเดตข้อมูล", type="primary"):
                            update_payload = {
                                "machine_id": edit_machine_id,
                                "first_name": edit_first_name, 
                                "last_name": edit_last_name, 
                                "department": edit_department, 
                                "position": edit_position, 
                                "phone": edit_phone, 
                                "address": edit_address, 
                                "tax_info": edit_tax_info, 
                                "base_salary": edit_base_salary, 
                                "account_no": edit_account_no, 
                                "is_active": edit_status, 
                                "is_sso": edit_sso,
                                "service_type": edit_service_type,
                                "service_percent": edit_service_percent,
                                "start_date": str(edit_start_date), # 🟢 ส่งข้อมูลวันเริ่มงานกลับไป
                                "audit_username": current_username()
                            }
                            res_update = requests.put(f"{API_URL}/employees/{emp_data['emp_code']}", json=update_payload, timeout=REQUEST_TIMEOUT)
                            if res_update.status_code == 200:
                                clear_api_cache()
                                clear_employee_edit_state(emp_code_key)
                                st.session_state["employee_edit_success"] = res_update.json()["message"]
                                st.rerun()
                            else:
                                st.error("❌ ขัดข้อง")
                    if st.session_state.get("employee_edit_success"):
                        st.success(st.session_state.pop("employee_edit_success"))
            except Exception: st.error("❌ เชื่อมต่อหลังบ้านไม่ได้")
            
        elif mode == "📄 โหลดรายงานพนักงาน":
            try:
                emp_list = api_get_json("/employees/")
                if not emp_list: st.warning("ยังไม่มีข้อมูลพนักงาน")
                else:
                    st.success(f"✅ ดึงข้อมูลพนักงานสำเร็จจำนวน {len(emp_list)} คน")
                    emp_pdf = generate_pdf_emp_report(emp_list)
                    st.download_button("📥 โหลดรายงานพนักงาน (PDF)", data=emp_pdf, file_name=f"Employee_DB_{datetime.date.today()}.pdf", mime="application/pdf", type="primary")
            except: st.error("❌ เชื่อมต่อหลังบ้านไม่ได้")

    with tab2:
        st.header("สั่งรันเงินเดือนประจำรอบ")
        col_m, col_y, col_d = st.columns(3)
        month_options = ["", "January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
        year_options = ["", "2026", "2027", "2028", "2029", "2030", "2031", "2032"]
        with col_m: sel_month = st.selectbox("📅 เลือกเดือน", month_options, format_func=lambda value: "เลือกเดือน" if value == "" else value)
        with col_y: sel_year = st.selectbox("🗓️ เลือกปี", year_options, format_func=lambda value: "เลือกปี" if value == "" else value)
        with col_d: payment_date = st.date_input("💰 วันที่เงินเข้าบัญชี")
        payroll_period_selected = bool(sel_month and sel_year)
        cycle_name = f"{sel_month}-{sel_year}" if payroll_period_selected else ""
        selected_lock_status = payroll_lock_status(cycle_name) if payroll_period_selected else {"is_locked": False}
        if payroll_period_selected:
            render_payroll_lock_badge(selected_lock_status)
        else:
            st.warning("กรุณาเลือกเดือนและปีเงินเดือนก่อนคำนวณ")

        st.markdown("---")
        st.subheader("⏱️ อัปโหลดข้อมูลรายรับ-รายจ่ายเพิ่มเติม (Excel)")
        
        st.info("💡 หัวคอลัมน์ Excel: `emp_code`, `emp_name`, `ot_15_hours`, `ot_1_hours`, `late_mins`, `sick_days`, `absent_days`, `leave_hours`, `other_benefits`, `backpay`, `company_loan`, `student_loan`, `sso_manual` (sick_days เก็บประวัติเท่านั้น ไม่กระทบเงินเดือน / ใส่ยอดประกันสังคมสำหรับคนที่ต้องการล็อคยอด ถ้าไม่ใส่ระบบจะคิด 5% ตามปกติ)")
        
        payroll_modify_disabled = (not payroll_period_selected) or bool(selected_lock_status.get("is_locked"))
        time_file = st.file_uploader("📂 อัปโหลดไฟล์ Excel", type=["xlsx", "csv"], key="payroll_file", disabled=payroll_modify_disabled)
        time_data_list = [] 
        if time_file is not None:
            df_time = read_uploaded_table(time_file.name, time_file.getvalue())
            df_time['emp_code'] = df_time['emp_code'].astype(str).str.replace(r'\.0$', '', regex=True)
            time_data_list = df_time.fillna(0).to_dict(orient="records")

        if st.button("🚀 รันระบบประมวลผลทันที", type="primary", use_container_width=True, disabled=payroll_modify_disabled):
            if not payroll_period_selected:
                st.warning("กรุณาเลือกเดือนและปีเงินเดือนก่อนคำนวณ")
                st.stop()
            payload = {
                "cycle_name": cycle_name,
                "payroll_month": sel_month,
                "payroll_year": sel_year,
                "payment_date": str(payment_date),
                "time_data": time_data_list,
                "audit_username": current_username()
            }
            try:
                with st.spinner("กำลังประมวลผล..."):
                    res = requests.post(f"{API_URL}/payroll/calculate", json=payload, timeout=REQUEST_TIMEOUT)
                    if res.status_code == 200: clear_api_cache(); st.success(res.json()["message"]); st.balloons()
                    else: st.error(f"❌ {res.text}")
            except: st.error("❌ เชื่อมต่อระบบหลังบ้านไม่ได้")

    with tab3:
        st.header("ดาวน์โหลดเอกสารและรายงาน")
        try:
            available_cycles = list(dict.fromkeys(api_get_json("/payroll/cycles")))
        except: available_cycles = []

        if not available_cycles: st.info("📌 ยังไม่มีข้อมูลรอบการจ่ายเงินเดือนในระบบ")
        else:
            search_cycle = st.selectbox("📂 เลือกรอบการจ่ายที่ต้องการดาวน์โหลด", available_cycles, key="report_cycle")
            report_lock_status = payroll_lock_status(search_cycle)
            render_payroll_lock_badge(report_lock_status)

            with st.expander("Payroll Month Lock"):
                if not report_lock_status.get("is_locked"):
                    lock_confirm = st.checkbox("Confirm lock payroll month", key=f"lock_confirm_{search_cycle}")
                    lock_note = st.text_input("Lock note", key=f"lock_note_{search_cycle}")
                    if st.button("🔒 Lock Payroll Month", use_container_width=True, disabled=not lock_confirm):
                        res = requests.post(
                            f"{API_URL}/payroll/cycles/{search_cycle}/lock",
                            json={"locked_by": current_username(), "lock_note": lock_note},
                            timeout=REQUEST_TIMEOUT
                        )
                        if res.status_code == 200:
                            clear_api_cache()
                            st.success("Payroll month locked.")
                            st.rerun()
                        else:
                            st.error(f"❌ {res.text}")
                else:
                    unlock_confirm = st.checkbox("Confirm unlock payroll month", key=f"unlock_confirm_{search_cycle}")
                    unlock_reason = st.text_input("Unlock reason", key=f"unlock_reason_{search_cycle}")
                    if st.button("🔓 Unlock Payroll Month", use_container_width=True, disabled=(not unlock_confirm or not unlock_reason.strip())):
                        res = requests.post(
                            f"{API_URL}/payroll/cycles/{search_cycle}/unlock",
                            json={
                                "unlocked_by": current_username(),
                                "role": st.session_state.get("role", ""),
                                "unlock_reason": unlock_reason
                            },
                            timeout=REQUEST_TIMEOUT
                        )
                        if res.status_code == 200:
                            clear_api_cache()
                            st.success("Payroll month unlocked.")
                            st.rerun()
                        else:
                            st.error(f"❌ {res.text}")
            
            st.markdown("---")
            st.subheader("⚖️ ตัวปรับสมดุลเศษสตางค์ (สำหรับไฟล์ธนาคาร SCB)")
            adj_mode = st.radio("เลือกปรับเศษ 0.01 เพื่อให้ยอดตรงกับธนาคาร:", 
                               ["❌ ไม่ปรับ", "➕ บวก 0.01", "➖ ลบ 0.01"], 
                               horizontal=True, key="adj_radio")
            
            col_btn1, col_btn2 = st.columns(2)
            with col_btn1: search_clicked = st.button("🔍 ค้นหาข้อมูล", type="primary", use_container_width=True)
            with col_btn2: delete_clicked = st.button("🗑️ ลบข้อมูลรอบนี้ทิ้ง", use_container_width=True, disabled=bool(report_lock_status.get("is_locked")))

            if delete_clicked:
                res = requests.delete(f"{API_URL}/payroll/{search_cycle}", params={"username": current_username()}, timeout=REQUEST_TIMEOUT)
                if res.status_code == 200:
                    clear_api_cache()
                    st.rerun()
                else:
                    st.error(f"❌ {res.text}")

            if search_clicked:
                try:
                    data = api_get_json(f"/payroll/{search_cycle}")
                    if data:
                        payroll_list = data["transactions"]
                        st.success(f"พบข้อมูลรอบ {data['cycle_name']} (พนักงาน {len(payroll_list)} คน)")
                        
                        # 🟢 1. เตรียมข้อมูลพื้นฐานและตัวแปรเพื่อป้องกัน Error
                        valid_txns = [t for t in payroll_list if t['net_salary'] > 0]
                        bank_errors = []
                        txt_bank = None
                        
                        # 🟢 2. จัดการเรื่องการปรับเศษ 0.01 (ถ้ามี)[cite: 2]
                        if len(valid_txns) >= 6:
                            if adj_mode == "➕ บวก 0.01": valid_txns[5]['net_salary'] = round(valid_txns[5]['net_salary'] + 0.01, 2)
                            elif adj_mode == "➖ ลบ 0.01": valid_txns[5]['net_salary'] = round(valid_txns[5]['net_salary'] - 0.01, 2)
                        
                        # 🟢 3. สร้างไฟล์เอกสาร PDF (Payslips & Summary)[cite: 2]
                        pdf_payslips = generate_pdf_payslips(payroll_list, data['cycle_name'])
                        pdf_summary = generate_pdf_payroll_summary(payroll_list, data['cycle_name'])
                        
                        # 🟢 4. สร้างไฟล์สรุปเงินเดือน Excel[cite: 2]
                        summary_data = []
                        for i, t in enumerate(payroll_list, 1):
                            summary_data.append({"No.": i, "Name/Surname": f"{t['first_name']} {t['last_name']}", "Net Pay": t['net_salary']}) 
                        df_summary_ex = pd.DataFrame(summary_data)
                        buffer_summary = io.BytesIO()
                        with pd.ExcelWriter(buffer_summary, engine='openpyxl') as writer: df_summary_ex.to_excel(writer, index=False)
                        excel_summary = buffer_summary.getvalue()

                        # 🟢 5. สร้างรายงาน JV บัญชี (ยึดตามรูปแบบ Aonang Fiore Resort เป๊ะๆ)
                        jv_lines = []
                        df_pay = pd.DataFrame(payroll_list)
                        t_net = df_pay['net_salary'].sum()
                        t_sso = df_pay['sso_deduction'].sum() * 2 
                        t_loan = df_pay['company_loan'].sum() + df_pay['student_loan'].sum()
                        
                        # --- ฝั่ง Credit (เครดิต) ---
                        jv_lines.append({"ACC. NO.": "2003101", "NAME": "เงินเดือนค้างจ่าย", "DEBIT": 0.0, "CREDIT": round(t_net, 2)})
                        jv_lines.append({"ACC. NO.": "2003102", "NAME": "เงินประกันสังคมค้างจ่าย", "DEBIT": 0.0, "CREDIT": round(t_sso, 2)})
                        if t_loan > 0: 
                            jv_lines.append({"ACC. NO.": "2003130", "NAME": "เงินหักพนักงานรอตัดลูกหนี้", "DEBIT": 0.0, "CREDIT": round(t_loan, 2)})
                            
                        # --- ฝั่ง Debit (เดบิตแยกตามแผนกและประเภทเงิน) ---
                        gl_mapping = {
                            "RM-ต้อนรับส่วนหน้า": {"sal": "4051101", "ot": "4051111", "sso": "4051202", "ben": "4051299", "pre": "RM-", "n_sal": "เงินเดือนแผนกต้อนรับส่วนหน้า", "n_ot": "เงินOT แผนกต้อนรับ"},
                            "RM-แม่บ้าน": {"sal": "4051102", "ot": "4051112", "sso": "4051202", "ben": "4051299", "pre": "RM-", "n_sal": "เงินเดือนแผนกแม่บ้าน", "n_ot": "เงิน OTแผนกแม่บ้าน"},
                            "FB-ห้องอาหาร": {"sal": "4151101", "ot": "4151111", "sso": "4151202", "ben": "4051299", "pre": "FB-", "n_sal": "เงินเดือนแผนกห้องอาหาร", "n_ot": "เงินOTแผนกห้องอาหาร"},
                            "FB-ครัวผลิต": {"sal": "4151102", "ot": "4151112", "sso": "4151202", "ben": "4051299", "pre": "FB-", "n_sal": "เงินเดือนแผนกครัวผลิต", "n_ot": "เงินOTแผนกครัวผลิต"},
                            "MY-เรือ MY Lalida": {"sal": "4251101", "ot": "4251111", "sso": "4251202", "ben": "4251299", "pre": "MY-", "n_sal": "เงินเดือนเรือMY Lalida", "n_ot": "เงินOTเรือMY Lalida"},
                            "TU-Zipline": {"sal": "4351101", "ot": "4351111", "sso": "4351202", "ben": "4051299", "pre": "TU-", "n_sal": "เงินเดือนZipline", "n_ot": "เงินOT Zipline"},
                            "AM-บริหารส่วนกลาง": {"sal": "6051101", "ot": "6051111", "sso": "6051202", "ben": "6051299", "pre": "AM-", "n_sal": "เงินเดือนแผนกบริหารส่วนกลาง", "n_ot": "เงินOTแผนกบริหาร"},
                            "AC-บัญชี": {"sal": "6151101", "ot": "6151111", "sso": "6151202", "ben": "6151299", "pre": "AC-", "n_sal": "เงินเดือนแผนกบัญชี", "n_ot": "เงินOTแผนกบัญชี"},
                            "SM-การตลาด": {"sal": "6251101", "ot": "6251111", "sso": "6251202", "ben": "6251299", "pre": "SM-", "n_sal": "เงินเดือนแผนกการตลาด", "n_ot": "เงินOTแผนกการตลาด"},
                            "EN-ช่างทั่วไป": {"sal": "6351101", "ot": "6351111", "sso": "6351202", "ben": "6351299", "pre": "EN-", "n_sal": "เงินเดือนแผนกช่างทั่วไป", "n_ot": "เงินOT แผนกช่างทั่วไป"},
                            "GN-สวน-ภูมิทัศน์": {"sal": "6451101", "ot": "6451111", "sso": "6451202", "ben": "6451299", "pre": "GN-", "n_sal": "เงินเดือนแผนกสวน-ภูมิทัศน์", "n_ot": "เงินOT แผนกสวน"},
                            "HR-ทรัพยากรบุคคล": {"sal": "7051101", "ot": "7051111", "sso": "7051202", "ben": "7051299", "pre": "HR-", "n_sal": "เงินเดือนแผนกทรัพยากรบุคคล", "n_ot": "เงินOT ทรัพยากรบุคคล"}
                        }
                        
                        for dept in df_pay['department'].unique():
                            d_data = df_pay[df_pay['department'] == dept]
                            c = gl_mapping.get(dept, {"sal": "999", "ot": "999", "sso": "999", "ben": "999", "pre": "", "n_sal": "เงินเดือน", "n_ot": "OT"})
                            
                            d_sal = round(d_data['base_salary'].sum() - d_data['leave_deduction'].sum(), 2)
                            d_ot = round(d_data['ot_amount'].sum(), 2)
                            d_sso = round(d_data['sso_deduction'].sum(), 2) # เฉพาะส่วนของพนักงานที่บันทึกเป็นค่าใช้จ่ายแผนก
                            d_ben = round(d_data['other_benefits'].sum() + d_data['backpay'].sum(), 2)

                            if d_sal > 0: jv_lines.append({"ACC. NO.": c['sal'], "NAME": f"{c['pre']}{c['n_sal']}", "DEBIT": d_sal, "CREDIT": 0.0})
                            if d_ot > 0: jv_lines.append({"ACC. NO.": c['ot'], "NAME": f"{c['pre']}{c['n_ot']}", "DEBIT": d_ot, "CREDIT": 0.0})
                            if d_sso > 0: jv_lines.append({"ACC. NO.": c['sso'], "NAME": f"{c['pre']}เงินสมทบประกันสังคม", "DEBIT": d_sso, "CREDIT": 0.0})
                            if d_ben > 0: 
                                b_name = "ค่าสวัสดิการอื่น ๆ" if c['ben'] == "7051299" else "เงินสวัสดิการอื่นๆ"
                                jv_lines.append({"ACC. NO.": c['ben'], "NAME": f"{c['pre']}{b_name}", "DEBIT": d_ben, "CREDIT": 0.0})
                        
                        df_jv = pd.DataFrame(jv_lines)
                        buffer_jv = io.BytesIO()
                        with pd.ExcelWriter(buffer_jv, engine='openpyxl') as writer: 
                            df_jv.to_excel(writer, index=False)
                        excel_jv = buffer_jv.getvalue()

                        # 🟢 6. สร้างไฟล์ธนาคาร SCB (ฉบับเกราะป้องกันที่เคยผ่าน)[cite: 2]
                        bank_lines = []
                        current_dt = datetime.datetime.now()
                        header_dt_str = current_dt.strftime("%d%m%y%H%M%S")
                        pay_date_str = str(data.get('payment_date', current_dt.strftime("%Y-%m-%d"))).replace("-", "")
                        comp_acc = "8013003558"
                        
                        total_count = len(valid_txns)
                        total_amount = sum(round(t['net_salary'], 2) for t in valid_txns)
                        bank_lines.append(f"HEADER|{header_dt_str}PAY|")
                        bank_lines.append(f"BCHDET|{header_dt_str}|PAY|{pay_date_str}|{comp_acc}|{comp_acc}|{total_amount:.2f}|{total_count}||")
                        for t in valid_txns:
                            raw_acc = str(t.get('account_no', '')).strip().replace('-', '').replace(' ', '')
                            acc_no = re.sub(r'\D', '', raw_acc).zfill(10)
                            clean_name = " ".join(f"{t.get('first_name', '')} {t.get('last_name', '')}".split())
                            bank_lines.append(f"TXNDET||{acc_no}||014|0111|{round(t['net_salary'], 2):.2f}||OUR|N||N||{clean_name}||||N|||N|N||||N||")
                        bank_lines.append(f"TRAILR|1|{total_count}|{total_amount:.2f}")
                        txt_bank = "\r\n".join(bank_lines).encode('utf-8')

                        # 🟢 7. แสดงผลปุ่มดาวน์โหลดทั้งหมด[cite: 2]
                        st.markdown("---")
                        col_doc1, col_doc2 = st.columns(2)
                        with col_doc1:
                            st.subheader("📑 เอกสารสรุป")
                            st.download_button("📄 1. โหลดสลิปรายบุคคล (PDF)", data=pdf_payslips, file_name=f"Payslips_{search_cycle}.pdf", mime="application/pdf", use_container_width=True)
                            st.download_button("📊 2. โหลดสรุปเงินเดือน (Excel)", data=excel_summary, file_name=f"Payroll_Summary_{search_cycle}.xlsx", use_container_width=True)
                            st.download_button("📑 3. โหลดสรุปเงินเดือน (PDF แนวนอน)", data=pdf_summary, file_name=f"Payroll_Summary_{search_cycle}.pdf", mime="application/pdf", use_container_width=True)
                        with col_doc2:
                            st.subheader("🏦 บัญชีและการโอน (Bank/JV)")
                            
                            # สร้างไฟล์ PDF JV ก่อนสร้างปุ่ม[cite: 2]
                            pdf_jv = generate_pdf_jv(df_jv, data['cycle_name'])
                            
                            # ปุ่มดาวน์โหลด JV แบบ Excel (เดิม)[cite: 2]
                            st.download_button("🔵 1. ใบสำคัญทั่วไป JV (Excel)", data=excel_jv, file_name=f"Accounting_JV_{search_cycle}.xlsx", use_container_width=True)
                            
                            # 🟢 เพิ่มปุ่มดาวน์โหลด JV แบบ PDF (ใหม่)[cite: 2]
                            st.download_button("📄 2. ใบสำคัญทั่วไป JV (PDF)", data=pdf_jv, file_name=f"Accounting_JV_{search_cycle}.pdf", mime="application/pdf", use_container_width=True)
                            
                            if bank_errors:
                                st.error("❌ พบข้อผิดพลาดในข้อมูลพนักงาน ไม่สามารถสร้างไฟล์ธนาคารได้")
                                st.dataframe(pd.DataFrame(bank_errors), use_container_width=True)
                            elif txt_bank:
                                safe_cycle = re.sub(r'[^0-9A-Za-z_-]+', '_', str(search_cycle)).strip('_')
                                # เปลี่ยนลำดับปุ่มเป็นหมายเลข 3[cite: 2]
                                st.download_button(f"💰 3. ไฟล์ส่งธนาคาร SCB ({adj_mode})", data=txt_bank, file_name=f"SCB_PAY_{safe_cycle}.txt", mime="text/plain", use_container_width=True)
                    else: st.error("❌ ไม่พบข้อมูลการจ่ายเงินในรอบที่เลือก")
                except Exception as e: st.error(f"❌ เกิดข้อผิดพลาดในการประมวลผลรายงาน: {e}")

    with tab4:
        st.header("⏱️ ประมวลผลเวลาทำงานจากเครื่อง ZK/Neocal")
        st.info("ระบบจะสรุปข้อมูลสแกนนิ้วอัตโนมัติ (รองรับไฟล์แบบแยกราย Sheet)")
        
        col_t1, col_t2, col_t3 = st.columns(3)
        with col_t1: 
            s_in = st.time_input("เวลาเข้างานปกติ", datetime.time(8, 0))
        with col_t2: 
            s_out = st.time_input("เวลาเลิกงานปกติ", datetime.time(17, 30))
        with col_t3: 
            quota = st.number_input("โควตาสายสะสม/เดือน (นาที)", value=30)

        punch_file = st.file_uploader("📂 เลือกไฟล์ Punch Report (Excel)", type=['xlsx'], key="punch_final_v2")
        
        if punch_file:
            if st.button("🚀 เริ่มประมวลผลข้อมูล", type="primary", use_container_width=True):
                try:
                    # ส่งข้อมูลพนักงานทั้งหมดเข้า parser เพื่อจับคู่ได้ทั้ง Machine ID และรหัสพนักงาน
                    mapping = {str(i): e for i, e in enumerate(api_get_json("/employees/"))}
                    
                    # ประมวลผลไฟล์[cite: 3]
                    result_df = process_attendance(punch_file, mapping, s_in, s_out, quota)
                    
                    if not result_df.empty:
                        result_df = result_df.sort_values(by=['แผนก', 'รหัสพนักงาน'])
                        st.subheader("📊 ผลลัพธ์การประมวลผล")
                        st.dataframe(result_df, use_container_width=True)
                        
                        output = io.BytesIO()
                        with pd.ExcelWriter(output, engine='openpyxl') as writer:
                            result_df.to_excel(writer, index=False)
                        
                        st.markdown("---")
                        st.success("✅ ประมวลผลสำเร็จ!")
                        st.download_button(
                            label="📥 ดาวน์โหลดไฟล์สรุปยอดสาย (Excel)",
                            data=output.getvalue(),
                            file_name=f"Attendance_Summary_{datetime.date.today()}.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            use_container_width=True
                        )
                    else:
                        st.warning("⚠️ ไม่พบข้อมูลพนักงานที่ตรงกับในไฟล์ หรือโครงสร้างไฟล์ไม่ถูกต้อง")
                except Exception as e:
                    st.error(f"❌ ขัดข้อง: {str(e)}")

    with tab5:
        st.header("📜 ประวัติพนักงานเข้าดูสลิป")

        if st.button("🔄 อัปเดตข้อมูลล่าสุด", use_container_width=True):
            api_get_json.clear()

        try:
            logs_data = api_get_json("/logs/")
            if logs_data:
                df_logs = pd.DataFrame(logs_data)
                st.dataframe(
                    df_logs,
                    column_config={
                        "user": "ชื่อพนักงาน",
                        "action": "การกระทำ",
                        "timestamp": "วัน-เวลาที่เข้าดู"
                    },
                    use_container_width=True
                )
            else:
                st.info("ยังไม่มีพนักงานคนไหนเข้ามาดูสลิปในขณะนี้")
        except Exception as e:
            st.error(f"❌ ไม่สามารถดึงประวัติการใช้งานได้: {e}")
