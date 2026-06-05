from fastapi import FastAPI, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from sqlalchemy import func
import database as db
from typing import List
import datetime

app = FastAPI()

# 🟢 บรรทัดนี้ช่วยสร้างตารางให้ใหม่ทันทีถ้าฐานข้อมูลหาย
db.Base.metadata.create_all(bind=db.engine)

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
            "is_sso": emp.is_sso
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
        is_sso=data.get("is_sso", True)
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
                    is_sso=bool(emp_data.get("is_sso", True))
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
            "late_mins": t.late_mins, "unpaid_leave_days": t.unpaid_leave_days, "leave_hours": t.leave_hours,
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
            unpaid_leave_days=absent_days, leave_hours=leave_hrs, leave_deduction=total_leave_deduct,
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
