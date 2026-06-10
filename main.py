from fastapi import FastAPI, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from sqlalchemy import func, inspect, text
import database as db
from typing import List
import datetime
from decimal import Decimal, ROUND_HALF_UP

app = FastAPI()

# 🟢 บรรทัดนี้ช่วยสร้างตารางให้ใหม่ทันทีถ้าฐานข้อมูลหาย
db.Base.metadata.create_all(bind=db.engine)

def add_column_if_missing(conn, table_name, existing_columns, column_name, column_sql):
    if column_name not in existing_columns:
        conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_sql}"))

def ensure_schema():
    inspector = inspect(db.engine)
    employee_columns = {col["name"] for col in inspector.get_columns("employees")}
    with db.engine.begin() as conn:
        add_column_if_missing(conn, "employees", employee_columns, "service_type", "VARCHAR DEFAULT 'AUTO'")
        add_column_if_missing(conn, "employees", employee_columns, "service_percent", "FLOAT DEFAULT 100.0")

        if "payroll_transactions" in inspector.get_table_names():
            payroll_columns = {col["name"] for col in inspector.get_columns("payroll_transactions")}
            add_column_if_missing(conn, "payroll_transactions", payroll_columns, "sick_days", "FLOAT DEFAULT 0.0")

        if "service_months" in inspector.get_table_names():
            service_month_columns = {col["name"] for col in inspector.get_columns("service_months")}
            add_column_if_missing(conn, "service_months", service_month_columns, "manual_service_rate", "FLOAT")

        if "service_employees" in inspector.get_table_names():
            service_employee_columns = {col["name"] for col in inspector.get_columns("service_employees")}
            add_column_if_missing(conn, "service_employees", service_employee_columns, "first_name", "VARCHAR")
            add_column_if_missing(conn, "service_employees", service_employee_columns, "last_name", "VARCHAR")
            add_column_if_missing(conn, "service_employees", service_employee_columns, "department", "VARCHAR")
            add_column_if_missing(conn, "service_employees", service_employee_columns, "position", "VARCHAR")
            add_column_if_missing(conn, "service_employees", service_employee_columns, "service_weight", "FLOAT DEFAULT 0.0")
            add_column_if_missing(conn, "service_employees", service_employee_columns, "service_rate", "FLOAT DEFAULT 0.0")
            add_column_if_missing(conn, "service_employees", service_employee_columns, "gross_service", "FLOAT DEFAULT 0.0")
            add_column_if_missing(conn, "service_employees", service_employee_columns, "sick_days", "FLOAT DEFAULT 0.0")
            add_column_if_missing(conn, "service_employees", service_employee_columns, "sick_deduction", "FLOAT DEFAULT 0.0")
            add_column_if_missing(conn, "service_employees", service_employee_columns, "leave_days", "FLOAT DEFAULT 0.0")
            add_column_if_missing(conn, "service_employees", service_employee_columns, "leave_hours", "FLOAT DEFAULT 0.0")
            add_column_if_missing(conn, "service_employees", service_employee_columns, "leave_hour_deduction", "FLOAT DEFAULT 0.0")
            add_column_if_missing(conn, "service_employees", service_employee_columns, "late_hours", "FLOAT DEFAULT 0.0")
            add_column_if_missing(conn, "service_employees", service_employee_columns, "late_deduction", "FLOAT DEFAULT 0.0")
            add_column_if_missing(conn, "service_employees", service_employee_columns, "evaluation_percent", "FLOAT DEFAULT 0.0")
            add_column_if_missing(conn, "service_employees", service_employee_columns, "evaluation_deduction", "FLOAT DEFAULT 0.0")
            add_column_if_missing(conn, "service_employees", service_employee_columns, "deposit_deduction", "FLOAT DEFAULT 0.0")
            add_column_if_missing(conn, "service_employees", service_employee_columns, "net_service", "FLOAT DEFAULT 0.0")
            add_column_if_missing(conn, "service_employees", service_employee_columns, "notes", "VARCHAR")

ensure_schema()

def get_db():
    db_session = db.SessionLocal()
    try:
        yield db_session
    finally:
        db_session.close()

# ==========================================
# 📜 ระบบบันทึกประวัติการใช้งาน (Access Logs)
# ==========================================

