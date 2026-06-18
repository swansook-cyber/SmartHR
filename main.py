from fastapi import FastAPI, Depends, HTTPException, Body
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import func, inspect, text
import database as db
from typing import List
import datetime
from decimal import Decimal, ROUND_HALF_UP
import json
import math
from pathlib import Path
import sqlite3
import shutil
import re

def safe_json_value(value, path="response"):
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            print(f"[safe-json] Non-finite float at {path}: {value}; response value converted to 0")
            return 0
        return value
    if isinstance(value, Decimal):
        if value.is_nan() or value.is_infinite():
            print(f"[safe-json] Non-finite Decimal at {path}: {value}; response value converted to 0")
            return 0
        return float(value)
    if isinstance(value, dict):
        return {
            str(key): safe_json_value(item, f"{path}.{key}")
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple, set)):
        return [
            safe_json_value(item, f"{path}[{index}]")
            for index, item in enumerate(value)
        ]
    if hasattr(value, "item") and value.__class__.__module__.split(".", 1)[0] in {"numpy", "pandas"}:
        try:
            return safe_json_value(value.item(), path)
        except Exception:
            print(f"[safe-json] Unsupported scalar at {path}: {type(value).__name__}; response value converted to None")
            return None
    return value

SERVICE_SAVE_OPTIONAL_NUMERIC_FIELDS = {
    "sick_days",
    "leave_days",
    "leave_hours",
    "late_hours",
    "evaluation_percent",
    "deposit_deduction",
}

def is_non_finite_number(value):
    if isinstance(value, float):
        return math.isnan(value) or math.isinf(value)
    if isinstance(value, Decimal):
        return value.is_nan() or value.is_infinite()
    if hasattr(value, "item") and value.__class__.__module__.split(".", 1)[0] in {"numpy", "pandas"}:
        try:
            return is_non_finite_number(value.item())
        except Exception:
            return False
    return False

def sanitize_service_save_number(value, path):
    if is_non_finite_number(value):
        print(f"unsafe {path} = {value}; converted to 0 before service save")
        return 0
    return value

def sanitize_service_save_request(data):
    sanitized = dict(data or {})
    sanitized["manual_service_rate"] = sanitize_service_save_number(
        sanitized.get("manual_service_rate"),
        "manual_service_rate",
    )
    sanitized_rows = []
    for index, row in enumerate(sanitized.get("employees", []) or []):
        normalized = dict(row or {})
        for field in SERVICE_SAVE_OPTIONAL_NUMERIC_FIELDS:
            if field in normalized:
                normalized[field] = sanitize_service_save_number(
                    normalized.get(field),
                    f"service_rows[{index}].{field}",
                )
        sanitized_rows.append(normalized)
    sanitized["employees"] = sanitized_rows
    return sanitized

class SafeJSONResponse(JSONResponse):
    def render(self, content) -> bytes:
        return super().render(safe_json_value(content))

app = FastAPI(default_response_class=SafeJSONResponse)

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
            add_column_if_missing(conn, "service_employees", service_employee_columns, "leave_day_deduction", "FLOAT DEFAULT 0.0")
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

def audit_log(session, username="-", action="", module="", reference_id="", details=""):
    try:
        log = db.AuditLog(
            timestamp=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            username=str(username or "-")[:200],
            action=str(action or "")[:200],
            module=str(module or "")[:100],
            reference_id=str(reference_id or "")[:200],
            details=str(details or "")[:1000]
        )
        session.add(log)
    except:
        pass

def audit_log_commit(session, username="-", action="", module="", reference_id="", details=""):
    try:
        audit_log(session, username, action, module, reference_id, details)
        session.commit()
    except:
        try:
            session.rollback()
        except:
            pass

def write_audit_log(username="-", action="", module="", reference_id="", details=""):
    audit_session = db.SessionLocal()
    try:
        audit_log(audit_session, username, action, module, reference_id, details)
        audit_session.commit()
    except:
        try:
            audit_session.rollback()
        except:
            pass
    finally:
        try:
            audit_session.close()
        except:
            pass

def audit_details(data, keys=None):
    try:
        if keys:
            payload = {key: data.get(key) for key in keys if key in data}
        else:
            payload = data
        return json.dumps(payload, ensure_ascii=False, default=str)
    except:
        return str(data)

BACKUP_DIR = Path("HRMS_Backup")
DATABASE_FILE = Path("payroll.db")

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

def company_settings_payload(settings=None):
    payload = dict(DEFAULT_COMPANY_SETTINGS)
    if settings:
        payload.update({
            "id": settings.id,
            "logo_path": settings.logo_path,
            "company_thai_name": settings.company_thai_name,
            "company_english_name": settings.company_english_name,
            "address": settings.address,
            "tax_id": settings.tax_id,
            "phone": settings.phone,
            "authorized_signer_name": settings.authorized_signer_name,
            "authorized_signer_position_thai": settings.authorized_signer_position_thai,
            "authorized_signer_position_english": settings.authorized_signer_position_english,
        })
    for key, value in DEFAULT_COMPANY_SETTINGS.items():
        if payload.get(key) in [None, ""]:
            payload[key] = value
    return payload

def get_or_create_company_settings(session):
    settings = session.query(db.CompanySettings).order_by(db.CompanySettings.id.asc()).first()
    if not settings:
        settings = db.CompanySettings(**DEFAULT_COMPANY_SETTINGS)
        session.add(settings)
        session.commit()
        session.refresh(settings)
    return settings

def backup_file_info(path):
    try:
        stat = path.stat()
        return {
            "file_name": path.name,
            "path": str(path),
            "size_bytes": stat.st_size,
            "modified_at": datetime.datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        }
    except:
        return {}

def list_backup_files():
    try:
        BACKUP_DIR.mkdir(exist_ok=True)
        files = sorted(BACKUP_DIR.glob("*.db"), key=lambda item: item.stat().st_mtime, reverse=True)
        return [backup_file_info(path) for path in files]
    except:
        return []

def create_database_backup(backup_type="manual"):
    BACKUP_DIR.mkdir(exist_ok=True)
    if not DATABASE_FILE.exists():
        raise FileNotFoundError("Cannot find payroll.db")

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_type = "".join(ch for ch in str(backup_type or "manual") if ch.isalnum() or ch in ["_", "-"]) or "manual"
    backup_path = BACKUP_DIR / f"payroll_backup_{safe_type}_{timestamp}.db"

    try:
        source = sqlite3.connect(str(DATABASE_FILE))
        destination = sqlite3.connect(str(backup_path))
        with destination:
            source.backup(destination)
        source.close()
        destination.close()
    except:
        try:
            source.close()
        except:
            pass
        try:
            destination.close()
        except:
            pass
        shutil.copy2(DATABASE_FILE, backup_path)

    return backup_file_info(backup_path)

def ensure_day_30_backup():
    try:
        today = datetime.date.today()
        if today.day != 30:
            return None
        BACKUP_DIR.mkdir(exist_ok=True)
        marker = BACKUP_DIR / f"auto_backup_{today.strftime('%Y_%m')}.done"
        if marker.exists():
            return None
        backup_info = create_database_backup("auto_day_30")
        marker.write_text(backup_info.get("file_name", ""), encoding="utf-8")
        return backup_info
    except:
        return None

ensure_day_30_backup()

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

@app.post("/audit-logs/")
def create_audit_log(data: dict, session: Session = Depends(get_db)):
    audit_log_commit(
        session,
        username=data.get("username", "-"),
        action=data.get("action", ""),
        module=data.get("module", ""),
        reference_id=data.get("reference_id", ""),
        details=data.get("details", "")
    )
    return {"message": "audit logged"}

@app.get("/audit-logs/")
def get_audit_logs(
    start_date: str | None = None,
    end_date: str | None = None,
    username: str | None = None,
    module: str | None = None,
    limit: int = 1000,
    session: Session = Depends(get_db)
):
    query = session.query(db.AuditLog)
    if start_date:
        query = query.filter(db.AuditLog.timestamp >= f"{start_date} 00:00:00")
    if end_date:
        query = query.filter(db.AuditLog.timestamp <= f"{end_date} 23:59:59")
    if username:
        query = query.filter(db.AuditLog.username.like(f"%{username}%"))
    if module and module != "All":
        query = query.filter(db.AuditLog.module == module)
    logs = query.order_by(db.AuditLog.id.desc()).limit(limit).all()
    return [
        {
            "timestamp": log.timestamp,
            "username": log.username,
            "module": log.module,
            "action": log.action,
            "reference_id": log.reference_id,
            "details": log.details
        }
        for log in logs
    ]

@app.get("/backups/")
def get_backups():
    return {
        "database_exists": DATABASE_FILE.exists(),
        "database_path": str(DATABASE_FILE),
        "backup_dir": str(BACKUP_DIR),
        "manual_script_exists": Path("Backup_HRMS.bat").exists(),
        "auto_backup_day": 30,
        "backups": list_backup_files()
    }

@app.post("/backups/create")
def create_backup(data: dict = Body(default={}), session: Session = Depends(get_db)):
    try:
        backup_info = create_database_backup("manual")
        write_audit_log(
            data.get("audit_username", "-"),
            "Create Backup",
            "System",
            backup_info.get("file_name", ""),
            backup_info.get("path", "")
        )
        return {"message": "Backup created successfully", "backup": backup_info}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/company-settings/")
def get_company_settings(session: Session = Depends(get_db)):
    return company_settings_payload(get_or_create_company_settings(session))

@app.post("/company-settings/")
def update_company_settings(data: dict, session: Session = Depends(get_db)):
    settings = get_or_create_company_settings(session)
    for field in DEFAULT_COMPANY_SETTINGS.keys():
        if field in data:
            setattr(settings, field, str(data.get(field, "") or ""))
    session.commit()
    session.refresh(settings)
    write_audit_log(
        data.get("audit_username", "-"),
        "Update Company Settings",
        "System",
        "company_settings",
        audit_details(data, list(DEFAULT_COMPANY_SETTINGS.keys()))
    )
    return company_settings_payload(settings)

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
    write_audit_log(
        data.get("audit_username", "-"),
        "Create Employee",
        "Employee",
        data.get("emp_code", ""),
        audit_details(data, ["emp_code", "first_name", "last_name", "department", "position", "service_type", "service_percent"])
    )
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
    if "start_date" in data: emp.start_date = data["start_date"]
    if "is_active" in data: emp.is_active = data["is_active"]
    if "is_sso" in data: emp.is_sso = data["is_sso"]
    if "machine_id" in data: emp.machine_id = data["machine_id"]
    if "service_type" in data: emp.service_type = data["service_type"]
    if "service_percent" in data: emp.service_percent = float(data["service_percent"])
    
    session.commit()
    write_audit_log(
        data.get("audit_username", "-"),
        "Update Employee",
        "Employee",
        emp_code,
        audit_details(data, ["first_name", "last_name", "department", "position", "phone", "start_date", "is_active", "is_sso", "service_type", "service_percent"])
    )
    return {"message": "อัปเดตข้อมูลพนักงานสำเร็จ"}

@app.delete("/employees/{emp_code}")
def delete_employee(emp_code: str, username: str | None = None, session: Session = Depends(get_db)):
    emp = session.query(db.Employee).filter(db.Employee.emp_code == emp_code).first()
    if not emp:
        raise HTTPException(status_code=404, detail="ไม่พบพนักงาน")
    details = audit_details({
        "emp_code": emp.emp_code,
        "first_name": emp.first_name,
        "last_name": emp.last_name,
        "department": emp.department
    })
    session.delete(emp)
    session.commit()
    write_audit_log(username or "-", "Delete Employee", "Employee", emp_code, details)
    return {"message": "ลบข้อมูลพนักงานสำเร็จ"}

# 🟢 ฟีเจอร์ Upsert (เพิ่มคนใหม่ + อัปเดตคนเดิม) รับข้อมูล List ได้โดยตรง
@app.post("/employees/bulk")
def bulk_import_employees(employees: list = Body(...), session: Session = Depends(get_db)):
    try:
        added_count = 0
        updated_count = 0
        audit_username = "-"
        
        for emp_data in employees:
            audit_username = emp_data.get("audit_username", audit_username)
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
        write_audit_log(
            audit_username,
            "Upload Employee",
            "Employee",
            "bulk",
            f"added={added_count}, updated={updated_count}"
        )
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
    if service_type == "FIXED_50":
        return 0.5
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