@app.post("/logs/")
def create_access_log(data: dict, session: Session = Depends(get_db)):
    new_log = db.AccessLog(
        user=str(data.get("user", "-"))[:200],
        action=str(data.get("action", "-"))[:500],
        timestamp=str(data.get("timestamp") or datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    )
    session.add(new_log)
    session.commit()
    return {"message": "บันทึกประวัติเรียบร้อย"}

@app.get("/logs/")
def get_access_logs(limit: int = 200, session: Session = Depends(get_db)):
    logs = session.query(db.AccessLog).order_by(db.AccessLog.id.desc()).limit(limit).all()
    return [
        {
            "user": log.user,
            "action": log.action,
            "timestamp": log.timestamp
        }
        for log in logs
    ]

# ==========================================
# 👥 ระบบจัดการพนักงาน (Employees)
# ==========================================

@app.get("/employees/")
def get_all_employees(session: Session = Depends(get_db)):
    # 🟢 เรียงลำดับตามแผนก และตามด้วยรหัสพนักงาน
    emps = session.query(db.Employee).order_by(
        db.Employee.department.asc(), 
        db.Employee.emp_code.asc()
    ).all()
    
    result = []
    for emp in emps:
        result.append({
            "emp_code": emp.emp_code,
            "machine_id": emp.machine_id,
            "first_name": emp.first_name,
            "last_name": emp.last_name,
            "position": emp.position,
            "department": emp.department,
            "phone": emp.phone,
            "start_date": str(emp.start_date) if emp.start_date else "",
            "address": emp.address,
            "tax_info": emp.tax_info,
            "base_salary": emp.base_salary,
            "account_no": emp.account_no,
            "is_active": emp.is_active,
            "is_sso": emp.is_sso,
            "service_type": emp.service_type or "AUTO",
            "service_percent": emp.service_percent if emp.service_percent is not None else 100.0
        })
    return result

@app.post("/employees/")
def create_employee(data: dict, session: Session = Depends(get_db)):
    existing = session.query(db.Employee).filter(db.Employee.emp_code == data["emp_code"]).first()
    if existing:
        raise HTTPException(status_code=400, detail="รหัสพนักงานซ้ำในระบบ")
    
    new_emp = db.Employee(
        emp_code=data["emp_code"],
        machine_id=data.get("machine_id", ""),
        first_name=data["first_name"],
        last_name=data["last_name"],
        position=data.get("position", ""),
        department=data.get("department", ""),
        phone=data.get("phone", ""),
        start_date=data.get("start_date", ""),
        address=data.get("address", ""),
        tax_info=data.get("tax_info", ""),
        base_salary=float(data.get("base_salary", 0.0)),
        account_no=data.get("account_no", ""),
        is_sso=data.get("is_sso", True),
        service_type=data.get("service_type", "AUTO"),
        service_percent=float(data.get("service_percent", 100.0))
    )
    session.add(new_emp)
    session.commit()
    return {"message": "เพิ่มพนักงานสำเร็จ"}

@app.put("/employees/{emp_code}")
def update_employee(emp_code: str, data: dict, session: Session = Depends(get_db)):
    emp = session.query(db.Employee).filter(db.Employee.emp_code == emp_code).first()
    if not emp:
        raise HTTPException(status_code=404, detail="ไม่พบพนักงาน")
    
    if "first_name" in data: emp.first_name = data["first_name"]
    if "last_name" in data: emp.last_name = data["last_name"]
    if "department" in data: emp.department = data["department"]
    if "position" in data: emp.position = data["position"]
    if "phone" in data: emp.phone = data["phone"]
    if "address" in data: emp.address = data["address"]
    if "tax_info" in data: emp.tax_info = data["tax_info"]
    if "base_salary" in data: emp.base_salary = float(data["base_salary"])
    if "account_no" in data: emp.account_no = data["account_no"]
    if "is_active" in data: emp.is_active = data["is_active"]
    if "is_sso" in data: emp.is_sso = data["is_sso"]
    if "machine_id" in data: emp.machine_id = data["machine_id"]
    if "service_type" in data: emp.service_type = data["service_type"]
    if "service_percent" in data: emp.service_percent = float(data["service_percent"])
    
    session.commit()
    return {"message": "อัปเดตข้อมูลพนักงานสำเร็จ"}

# 🟢 ฟีเจอร์ Upsert (เพิ่มคนใหม่ + อัปเดตคนเดิม) รับข้อมูล List ได้โดยตรง
@app.post("/employees/bulk")
def bulk_import_employees(employees: list = Body(...), session: Session = Depends(get_db)):
    try:
        added_count = 0
        updated_count = 0
        
        for emp_data in employees:
            emp_code_str = str(emp_data.get("emp_code", "")).strip()
            if not emp_code_str or emp_code_str in ["nan", "", "-"]: 
                continue # ข้ามถ้าไม่มีรหัสพนักงาน

            existing_emp = session.query(db.Employee).filter(db.Employee.emp_code == emp_code_str).first()
            
            if existing_emp:
                # 🟡 อัปเดตพนักงานเดิม
                existing_emp.first_name = str(emp_data.get("first_name", existing_emp.first_name))
                existing_emp.last_name = str(emp_data.get("last_name", existing_emp.last_name))
                existing_emp.position = str(emp_data.get("position", existing_emp.position))
                existing_emp.department = str(emp_data.get("department", existing_emp.department))
                existing_emp.phone = str(emp_data.get("phone", existing_emp.phone))
                existing_emp.start_date = str(emp_data.get("start_date", existing_emp.start_date))
                existing_emp.address = str(emp_data.get("address", existing_emp.address))
                existing_emp.tax_info = str(emp_data.get("tax_info", existing_emp.tax_info))
                
                # ป้องกัน Error กรณี Excel มีช่องว่างในช่องเงินเดือน
                raw_salary = emp_data.get("base_salary", existing_emp.base_salary)
                try: existing_emp.base_salary = float(raw_salary) if str(raw_salary).strip() != "" else 0.0
                except: pass
                
                existing_emp.account_no = str(emp_data.get("account_no", existing_emp.account_no))
                if "is_sso" in emp_data: existing_emp.is_sso = bool(emp_data["is_sso"])
                if "service_type" in emp_data and str(emp_data["service_type"]).strip():
                    existing_emp.service_type = str(emp_data["service_type"]).strip().upper()
                if "service_percent" in emp_data and str(emp_data["service_percent"]).strip() != "":
                    try: existing_emp.service_percent = float(emp_data["service_percent"])
                    except: pass
                if "machine_id" in emp_data and str(emp_data["machine_id"]) not in ["nan", "", "-"]:
                    existing_emp.machine_id = str(emp_data["machine_id"])
                    
                updated_count += 1
            else:
                # 🔵 เพิ่มพนักงานใหม่
                raw_salary = emp_data.get("base_salary", 0.0)
                try: safe_salary = float(raw_salary) if str(raw_salary).strip() != "" else 0.0
                except: safe_salary = 0.0
                
                new_emp = db.Employee(
                    emp_code=emp_code_str,
                    first_name=str(emp_data.get("first_name", "-")),
                    last_name=str(emp_data.get("last_name", "-")),
                    position=str(emp_data.get("position", "-")),
                    department=str(emp_data.get("department", "-")),
                    phone=str(emp_data.get("phone", "-")),
                    start_date=str(emp_data.get("start_date", "-")),
                    address=str(emp_data.get("address", "-")),
                    tax_info=str(emp_data.get("tax_info", "-")),
                    base_salary=safe_salary,
                    account_no=str(emp_data.get("account_no", "-")),
                    is_sso=bool(emp_data.get("is_sso", True)),
                    service_type=str(emp_data.get("service_type", "AUTO")).strip().upper() or "AUTO",
                    service_percent=float(emp_data.get("service_percent", 100.0) or 100.0)
                )
                if "machine_id" in emp_data and str(emp_data["machine_id"]) not in ["nan", "", "-"]:
                    new_emp.machine_id = str(emp_data["machine_id"])
                    
                session.add(new_emp)
                added_count += 1
                
        session.commit()
        return {"message": f"✅ นำเข้าสำเร็จ: เพิ่มพนักงานใหม่ {added_count} คน | อัปเดตข้อมูลเดิม {updated_count} คน"}
        
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=f"เกิดข้อผิดพลาด: {str(e)}")