def payroll_cycle_month_year(cycle_name):
    month_options = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
    pattern = r"\b(" + "|".join(month_options) + r")\b\D+(\d{4})\b"
    match = re.search(pattern, str(cycle_name or ""), flags=re.IGNORECASE)
    if not match:
        return None
    month_name = next(month for month in month_options if month.lower() == match.group(1).lower())
    return (int(match.group(2)), month_options.index(month_name) + 1)

def latest_payroll_cycle_for_service_month(session, service_month):
    service_key = service_month_key(service_month)
    cycle_rows = session.query(
        db.PayrollTransaction.cycle_name,
        func.max(db.PayrollTransaction.id).label("latest_id"),
        func.max(db.PayrollTransaction.payment_date).label("latest_payment_date")
    ).group_by(db.PayrollTransaction.cycle_name).all()
    matching_cycles = [
        row for row in cycle_rows
        if payroll_cycle_month_year(row.cycle_name) == service_key
    ]
    if not matching_cycles:
        return None
    return sorted(
        matching_cycles,
        key=lambda row: (int(row.latest_id or 0), str(row.latest_payment_date or "")),
        reverse=True
    )[0]

def payroll_service_inputs(session, service_month):
    cycle = latest_payroll_cycle_for_service_month(session, service_month)
    if not cycle:
        return {}

    rows = session.query(db.PayrollTransaction).filter(
        db.PayrollTransaction.cycle_name == cycle.cycle_name
    ).order_by(db.PayrollTransaction.id.desc()).all()

    imported = {}
    payroll_year, payroll_month = payroll_cycle_month_year(cycle.cycle_name)
    for row in rows:
        emp_code = str(row.emp_code)
        if emp_code in imported:
            continue
        imported[emp_code] = {
            "sick_days": float(row.sick_days or 0),
            "leave_days": float(row.unpaid_leave_days or 0),
            "leave_hours": float(row.leave_hours or 0),
            "late_mins": float(row.late_mins or 0),
            "late_hours": float(row.late_mins or 0) / 60,
            "source": "Imported from Payroll",
            "payroll_cycle_id": int(cycle.latest_id or 0),
            "payroll_cycle_name": cycle.cycle_name,
            "payroll_month": payroll_month,
            "payroll_year": payroll_year,
            "imported_from_payroll": True
        }

    return imported

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
    if str(getattr(emp, "service_type", "AUTO") or "AUTO").upper() != "AUTO":
        return 0
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
    leave_days = float(row.get("leave_days", 0) or 0)
    leave_hours = float(row.get("leave_hours", 0) or 0)
    late_hours = float(row.get("late_hours", 0) or 0)
    evaluation_percent = float(row.get("evaluation_percent", 0) or 0)
    deposit_deduction = round_baht(row.get("deposit_deduction", 0))

    sick_deduction = round_baht(gross_service / 30 * sick_days)
    leave_day_deduction = round_baht(gross_service / 30 * leave_days)
    leave_hour_deduction = round_baht(gross_service / 30 / 8 * leave_hours)
    late_deduction = calculate_late_deduction(gross_service, late_hours)
    evaluation_deduction = round_baht(gross_service * evaluation_percent / 100)
    net_service = max(
        0,
        round_baht(
            gross_service
            - sick_deduction
            - leave_day_deduction
            - leave_hour_deduction
            - late_deduction
            - evaluation_deduction
            - deposit_deduction
        )
    )

    return {
        "sick_deduction": sick_deduction,
        "leave_days": leave_days,
        "leave_day_deduction": leave_day_deduction,
        "leave_hours": leave_hours,
        "leave_hour_deduction": leave_hour_deduction,
        "late_hours": late_hours,
        "late_deduction": late_deduction,
        "evaluation_deduction": evaluation_deduction,
        "net_service": net_service
    }

def service_row_total_after_deduction(row):
    if "total_after_deduction" in row:
        return round_baht(row.get("total_after_deduction", 0))
    return round_baht(row.get("net_service", 0)) + round_baht(row.get("deposit_deduction", 0))

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
        "leave_day_deduction": row.leave_day_deduction or 0.0,
        "leave_hours": row.leave_hours or 0.0,
        "leave_hour_deduction": row.leave_hour_deduction or 0.0,
        "late_hours": row.late_hours or 0.0,
        "late_deduction": row.late_deduction or 0.0,
        "evaluation_percent": row.evaluation_percent or 0.0,
        "evaluation_deduction": row.evaluation_deduction or 0.0,
        "deposit_deduction": row.deposit_deduction or 0.0,
        "net_service": row.net_service or 0.0,
        "notes": sanitize_service_manual_notes(row.notes)
    }

def serialize_service_slip(row, service_month, employee=None, payroll_input=None):
    payroll_input = payroll_input or {}
    late_mins = payroll_input.get("late_mins")
    return {
        "service_month_id": service_month.id,
        "service_month": f"{service_month.month}-{service_month.year}",
        "month": service_month.month,
        "year": service_month.year,
        "emp_code": row.emp_code,
        "first_name": row.first_name or "",
        "last_name": row.last_name or "",
        "department": row.department or "",
        "service_eligibility_percent": round_baht(float(row.service_weight or 0) * 100),
        "eligible_service_month": eligible_service_month_index(employee, service_month) if employee else "",
        "service_weight": row.service_weight or 0.0,
        "service_rate": row.service_rate or 0.0,
        "gross_service": row.gross_service or 0.0,
        "sick_days": row.sick_days or 0.0,
        "sick_deduction": row.sick_deduction or 0.0,
        "leave_days": row.leave_days or 0.0,
        "leave_day_deduction": row.leave_day_deduction or 0.0,
        "leave_hours": row.leave_hours or 0.0,
        "leave_hour_deduction": row.leave_hour_deduction or 0.0,
        "late_mins": late_mins,
        "late_hours": row.late_hours or 0.0,
        "late_deduction": row.late_deduction or 0.0,
        "evaluation_percent": row.evaluation_percent or 0.0,
        "evaluation_deduction": row.evaluation_deduction or 0.0,
        "total_after_deduction": round_baht(row.gross_service or 0.0)
            - round_baht(row.sick_deduction or 0.0)
            - round_baht(row.leave_day_deduction or 0.0)
            - round_baht(row.leave_hour_deduction or 0.0)
            - round_baht(row.late_deduction or 0.0)
            - round_baht(row.evaluation_deduction or 0.0),
        "deposit_deduction": row.deposit_deduction or 0.0,
        "deposit_refund": 0,
        "net_service": row.net_service or 0.0,
        "deduction_remarks": service_attendance_remarks({
            "sick_days": row.sick_days or 0.0,
            "leave_days": row.leave_days or 0.0,
            "leave_hours": row.leave_hours or 0.0,
            "late_mins": late_mins,
            "late_hours": row.late_hours or 0.0,
            "evaluation_percent": row.evaluation_percent or 0.0,
            "deposit_deduction": row.deposit_deduction or 0.0
        }),
        "notes": sanitize_service_manual_notes(row.notes)
    }