# ==========================================
# 🧾 ระบบ Service Charge (Beta / Phase 1)
# ==========================================

def serialize_service_month(item):
    total_service = (
        float(item.room_service or 0)
        + float(item.fb_service or 0)
        + float(item.zipline_service or 0)
        + float(item.other_service or 0)
    )
    return {
        "id": item.id,
        "month": item.month,
        "year": item.year,
        "room_service": item.room_service or 0.0,
        "fb_service": item.fb_service or 0.0,
        "zipline_service": item.zipline_service or 0.0,
        "other_service": item.other_service or 0.0,
        "total_service": total_service,
        "employee_pool": total_service * 0.60,
        "welfare_fund": total_service * 0.20,
        "resort_fund": total_service * 0.20,
        "manual_service_rate": item.manual_service_rate,
        "note": item.note or ""
    }

def round_baht(value):
    return int(Decimal(str(value or 0)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))

def parse_date(value):
    try:
        return datetime.datetime.strptime(str(value), "%Y-%m-%d").date()
    except:
        return None

def calculate_service_weight(emp, service_month):
    service_type = str(emp.service_type or "AUTO").upper()
    if service_type == "NONE":
        return 0.0
    if service_type == "FIXED":
        return float(emp.service_percent or 0) / 100.0

    start_date = parse_date(emp.start_date)
    if not start_date:
        return 1.0

    months_worked = (int(service_month.year) - start_date.year) * 12 + (month_number(service_month.month) - start_date.month) + 1
    if months_worked <= 0:
        return 0.0

    if start_date.day <= 10:
        if months_worked in [1, 2, 3]:
            return 0.5
        return 1.0

    if months_worked == 1:
        return 0.0
    if months_worked in [2, 3, 4]:
        return 0.5
    return 1.0

def eligible_service_month_index(emp, service_month):
    if str(emp.service_type or "AUTO").upper() == "NONE":
        return 0

    start_date = parse_date(emp.start_date)
    if not start_date:
        return 999

    months_worked = (int(service_month.year) - start_date.year) * 12 + (month_number(service_month.month) - start_date.month) + 1
    if months_worked <= 0:
        return 0
    if start_date.day <= 10:
        return months_worked
    return months_worked - 1

def service_month_key(service_month):
    return (int(service_month.year or 0), month_number(service_month.month))

def service_payroll_cycle_name(service_month):
    return f"{service_month.month}-{service_month.year}"