def service_summary(service_month, rows):
    employee_pool = serialize_service_month(service_month)["employee_pool"]
    total_weight = sum(float(row.get("service_weight", 0) or 0) for row in rows)
    calculated_rate = float(employee_pool / total_weight) if total_weight > 0 else 0
    manual_rate = service_month.manual_service_rate
    service_rate = float(manual_rate) if manual_rate not in [None, ""] else calculated_rate
    actual_paid = sum(service_row_total_after_deduction(row) for row in rows)
    return {
        "employee_pool": round_baht(employee_pool),
        "total_weight": total_weight,
        "calculated_service_rate": calculated_rate,
        "manual_service_rate": float(manual_rate) if manual_rate not in [None, ""] else None,
        "service_rate": service_rate,
        "actual_employee_paid": actual_paid,
        "balance_returned_to_resort": round_baht(employee_pool - actual_paid),
        "exceeds_employee_pool": actual_paid > round_baht(employee_pool)
    }

def service_summary_totals(summary):
    return {
        "employee_pool": round_baht(summary.get("employee_pool", 0)),
        "actual_employee_paid": round_baht(summary.get("actual_employee_paid", 0)),
        "balance_returned_to_resort": round_baht(summary.get("balance_returned_to_resort", 0)),
    }

def validate_service_summary_consistency(preview_summary, saved_summary):
    preview_totals = service_summary_totals(preview_summary)
    saved_totals = service_summary_totals(saved_summary)
    if preview_totals != saved_totals:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Service calculation consistency error: preview totals do not match saved totals",
                "preview_totals": preview_totals,
                "saved_totals": saved_totals,
            }
        )

def format_service_remark_number(value):
    value = float(value or 0)
    if value.is_integer():
        return f"{int(value):,}"
    return f"{value:,.2f}".rstrip("0").rstrip(".")

def sanitize_service_manual_notes(notes):
    text_value = str(notes or "").strip()
    if not text_value:
        return ""

    auto_remark_pattern = re.compile(
        r"""
        (?:^|,\s*)
        (?:
            Sick\s*:\s*[\d,.]+(?:\s*(?:day|days))?
            |Leave\s+Hour\s*:\s*[\d,.]+
            |Leave\s*:\s*[\d,.]+(?:\s*(?:day|days|hour|hours|hr|hrs))?
            |Late\s*:\s*[\d,.]+(?:\s*(?:min|mins|minute|minutes|hour|hours|hr|hrs))?
            |Evaluation\s*:\s*[\d,.]+%?
            |Deposit\s*:\s*[\d,.]+
        )
        (?=,|$)
        """,
        re.IGNORECASE | re.VERBOSE,
    )
    cleaned = auto_remark_pattern.sub("", text_value)
    cleaned = re.sub(r"\s*,\s*", ", ", cleaned)
    return cleaned.strip(" ,")

def service_attendance_remarks(row):
    remarks = []
    sick_days = float(row.get("sick_days", 0) or 0)
    leave_days = float(row.get("leave_days", 0) or 0)
    leave_hours = float(row.get("leave_hours", 0) or 0)
    late_mins = row.get("late_mins")
    late_hours = float(row.get("late_hours", 0) or 0)
    evaluation_percent = float(row.get("evaluation_percent", 0) or 0)

    if sick_days > 0:
        unit = "day" if sick_days == 1 else "days"
        remarks.append(f"Sick: {format_service_remark_number(sick_days)} {unit}")
    if leave_days > 0:
        unit = "day" if leave_days == 1 else "days"
        remarks.append(f"Leave: {format_service_remark_number(leave_days)} {unit}")
    if leave_hours > 0:
        remarks.append(f"Leave: {format_service_remark_number(leave_hours)} {'hr' if leave_hours == 1 else 'hrs'}")
    if late_mins not in [None, ""] and float(late_mins or 0) > 0:
        remarks.append(f"Late: {format_service_remark_number(float(late_mins or 0))} mins")
    elif late_hours > 0:
        unit = "hr" if late_hours == 1 else "hrs"
        remarks.append(f"Late: {format_service_remark_number(late_hours)} {unit}")
    if evaluation_percent > 0:
        remarks.append(f"Evaluation: {format_service_remark_number(evaluation_percent)}%")
    return ", ".join(remarks)

def serialize_service_detail_report(row, employee=None, payroll_input=None):
    data = serialize_service_employee(row)
    payroll_input = payroll_input or {}
    if payroll_input.get("late_mins") not in [None, ""]:
        data["late_mins"] = payroll_input.get("late_mins")
    display_first_name = getattr(employee, "first_name", None) if employee else None
    display_last_name = getattr(employee, "last_name", None) if employee else None
    display_department = getattr(employee, "department", None) if employee else None
    display_position = getattr(employee, "position", None) if employee else None
    display_start_date = getattr(employee, "start_date", None) if employee else None
    deduction_amount = round_baht(data.get("sick_deduction", 0)) + round_baht(data.get("leave_day_deduction", 0)) + round_baht(data.get("leave_hour_deduction", 0)) + round_baht(data.get("late_deduction", 0)) + round_baht(data.get("evaluation_deduction", 0))
    total_after_deduction = round_baht(data.get("gross_service", 0)) - deduction_amount
    notes = sanitize_service_manual_notes(data.get("notes", ""))
    deduction_remarks = service_attendance_remarks(data)
    remarks = ", ".join(part for part in [deduction_remarks, notes] if part)
    return {
        "emp_code": data.get("emp_code", ""),
        "first_name": display_first_name if display_first_name is not None else data.get("first_name", ""),
        "last_name": display_last_name if display_last_name is not None else data.get("last_name", ""),
        "department": (display_department if display_department is not None else data.get("department", "")) or "ไม่ระบุแผนก",
        "position": display_position if display_position is not None else data.get("position", "") or "",
        "start_date": display_start_date if display_start_date is not None else "",
        "service_percent": round_baht(float(data.get("service_weight", 0) or 0) * 100),
        "income_amount": round_baht(data.get("gross_service", 0)),
        "deduction_amount": deduction_amount,
        "total_after_deduction": total_after_deduction,
        "deposit_refund": 0,
        "deposit_deduction": round_baht(data.get("deposit_deduction", 0)),
        "net_service": round_baht(data.get("net_service", 0)),
        "remarks": remarks
    }