def payroll_service_inputs(session, service_month):
    cycle_name = service_payroll_cycle_name(service_month)
    rows = session.query(db.PayrollTransaction).filter(
        db.PayrollTransaction.cycle_name == cycle_name
    ).all()

    return {
        str(row.emp_code): {
            "sick_days": float(row.sick_days or 0),
            "leave_days": float(row.unpaid_leave_days or 0),
            "leave_hours": float(row.leave_hours or 0),
            "late_hours": float(row.late_mins or 0) / 60,
            "source": "Imported from Payroll"
        }
        for row in rows
    }

def service_deposit_total_before(session, emp_code, service_month_id, current_service_month):
    current_key = service_month_key(current_service_month)
    rows = session.query(db.ServiceEmployee, db.ServiceMonth).join(
        db.ServiceMonth,
        db.ServiceEmployee.service_month_id == db.ServiceMonth.id
    ).filter(
        db.ServiceEmployee.emp_code == str(emp_code),
        db.ServiceEmployee.service_month_id != service_month_id
    ).all()

    total = 0
    for service_employee, service_month in rows:
        if service_month_key(service_month) < current_key:
            total += round_baht(service_employee.deposit_deduction or 0)
    return total

def default_service_deposit(emp, service_month, service_weight, prior_deposit_total=0):
    if service_weight <= 0:
        return 0
    if prior_deposit_total >= 1500:
        return 0
    if eligible_service_month_index(emp, service_month) in [1, 2, 3]:
        return min(500, 1500 - prior_deposit_total)
    return 0

def calculate_late_deduction(gross_service, late_hours):
    late_hours = float(late_hours or 0)
    if late_hours <= 0:
        return 0
    if late_hours <= 5:
        return round_baht(float(gross_service or 0) * late_hours * 0.10)
    return round_baht(gross_service)

def calculate_service_amounts(row):
    gross_service = round_baht(row.get("gross_service", 0))
    sick_days = float(row.get("sick_days", 0) or 0)
    leave_hours = float(row.get("leave_hours", 0) or 0)
    late_hours = float(row.get("late_hours", 0) or 0)
    evaluation_percent = float(row.get("evaluation_percent", 0) or 0)
    deposit_deduction = round_baht(row.get("deposit_deduction", 0))

    sick_deduction = round_baht(gross_service / 30 * sick_days)
    leave_hour_deduction = round_baht(gross_service / 30 / 8 * leave_hours)
    late_deduction = calculate_late_deduction(gross_service, late_hours)
    evaluation_deduction = round_baht(gross_service * evaluation_percent / 100)
    net_service = max(
        0,
        round_baht(
            gross_service
            - sick_deduction
            - leave_hour_deduction
            - late_deduction
            - evaluation_deduction
            - deposit_deduction
        )
    )

    return {
        "sick_deduction": sick_deduction,
        "leave_hours": leave_hours,
        "leave_hour_deduction": leave_hour_deduction,
        "late_hours": late_hours,
        "late_deduction": late_deduction,
        "evaluation_deduction": evaluation_deduction,
        "net_service": net_service
    }

def month_number(month_name):
    month_options = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
    try:
        return month_options.index(str(month_name)) + 1
    except ValueError:
        return 1

def serialize_service_employee(row):
    return {
        "id": row.id,
        "service_month_id": row.service_month_id,
        "emp_code": row.emp_code,
        "first_name": row.first_name or "",
        "last_name": row.last_name or "",
        "department": row.department or "",
        "position": row.position or "",
        "service_type": row.service_type or "AUTO",
        "service_percent": row.service_percent or 0.0,
        "service_weight": row.service_weight or 0.0,
        "service_rate": row.service_rate or 0.0,
        "fixed_amount": row.fixed_amount or 0.0,
        "gross_service": row.gross_service or 0.0,
        "sick_days": row.sick_days or 0.0,
        "sick_deduction": row.sick_deduction or 0.0,
        "leave_days": row.leave_days or 0.0,
        "leave_hours": row.leave_hours or 0.0,
        "leave_hour_deduction": row.leave_hour_deduction or 0.0,
        "late_hours": row.late_hours or 0.0,
        "late_deduction": row.late_deduction or 0.0,
        "evaluation_percent": row.evaluation_percent or 0.0,
        "evaluation_deduction": row.evaluation_deduction or 0.0,
        "deposit_deduction": row.deposit_deduction or 0.0,
        "net_service": row.net_service or 0.0,
        "notes": row.notes or ""
    }

def service_summary(service_month, rows):
    employee_pool = serialize_service_month(service_month)["employee_pool"]
    total_weight = sum(float(row.get("service_weight", 0) or 0) for row in rows)
    calculated_rate = round_baht(employee_pool / total_weight) if total_weight > 0 else 0
    manual_rate = service_month.manual_service_rate
    service_rate = round_baht(manual_rate) if manual_rate not in [None, ""] else calculated_rate
    actual_paid = sum(round_baht(row.get("net_service", 0)) for row in rows)
    return {
        "employee_pool": round_baht(employee_pool),
        "total_weight": total_weight,
        "calculated_service_rate": calculated_rate,
        "manual_service_rate": round_baht(manual_rate) if manual_rate not in [None, ""] else None,
        "service_rate": service_rate,
        "actual_employee_paid": actual_paid,
        "balance_returned_to_resort": round_baht(employee_pool - actual_paid),
        "exceeds_employee_pool": actual_paid > round_baht(employee_pool)
    }

@app.get("/api/service/months")
@app.get("/service/months")
def get_service_months(session: Session = Depends(get_db)):
    rows = session.query(db.ServiceMonth).order_by(db.ServiceMonth.year.desc(), db.ServiceMonth.id.desc()).all()
    return [serialize_service_month(row) for row in rows]

@app.get("/api/service/months/{year}/{month}")
@app.get("/service/months/{year}/{month}")
def get_service_month(year: int, month: str, session: Session = Depends(get_db)):
    item = session.query(db.ServiceMonth).filter(
        db.ServiceMonth.year == year,
        db.ServiceMonth.month == month
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="ไม่พบข้อมูล Service Charge เดือนนี้")
    return serialize_service_month(item)

@app.post("/api/service/months")
@app.post("/service/months")
def upsert_service_month(data: dict, session: Session = Depends(get_db)):
    month = str(data.get("month", "")).strip()
    year = int(data.get("year", datetime.date.today().year))
    if not month:
        raise HTTPException(status_code=400, detail="กรุณาระบุเดือน")

    item = session.query(db.ServiceMonth).filter(
        db.ServiceMonth.year == year,
        db.ServiceMonth.month == month
    ).first()
    if not item:
        item = db.ServiceMonth(month=month, year=year)
        session.add(item)

    item.room_service = float(data.get("room_service", 0.0) or 0.0)
    item.fb_service = float(data.get("fb_service", 0.0) or 0.0)
    item.zipline_service = float(data.get("zipline_service", 0.0) or 0.0)
    item.other_service = float(data.get("other_service", 0.0) or 0.0)
    manual_rate = data.get("manual_service_rate", None)
    item.manual_service_rate = None if manual_rate in [None, ""] else float(manual_rate)
    item.note = str(data.get("note", "") or "")
    session.commit()
    session.refresh(item)
    return serialize_service_month(item)

@app.get("/api/service/calculate/{service_month_id}")
@app.get("/service/calculate/{service_month_id}")
def preview_service_calculation(service_month_id: int, manual_service_rate: float | None = None, session: Session = Depends(get_db)):
    service_month = session.query(db.ServiceMonth).filter(db.ServiceMonth.id == service_month_id).first()
    if not service_month:
        raise HTTPException(status_code=404, detail="ไม่พบข้อมูล Service Charge เดือนนี้")

    if manual_service_rate is not None:
        service_month.manual_service_rate = manual_service_rate

    active_emps = session.query(db.Employee).filter(db.Employee.is_active == True).order_by(
        db.Employee.department.asc(),
        db.Employee.emp_code.asc()
    ).all()
    existing_rows = {
        row.emp_code: row
        for row in session.query(db.ServiceEmployee).filter(db.ServiceEmployee.service_month_id == service_month_id).all()
    }
    payroll_inputs = payroll_service_inputs(session, service_month)

    base_rows = []
    total_weight = 0.0
    for emp in active_emps:
        existing = existing_rows.get(emp.emp_code)
        service_weight = calculate_service_weight(emp, service_month)
        total_weight += service_weight
        base_rows.append((emp, existing, service_weight))

    month_data = serialize_service_month(service_month)
    calculated_rate = round_baht(month_data["employee_pool"] / total_weight) if total_weight > 0 else 0
    selected_rate = round_baht(manual_service_rate) if manual_service_rate is not None else calculated_rate

    rows = []
    for emp, existing, service_weight in base_rows:
        payroll_input = payroll_inputs.get(str(emp.emp_code), {})
        sick_days = existing.sick_days if existing else payroll_input.get("sick_days", 0.0)
        leave_days = existing.leave_days if existing else payroll_input.get("leave_days", 0.0)
        leave_hours = existing.leave_hours if existing else payroll_input.get("leave_hours", 0.0)
        late_hours = existing.late_hours if existing else payroll_input.get("late_hours", 0.0)
        evaluation_percent = existing.evaluation_percent if existing else 0.0
        prior_deposit_total = service_deposit_total_before(session, emp.emp_code, service_month_id, service_month)
        deposit_deduction = existing.deposit_deduction if existing else default_service_deposit(emp, service_month, service_weight, prior_deposit_total)
        if service_weight <= 0:
            deposit_deduction = 0
        notes = existing.notes if existing else ""
        gross_service = round_baht(selected_rate * service_weight)
        amounts = calculate_service_amounts({
            "gross_service": gross_service,
            "sick_days": sick_days,
            "leave_hours": leave_hours,
            "late_hours": late_hours,
            "evaluation_percent": evaluation_percent,
            "deposit_deduction": deposit_deduction
        })
        rows.append({
            "emp_code": emp.emp_code,
            "first_name": emp.first_name,
            "last_name": emp.last_name,
            "department": emp.department,
            "position": emp.position,
            "start_date": emp.start_date,
            "service_type": emp.service_type or "AUTO",
            "service_percent": emp.service_percent if emp.service_percent is not None else 100.0,
            "eligible_service_month": eligible_service_month_index(emp, service_month),
            "prior_deposit_total": prior_deposit_total,
            "service_weight": service_weight,
            "service_rate": selected_rate,
            "gross_service": gross_service,
            "sick_days": sick_days or 0.0,
            "sick_deduction": amounts["sick_deduction"],
            "leave_days": leave_days or 0.0,
            "leave_hours": amounts["leave_hours"],
            "leave_hour_deduction": amounts["leave_hour_deduction"],
            "late_hours": amounts["late_hours"],
            "late_deduction": amounts["late_deduction"],
            "evaluation_percent": evaluation_percent or 0.0,
            "evaluation_deduction": amounts["evaluation_deduction"],
            "deposit_deduction": round_baht(deposit_deduction or 0),
            "net_service": amounts["net_service"],
            "source": payroll_input.get("source", ""),
            "notes": notes or ""
        })

    return {
        "service_month": month_data,
        "summary": service_summary(service_month, rows),
        "employees": rows
    }