def serialize_service_summary_report(service_month, service_rows):
    month_data = serialize_service_month(service_month)
    actual_paid = sum(round_baht(row.net_service or 0) + round_baht(row.deposit_deduction or 0) for row in service_rows)
    deposit_total = sum(round_baht(row.deposit_deduction or 0) for row in service_rows)
    employee_pool = round_baht(month_data["employee_pool"])
    balance_returned = round_baht(employee_pool - actual_paid)
    room_service = round_baht(month_data["room_service"])
    fb_service = round_baht(month_data["fb_service"])
    zipline_service = round_baht(month_data["zipline_service"])
    other_service = round_baht(month_data["other_service"])
    total_service = round_baht(month_data["total_service"])
    return {
        "service_month_id": service_month.id,
        "month": service_month.month,
        "year": service_month.year,
        "month_no": month_number(service_month.month),
        "room_revenue": round_baht(room_service / 0.10),
        "fb_revenue": round_baht(fb_service / 0.10),
        "zipline_revenue": round_baht(zipline_service / 0.10),
        "other_revenue": round_baht(other_service / 0.10),
        "total_revenue": round_baht(total_service / 0.10),
        "service_charge_10": total_service,
        "employee_pool": employee_pool,
        "actual_employee_paid": actual_paid,
        "welfare_fund": round_baht(month_data["welfare_fund"] + balance_returned),
        "employee_deposit_total": deposit_total,
        "resort_fund": round_baht(month_data["resort_fund"]),
        "balance_returned_to_resort": balance_returned
    }

SERVICE_JV_DEPARTMENT_ACCOUNTS = {
    "RM": ("4051201", "RM-เงินค่าเซอร์วิสพนักงาน"),
    "FB": ("4151201", "FB-เงินค่าเซอร์วิสพนักงาน"),
    "MY": ("4251201", "MY-เงินค่าเซอร์วิสพนักงาน"),
    "TU": ("4351201", "TU-เงินค่าเซอร์วิสพนักงาน"),
    "AM": ("6051201", "AM-เงินค่าเซอร์วิสพนักงาน"),
    "AC": ("6151201", "AC-เงินค่าเซอร์วิสพนักงาน"),
    "SM": ("6251201", "SM-เงินค่าเซอร์วิสพนักงาน"),
    "EN": ("6351201", "EN-เงินค่าเซอร์วิสพนักงาน"),
    "GN": ("6451201", "GN-เงินค่าเซอร์วิสพนักงาน"),
    "HR": ("7051201", "HR-เงินค่าเซอร์วิสพนักงาน"),
}

SERVICE_JV_DEPARTMENT_ORDER = ["RM", "FB", "MY", "TU", "AM", "AC", "SM", "EN", "GN", "HR"]

def service_department_jv_group(department):
    code = str(department or "").split("-", 1)[0].strip().upper()
    return code if code in SERVICE_JV_DEPARTMENT_ACCOUNTS else ""