@app.post("/api/service/calculate/{service_month_id}/save")
@app.post("/service/calculate/{service_month_id}/save")
def save_service_calculation(service_month_id: int, data: dict, session: Session = Depends(get_db)):
    service_month = session.query(db.ServiceMonth).filter(db.ServiceMonth.id == service_month_id).first()
    if not service_month:
        raise HTTPException(status_code=404, detail="ไม่พบข้อมูล Service Charge เดือนนี้")

    manual_rate = data.get("manual_service_rate", None)
    service_month.manual_service_rate = None if manual_rate in [None, ""] else float(manual_rate)

    rows = []
    for row in data.get("employees", []):
        normalized = dict(row)
        service_weight = float(normalized.get("service_weight", 0.0) or 0.0)
        service_rate = round_baht(normalized.get("service_rate", 0.0))
        gross_service = round_baht(service_rate * service_weight)
        sick_days = float(normalized.get("sick_days", 0.0) or 0.0)
        leave_days = float(normalized.get("leave_days", 0.0) or 0.0)
        leave_hours = float(normalized.get("leave_hours", 0.0) or 0.0)
        late_hours = float(normalized.get("late_hours", 0.0) or 0.0)
        evaluation_percent = float(normalized.get("evaluation_percent", 0.0) or 0.0)
        deposit_deduction = round_baht(normalized.get("deposit_deduction", 0.0))
        prior_deposit_total = service_deposit_total_before(session, normalized.get("emp_code", ""), service_month_id, service_month)

        if service_weight <= 0 or prior_deposit_total >= 1500:
            deposit_deduction = 0
        elif prior_deposit_total + deposit_deduction > 1500:
            raise HTTPException(
                status_code=400,
                detail=f"Deposit deduction for {normalized.get('emp_code', '')} exceeds 1,500 Baht total"
            )

        amounts = calculate_service_amounts({
            "gross_service": gross_service,
            "sick_days": sick_days,
            "leave_hours": leave_hours,
            "late_hours": late_hours,
            "evaluation_percent": evaluation_percent,
            "deposit_deduction": deposit_deduction
        })

        normalized.update({
            "service_weight": service_weight,
            "service_rate": service_rate,
            "gross_service": gross_service,
            "sick_days": sick_days,
            "sick_deduction": amounts["sick_deduction"],
            "leave_days": leave_days,
            "leave_hours": amounts["leave_hours"],
            "leave_hour_deduction": amounts["leave_hour_deduction"],
            "late_hours": amounts["late_hours"],
            "late_deduction": amounts["late_deduction"],
            "evaluation_percent": evaluation_percent,
            "evaluation_deduction": amounts["evaluation_deduction"],
            "deposit_deduction": deposit_deduction,
            "net_service": amounts["net_service"]
        })
        rows.append(normalized)

    summary = service_summary(service_month, rows)
    if summary["exceeds_employee_pool"]:
        raise HTTPException(status_code=400, detail="Actual Employee Paid exceeds Employee Pool")

    session.query(db.ServiceEmployee).filter(db.ServiceEmployee.service_month_id == service_month_id).delete()
    for row in rows:
        deposit_deduction = round_baht(row.get("deposit_deduction", 0.0))
        service_weight = float(row.get("service_weight", 0.0) or 0.0)
        if service_weight <= 0:
            deposit_deduction = 0

        service_employee = db.ServiceEmployee(
            service_month_id=service_month_id,
            emp_code=str(row.get("emp_code", "")),
            first_name=str(row.get("first_name", "")),
            last_name=str(row.get("last_name", "")),
            department=str(row.get("department", "")),
            position=str(row.get("position", "")),
            service_type=str(row.get("service_type", "AUTO")),
            service_percent=float(row.get("service_percent", 100.0) or 0.0),
            service_weight=float(row.get("service_weight", 0.0) or 0.0),
            service_rate=round_baht(row.get("service_rate", 0.0)),
            gross_service=round_baht(row.get("gross_service", 0.0)),
            sick_days=float(row.get("sick_days", 0.0) or 0.0),
            sick_deduction=round_baht(row.get("sick_deduction", 0.0)),
            leave_days=float(row.get("leave_days", 0.0) or 0.0),
            leave_hours=float(row.get("leave_hours", 0.0) or 0.0),
            leave_hour_deduction=round_baht(row.get("leave_hour_deduction", 0.0)),
            late_hours=float(row.get("late_hours", 0.0) or 0.0),
            late_deduction=round_baht(row.get("late_deduction", 0.0)),
            evaluation_percent=float(row.get("evaluation_percent", 0.0) or 0.0),
            evaluation_deduction=round_baht(row.get("evaluation_deduction", 0.0)),
            deposit_deduction=deposit_deduction,
            net_service=round_baht(row.get("net_service", 0.0)),
            notes=str(row.get("notes", "") or "")
        )
        session.add(service_employee)

    session.commit()
    return {"message": "บันทึก Service Calculation สำเร็จ", "summary": summary}

@app.get("/api/service/employees/{service_month_id}")
@app.get("/service/employees/{service_month_id}")
def get_service_employees(service_month_id: int, session: Session = Depends(get_db)):
    rows = session.query(db.ServiceEmployee).filter(
        db.ServiceEmployee.service_month_id == service_month_id
    ).order_by(db.ServiceEmployee.department.asc(), db.ServiceEmployee.emp_code.asc()).all()
    return [serialize_service_employee(row) for row in rows]

@app.get("/api/service/reports/{service_month_id}")
@app.get("/service/reports/{service_month_id}")
def get_service_reports(service_month_id: int, session: Session = Depends(get_db)):
    service_month = session.query(db.ServiceMonth).filter(db.ServiceMonth.id == service_month_id).first()
    if not service_month:
        raise HTTPException(status_code=404, detail="ไม่พบข้อมูล Service Charge เดือนนี้")

    rows = [serialize_service_employee(row) for row in session.query(db.ServiceEmployee).filter(db.ServiceEmployee.service_month_id == service_month_id).all()]
    distribution = {}
    for row in rows:
        amount = round_baht(row.get("net_service", 0))
        distribution[amount] = distribution.get(amount, 0) + 1

    distribution_summary = [
        {"Net Service Amount": amount, "Employee Count": count}
        for amount, count in sorted(distribution.items(), key=lambda item: item[0], reverse=True)
    ]

    remaining = sum(round_baht(row.get("net_service", 0)) for row in rows)
    cash_rows = []
    for denom in [1000, 500, 100, 50, 20]:
        qty = remaining // denom
        amount = qty * denom
        cash_rows.append({"Denomination": denom, "Quantity": qty, "Amount": amount})
        remaining -= amount
    cash_rows.append({"Denomination": "coins/remainder", "Quantity": remaining, "Amount": remaining})

    summary = service_summary(service_month, rows)
    return {
        "summary": summary,
        "distribution_summary": distribution_summary,
        "total_employees": len(rows),
        "cash_preparation": cash_rows,
        "cash_grand_total": sum(row["Amount"] for row in cash_rows)
    }

# ==========================================
# 💰 ระบบประมวลผลเงินเดือน (Payroll)
# ==========================================

@app.get("/payroll/cycles")
def get_payroll_cycles(session: Session = Depends(get_db)):
    cycles = session.query(db.PayrollTransaction.cycle_name).distinct().all()
    return [c[0] for c in cycles]

@app.get("/payroll/{cycle_name}")
def get_payroll_by_cycle(cycle_name: str, session: Session = Depends(get_db)):
    transactions = session.query(db.PayrollTransaction).filter(db.PayrollTransaction.cycle_name == cycle_name).all()
    if not transactions:
        raise HTTPException(status_code=404, detail="ไม่พบข้อมูลรอบการจ่ายนี้")
    
    res_list = []
    payment_date = ""
    for t in transactions:
        payment_date = t.payment_date
        res_list.append({
            "emp_code": t.emp_code, "first_name": t.first_name, "last_name": t.last_name,
            "department": t.department, "position": t.position, "account_no": t.account_no,
            "base_salary": t.base_salary, "ot_15_hours": t.ot_15_hours, "ot_15_amount": t.ot_15_amount,
            "ot_1_hours": t.ot_1_hours, "ot_1_amount": t.ot_1_amount, "ot_amount": t.ot_amount,
            "other_benefits": t.other_benefits, "backpay": t.backpay, "gross_salary": t.gross_salary,
            "late_mins": t.late_mins, "sick_days": t.sick_days, "unpaid_leave_days": t.unpaid_leave_days, "leave_hours": t.leave_hours,
            "leave_deduction": t.leave_deduction, "company_loan": t.company_loan, "student_loan": t.student_loan,
            "sso_deduction": t.sso_deduction, "net_salary": t.net_salary
        })
        
    return {"cycle_name": cycle_name, "payment_date": payment_date, "transactions": res_list}

@app.delete("/payroll/{cycle_name}")
def delete_payroll_cycle(cycle_name: str, session: Session = Depends(get_db)):
    session.query(db.PayrollTransaction).filter(db.PayrollTransaction.cycle_name == cycle_name).delete()
    session.commit()
    return {"message": "ลบข้อมูลรอบนี้เรียบร้อยแล้ว"}