def build_service_jv_report(service_month, service_rows, employees):
    month_data = serialize_service_month(service_month)
    welfare_resort_total = round_baht(month_data["welfare_fund"]) + round_baht(month_data["resort_fund"])

    detail_rows = [
        serialize_service_detail_report(row, employees.get(str(row.emp_code)))
        for row in service_rows
    ]
    net_service_total = sum(round_baht(row.net_service or 0) for row in service_rows)
    deposit_deduction_total = sum(round_baht(row.deposit_deduction or 0) for row in service_rows)
    deposit_refund_total = sum(round_baht(row.get("deposit_refund", 0)) for row in detail_rows)

    jv_rows = [
        {
            "acc_no": "2003103",
            "name": "Service Charge ค้างจ่าย",
            "debit": 0,
            "credit": net_service_total,
        },
        {
            "acc_no": "2005002",
            "name": "สำรองเงินจาก Service",
            "debit": 0,
            "credit": welfare_resort_total,
        },
        {
            "acc_no": "3012010",
            "name": "กำไร(ขาดทุน)สะสม-จัดสรรเงินกองทุน",
            "debit": welfare_resort_total,
            "credit": 0,
        },
    ]

    if deposit_deduction_total > 0:
        jv_rows.append({
            "acc_no": "2004102",
            "name": "เงินประกันพนักงาน",
            "debit": 0,
            "credit": deposit_deduction_total,
        })

    department_totals = {}
    for row in detail_rows:
        department_code = service_department_jv_group(row.get("department"))
        if not department_code:
            continue
        department_totals[department_code] = department_totals.get(department_code, 0) + round_baht(row.get("total_after_deduction", 0))

    for department_code in SERVICE_JV_DEPARTMENT_ORDER:
        amount = department_totals.get(department_code, 0)
        if amount <= 0:
            continue
        acc_no, name = SERVICE_JV_DEPARTMENT_ACCOUNTS[department_code]
        jv_rows.append({
            "acc_no": acc_no,
            "name": name,
            "debit": amount,
            "credit": 0,
        })

    if deposit_refund_total > 0:
        jv_rows.append({
            "acc_no": "2004102",
            "name": "เงินประกันพนักงาน",
            "debit": deposit_refund_total,
            "credit": 0,
        })

    for row in jv_rows:
        row["debit"] = round_baht(row.get("debit", 0))
        row["credit"] = round_baht(row.get("credit", 0))
        row["net"] = round_baht(row["debit"] - row["credit"])

    total_debit = sum(row["debit"] for row in jv_rows)
    total_credit = sum(row["credit"] for row in jv_rows)
    return {
        "rows": jv_rows,
        "total_debit": total_debit,
        "total_credit": total_credit,
        "net": round_baht(total_debit - total_credit),
        "is_balanced": total_debit == total_credit,
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
    write_audit_log(
        data.get("audit_username", "-"),
        "Save Service Month",
        "Service Charge",
        f"{month}-{year}",
        audit_details(data, ["room_service", "fb_service", "zipline_service", "other_service", "manual_service_rate"])
    )
    session.refresh(item)
    return serialize_service_month(item)

@app.get("/api/service/calculate/{service_month_id}")
@app.get("/service/calculate/{service_month_id}")
def preview_service_calculation(service_month_id: int, manual_service_rate: float | None = None, refresh_eligibility: bool = False, session: Session = Depends(get_db)):
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
    calculated_rate = float(month_data["employee_pool"] / total_weight) if total_weight > 0 else 0
    selected_rate = float(manual_service_rate) if manual_service_rate is not None else calculated_rate

    rows = []
    for emp, existing, service_weight in base_rows:
        payroll_input = payroll_inputs.get(str(emp.emp_code), {})
        import_payroll_values = bool(payroll_input) and (not existing or refresh_eligibility)
        sick_days = payroll_input.get("sick_days", 0.0) if import_payroll_values else (existing.sick_days if existing else 0.0)
        leave_days = payroll_input.get("leave_days", 0.0) if import_payroll_values else (existing.leave_days if existing else 0.0)
        leave_hours = payroll_input.get("leave_hours", 0.0) if import_payroll_values else (existing.leave_hours if existing else 0.0)
        late_hours = payroll_input.get("late_hours", 0.0) if import_payroll_values else (existing.late_hours if existing else 0.0)
        evaluation_percent = existing.evaluation_percent if existing else 0.0
        prior_deposit_total = service_deposit_total_before(session, emp.emp_code, service_month_id, service_month)
        default_deposit = default_service_deposit(emp, service_month, service_weight, prior_deposit_total)
        deposit_deduction = (
            existing.deposit_deduction
            if existing and not refresh_eligibility and default_deposit > 0
            else default_deposit
        )
        if str(emp.service_type or "AUTO").upper() != "AUTO" or service_weight <= 0:
            deposit_deduction = 0
        notes = sanitize_service_manual_notes(existing.notes) if existing else ""
        gross_service = round_baht(selected_rate * service_weight)
        amounts = calculate_service_amounts({
            "gross_service": gross_service,
            "sick_days": sick_days,
            "leave_days": leave_days,
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
            "leave_day_deduction": amounts["leave_day_deduction"],
            "leave_hours": amounts["leave_hours"],
            "leave_hour_deduction": amounts["leave_hour_deduction"],
            "late_mins": payroll_input.get("late_mins") if payroll_input else None,
            "late_hours": amounts["late_hours"],
            "late_deduction": amounts["late_deduction"],
            "evaluation_percent": evaluation_percent or 0.0,
            "evaluation_deduction": amounts["evaluation_deduction"],
            "deposit_deduction": round_baht(deposit_deduction or 0),
            "net_service": amounts["net_service"],
            "source": payroll_input.get("source", ""),
            "payroll_cycle_id": payroll_input.get("payroll_cycle_id"),
            "payroll_cycle_name": payroll_input.get("payroll_cycle_name", ""),
            "payroll_month": payroll_input.get("payroll_month"),
            "payroll_year": payroll_input.get("payroll_year"),
            "imported_from_payroll": bool(payroll_input),
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
    data = sanitize_service_save_request(data)
    service_month = session.query(db.ServiceMonth).filter(db.ServiceMonth.id == service_month_id).first()
    if not service_month:
        raise HTTPException(status_code=404, detail="ไม่พบข้อมูล Service Charge เดือนนี้")

    manual_rate = data.get("manual_service_rate", None)
    service_month.manual_service_rate = None if manual_rate in [None, ""] else float(manual_rate)

    rows = []
    employees = {
        str(emp.emp_code): emp
        for emp in session.query(db.Employee).all()
    }
    for row in data.get("employees", []):
        normalized = dict(row)
        emp_code = str(normalized.get("emp_code", "") or "")
        employee = employees.get(emp_code)
        service_weight = calculate_service_weight(employee, service_month) if employee else float(normalized.get("service_weight", 0.0) or 0.0)
        service_rate = float(normalized.get("service_rate", 0.0) or 0.0)
        gross_service = round_baht(service_rate * service_weight)
        sick_days = float(normalized.get("sick_days", 0.0) or 0.0)
        leave_days = float(normalized.get("leave_days", 0.0) or 0.0)
        leave_hours = float(normalized.get("leave_hours", 0.0) or 0.0)
        late_hours = float(normalized.get("late_hours", 0.0) or 0.0)
        evaluation_percent = float(normalized.get("evaluation_percent", 0.0) or 0.0)
        deposit_deduction = round_baht(normalized.get("deposit_deduction", 0.0))
        prior_deposit_total = service_deposit_total_before(session, normalized.get("emp_code", ""), service_month_id, service_month)
        service_type = str(getattr(employee, "service_type", normalized.get("service_type", "AUTO")) or "AUTO").upper()
        expected_auto_deposit = default_service_deposit(employee, service_month, service_weight, prior_deposit_total) if employee else deposit_deduction

        if service_type != "AUTO" and deposit_deduction != 0:
            raise HTTPException(
                status_code=400,
                detail=f"Deposit deduction mismatch for {normalized.get('emp_code', '')}: service type {service_type} is not eligible for automatic deposit"
            )
        if service_type == "AUTO" and expected_auto_deposit == 0 and deposit_deduction != 0:
            raise HTTPException(
                status_code=400,
                detail=f"Deposit deduction mismatch for {normalized.get('emp_code', '')}: current employee eligibility requires deposit 0 but submitted deposit is {deposit_deduction}"
            )
        if service_weight <= 0 and deposit_deduction != 0:
            raise HTTPException(
                status_code=400,
                detail=f"Deposit deduction mismatch for {normalized.get('emp_code', '')}: service weight is 0 but submitted deposit is {deposit_deduction}"
            )
        if prior_deposit_total >= 1500 and deposit_deduction != 0:
            raise HTTPException(
                status_code=400,
                detail=f"Deposit deduction mismatch for {normalized.get('emp_code', '')}: prior deposit total is already 1,500 Baht"
            )
        if prior_deposit_total + deposit_deduction > 1500:
            raise HTTPException(
                status_code=400,
                detail=f"Deposit deduction for {normalized.get('emp_code', '')} exceeds 1,500 Baht total"
            )

        amounts = calculate_service_amounts({
            "gross_service": gross_service,
            "sick_days": sick_days,
            "leave_days": leave_days,
            "leave_hours": leave_hours,
            "late_hours": late_hours,
            "evaluation_percent": evaluation_percent,
            "deposit_deduction": deposit_deduction
        })

        normalized.update({
            "first_name": employee.first_name if employee else normalized.get("first_name", ""),
            "last_name": employee.last_name if employee else normalized.get("last_name", ""),
            "department": employee.department if employee else normalized.get("department", ""),
            "position": employee.position if employee else normalized.get("position", ""),
            "service_type": employee.service_type if employee else normalized.get("service_type", "AUTO"),
            "service_percent": employee.service_percent if employee else normalized.get("service_percent", 100.0),
            "eligible_service_month": eligible_service_month_index(employee, service_month) if employee else normalized.get("eligible_service_month", ""),
            "service_weight": service_weight,
            "service_rate": service_rate,
            "gross_service": gross_service,
            "sick_days": sick_days,
            "sick_deduction": amounts["sick_deduction"],
            "leave_days": leave_days,
            "leave_day_deduction": amounts["leave_day_deduction"],
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
            service_rate=float(row.get("service_rate", 0.0) or 0.0),
            gross_service=round_baht(row.get("gross_service", 0.0)),
            sick_days=float(row.get("sick_days", 0.0) or 0.0),
            sick_deduction=round_baht(row.get("sick_deduction", 0.0)),
            leave_days=float(row.get("leave_days", 0.0) or 0.0),
            leave_day_deduction=round_baht(row.get("leave_day_deduction", 0.0)),
            leave_hours=float(row.get("leave_hours", 0.0) or 0.0),
            leave_hour_deduction=round_baht(row.get("leave_hour_deduction", 0.0)),
            late_hours=float(row.get("late_hours", 0.0) or 0.0),
            late_deduction=round_baht(row.get("late_deduction", 0.0)),
            evaluation_percent=float(row.get("evaluation_percent", 0.0) or 0.0),
            evaluation_deduction=round_baht(row.get("evaluation_deduction", 0.0)),
            deposit_deduction=round_baht(row.get("deposit_deduction", 0.0)),
            net_service=round_baht(row.get("net_service", 0.0)),
            notes=sanitize_service_manual_notes(row.get("notes", ""))
        )
        session.add(service_employee)

    session.flush()
    saved_rows = session.query(db.ServiceEmployee).filter(
        db.ServiceEmployee.service_month_id == service_month_id
    ).all()
    saved_summary = service_summary(
        service_month,
        [serialize_service_employee(row) for row in saved_rows]
    )
    try:
        validate_service_summary_consistency(summary, saved_summary)
    except HTTPException:
        session.rollback()
        raise

    session.commit()
    write_audit_log(
        data.get("audit_username", "-"),
        "Save Service Calculation",
        "Service Charge",
        service_month_id,
        f"employees={len(rows)}, actual_employee_paid={summary['actual_employee_paid']}"
    )
    if rows:
        write_audit_log(
            data.get("audit_username", "-"),
            "Update Service Employee",
            "Service Charge",
            service_month_id,
            f"employees={len(rows)}"
        )
    return {"message": "บันทึก Service Calculation สำเร็จ", "summary": summary}

@app.get("/api/service/employees/{service_month_id}")
@app.get("/service/employees/{service_month_id}")
def get_service_employees(service_month_id: int, session: Session = Depends(get_db)):
    rows = session.query(db.ServiceEmployee).filter(
        db.ServiceEmployee.service_month_id == service_month_id
    ).order_by(db.ServiceEmployee.department.asc(), db.ServiceEmployee.emp_code.asc()).all()
    return [serialize_service_employee(row) for row in rows]

@app.get("/api/service/slips")
@app.get("/service/slips")
def get_all_service_slips(session: Session = Depends(get_db)):
    rows = session.query(db.ServiceEmployee, db.ServiceMonth).join(
        db.ServiceMonth,
        db.ServiceEmployee.service_month_id == db.ServiceMonth.id
    ).order_by(db.ServiceMonth.year.desc(), db.ServiceMonth.id.desc(), db.ServiceEmployee.emp_code.asc()).all()
    employees = {str(emp.emp_code): emp for emp in session.query(db.Employee).all()}
    payroll_inputs_by_month = {}
    result = []
    for row, service_month in rows:
        if service_month.id not in payroll_inputs_by_month:
            payroll_inputs_by_month[service_month.id] = payroll_service_inputs(session, service_month)
        payroll_input = payroll_inputs_by_month[service_month.id].get(str(row.emp_code), {})
        result.append(serialize_service_slip(row, service_month, employees.get(str(row.emp_code)), payroll_input))
    return result

@app.get("/api/service/slips/{emp_code}")
@app.get("/service/slips/{emp_code}")
def get_employee_service_slips(emp_code: str, session: Session = Depends(get_db)):
    rows = session.query(db.ServiceEmployee, db.ServiceMonth).join(
        db.ServiceMonth,
        db.ServiceEmployee.service_month_id == db.ServiceMonth.id
    ).filter(
        db.ServiceEmployee.emp_code == emp_code
    ).order_by(db.ServiceMonth.year.desc(), db.ServiceMonth.id.desc()).all()
    employee = session.query(db.Employee).filter(db.Employee.emp_code == emp_code).first()
    payroll_inputs_by_month = {}
    result = []
    for row, service_month in rows:
        if service_month.id not in payroll_inputs_by_month:
            payroll_inputs_by_month[service_month.id] = payroll_service_inputs(session, service_month)
        payroll_input = payroll_inputs_by_month[service_month.id].get(str(row.emp_code), {})
        result.append(serialize_service_slip(row, service_month, employee, payroll_input))
    return result

@app.get("/api/service/reports/{service_month_id}")
@app.get("/service/reports/{service_month_id}")
def get_service_reports(service_month_id: int, session: Session = Depends(get_db)):
    service_month = session.query(db.ServiceMonth).filter(db.ServiceMonth.id == service_month_id).first()
    if not service_month:
        raise HTTPException(status_code=404, detail="ไม่พบข้อมูล Service Charge เดือนนี้")

    service_rows = session.query(db.ServiceEmployee).filter(db.ServiceEmployee.service_month_id == service_month_id).order_by(
        db.ServiceEmployee.department.asc(),
        db.ServiceEmployee.emp_code.asc()
    ).all()
    employees = {str(emp.emp_code): emp for emp in session.query(db.Employee).all()}
    rows = [serialize_service_employee(row) for row in service_rows]
    payroll_inputs = payroll_service_inputs(session, service_month)
    payroll_cycle = latest_payroll_cycle_for_service_month(session, service_month)
    payroll_transactions = []
    if payroll_cycle:
        payroll_transactions = session.query(db.PayrollTransaction).filter(
            db.PayrollTransaction.cycle_name == payroll_cycle.cycle_name
        ).order_by(db.PayrollTransaction.id.asc()).all()
    payroll_order = {
        str(transaction.emp_code): index
        for index, transaction in enumerate(payroll_transactions)
    }
    for row in rows:
        emp_code = str(row.get("emp_code", "") or "")
        if emp_code in payroll_order:
            row["payroll_order"] = payroll_order[emp_code]
    distribution = {}
    for row in rows:
        amount = round_baht(row.get("net_service", 0))
        distribution[amount] = distribution.get(amount, 0) + 1

    distribution_summary = [
        {"Net Service Amount": amount, "Employee Count": count, "Total Amount": amount * count}
        for amount, count in sorted(distribution.items(), key=lambda item: item[0], reverse=True)
    ]

    denominations = [1000, 500, 100, 50, 20]
    cash_totals = {
        denom: {"Denomination": denom, "Quantity": 0, "Amount": 0}
        for denom in denominations
    }
    cash_totals["coins/remainder"] = {"Denomination": "coins/remainder", "Quantity": 0, "Amount": 0}
    for row in rows:
        employee_remaining = round_baht(row.get("net_service", 0))
        for denom in denominations:
            qty = employee_remaining // denom
            amount = qty * denom
            cash_totals[denom]["Quantity"] += qty
            cash_totals[denom]["Amount"] += amount
            employee_remaining -= amount
        if employee_remaining:
            cash_totals["coins/remainder"]["Quantity"] += employee_remaining
            cash_totals["coins/remainder"]["Amount"] += employee_remaining
    cash_rows = [cash_totals[denom] for denom in denominations + ["coins/remainder"]]

    summary = service_summary(service_month, rows)
    return {
        "summary": summary,
        "service_month": serialize_service_month(service_month),
        "service_detail": [
            {
                **serialize_service_detail_report(row, employees.get(str(row.emp_code)), payroll_inputs.get(str(row.emp_code), {})),
                **({"payroll_order": payroll_order[str(row.emp_code)]} if str(row.emp_code) in payroll_order else {})
            }
            for row in service_rows
        ],
        "distribution_summary": distribution_summary,
        "total_employees": len(rows),
        "cash_preparation": cash_rows,
        "cash_grand_total": sum(round_baht(row.get("net_service", 0)) for row in rows),
        "monthly_jv": build_service_jv_report(service_month, service_rows, employees)
    }

@app.get("/api/service/reports/summary/{year}")
@app.get("/service/reports/summary/{year}")
def get_service_summary_report(year: int, session: Session = Depends(get_db)):
    service_months = session.query(db.ServiceMonth).filter(
        db.ServiceMonth.year == year
    ).all()
    service_months = sorted(service_months, key=lambda item: month_number(item.month))

    summary_rows = []
    for service_month in service_months:
        service_rows = session.query(db.ServiceEmployee).filter(
            db.ServiceEmployee.service_month_id == service_month.id
        ).all()
        summary_rows.append(serialize_service_summary_report(service_month, service_rows))

    total_fields = [
        "room_revenue", "fb_revenue", "zipline_revenue", "other_revenue",
        "total_revenue", "service_charge_10", "employee_pool", "actual_employee_paid",
        "welfare_fund", "employee_deposit_total", "resort_fund",
        "balance_returned_to_resort"
    ]
    yearly_total = {field: sum(round_baht(row.get(field, 0)) for row in summary_rows) for field in total_fields}
    yearly_total.update({"month": "Yearly Total", "year": year})

    return {
        "year": year,
        "rows": summary_rows,
        "yearly_total": yearly_total
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
def delete_payroll_cycle(cycle_name: str, username: str | None = None, session: Session = Depends(get_db)):
    session.query(db.PayrollTransaction).filter(db.PayrollTransaction.cycle_name == cycle_name).delete()
    session.commit()
    write_audit_log(username or "-", "Delete Payroll Cycle", "Payroll", cycle_name, "")
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
    username = data.get("audit_username", "-")
    session.commit()
    if time_data:
        write_audit_log(username, "Upload Payroll", "Payroll", cycle_name, f"rows={len(time_data)}")
    write_audit_log(username, "Calculate Payroll", "Payroll", cycle_name, f"employees={len(transactions_to_add)}")
    return {"message": f"คำนวณเงินเดือนรอบ {cycle_name} สำเร็จ! ({len(transactions_to_add)} คน)"}

@app.get("/dashboard/trend")
def get_dashboard_trend(session: Session = Depends(get_db)):
    results = session.query(
        db.PayrollTransaction.cycle_name,
        func.sum(db.PayrollTransaction.net_salary).label("total_net_salary")
    ).group_by(db.PayrollTransaction.cycle_name).all()
    
    trend_data = [{"รอบเงินเดือน": r.cycle_name, "รายจ่ายสุทธิ": r.total_net_salary} for r in results]
    return trend_data