@app.post("/payroll/calculate")
def calculate_payroll(data: dict, session: Session = Depends(get_db)):
    cycle_name = data.get("cycle_name")
    payment_date = data.get("payment_date")
    time_data = data.get("time_data", [])
    
    session.query(db.PayrollTransaction).filter(db.PayrollTransaction.cycle_name == cycle_name).delete()
    active_emps = session.query(db.Employee).filter(db.Employee.is_active == True).all()
    
    time_dict = {}
    for td in time_data:
        time_dict[str(td["emp_code"])] = td
        
    transactions_to_add = []
    
    for emp in active_emps:
        emp_code = str(emp.emp_code)
        td = time_dict.get(emp_code, {})
        
        daily_wage = emp.base_salary / 30 if emp.base_salary > 0 else 0
        hourly_wage = daily_wage / 8 if daily_wage > 0 else 0
        
        ot_15_hrs = float(td.get("ot_15_hours", 0))
        ot_1_hrs = float(td.get("ot_1_hours", 0))
        ot_15_amt = ot_15_hrs * hourly_wage * 1.5
        ot_1_amt = ot_1_hrs * hourly_wage * 1.0
        total_ot = ot_15_amt + ot_1_amt
        
        other_ben = float(td.get("other_benefits", 0))
        backpay = float(td.get("backpay", 0))
        gross_salary = emp.base_salary + total_ot + other_ben + backpay
        
        late_mins = float(td.get("late_mins", 0))
        sick_days = float(td.get("sick_days", 0))
        absent_days = float(td.get("absent_days", 0))
        leave_hrs = float(td.get("leave_hours", 0))
        
        deduct_late = (late_mins / 60) * hourly_wage
        deduct_absent = absent_days * daily_wage
        deduct_leave = leave_hrs * hourly_wage
        total_leave_deduct = deduct_late + deduct_absent + deduct_leave
        
        comp_loan = float(td.get("company_loan", 0))
        student_loan = float(td.get("student_loan", 0))
        
        # 🟢 คำนวณประกันสังคม (อัปเดตเพดานใหม่ + ปัดเศษสตางค์)
        sso_deduction = 0.0
        if emp.is_sso:
            # 1. ถ้าระบุยอด sso_manual มาใน Excel แบบเจาะจง ให้ยึดตาม Excel
            if "sso_manual" in td and float(td.get("sso_manual", 0)) > 0:
                sso_deduction = float(td["sso_manual"])
            else:
                # 2. ถ้าไม่ระบุ ให้คำนวณ 5% จากฐานเงินเดือน (เพดานใหม่ 17,500 บาท)
                max_sso_base = 17500.0 # 👈 สามารถแก้ตัวเลขเพดานตรงนี้ได้ในอนาคต
                cal_base = emp.base_salary if emp.base_salary <= max_sso_base else max_sso_base
                
                # 🟢 คำนวณ 5% และปัดเศษสตางค์ (ตั้งแต่ 0.50 ปัดขึ้น, ต่ำกว่าปัดทิ้ง)
                raw_sso = cal_base * 0.05
                sso_deduction = float(int(raw_sso + 0.5))
        
        net_salary = gross_salary - (total_leave_deduct + comp_loan + student_loan + sso_deduction)
        if net_salary < 0: net_salary = 0.0
            
        new_tx = db.PayrollTransaction(
            cycle_name=cycle_name, payment_date=payment_date, emp_code=emp_code,
            first_name=emp.first_name, last_name=emp.last_name, department=emp.department,
            position=emp.position, account_no=emp.account_no, base_salary=emp.base_salary,
            ot_15_hours=ot_15_hrs, ot_15_amount=ot_15_amt, ot_1_hours=ot_1_hrs,
            ot_1_amount=ot_1_amt, ot_amount=total_ot, other_benefits=other_ben,
            backpay=backpay, gross_salary=gross_salary, late_mins=late_mins,
            sick_days=sick_days, unpaid_leave_days=absent_days, leave_hours=leave_hrs, leave_deduction=total_leave_deduct,
            company_loan=comp_loan, student_loan=student_loan, sso_deduction=sso_deduction,
            net_salary=net_salary
        )
        transactions_to_add.append(new_tx)
        
    session.bulk_save_objects(transactions_to_add)
    session.commit()
    return {"message": f"คำนวณเงินเดือนรอบ {cycle_name} สำเร็จ! ({len(transactions_to_add)} คน)"}

@app.get("/dashboard/trend")
def get_dashboard_trend(session: Session = Depends(get_db)):
    results = session.query(
        db.PayrollTransaction.cycle_name,
        func.sum(db.PayrollTransaction.net_salary).label("total_net_salary")
    ).group_by(db.PayrollTransaction.cycle_name).all()
    
    trend_data = [{"รอบเงินเดือน": r.cycle_name, "รายจ่ายสุทธิ": r.total_net_salary} for r in results]
    return trend_data
