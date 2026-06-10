from sqlalchemy import create_engine, Column, Integer, String, Float, Boolean
from sqlalchemy.orm import declarative_base, sessionmaker

SQLALCHEMY_DATABASE_URL = "sqlite:///./payroll.db"

engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

# 👥 ตารางเก็บข้อมูลพนักงาน
class Employee(Base):
    __tablename__ = "employees"

    id = Column(Integer, primary_key=True, index=True)
    emp_code = Column(String, unique=True, index=True)
    machine_id = Column(String, nullable=True) # 🟢 เพิ่มสำหรับเครื่องสแกนนิ้ว
    first_name = Column(String)
    last_name = Column(String)
    department = Column(String, nullable=True)
    position = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    start_date = Column(String, nullable=True)
    address = Column(String, nullable=True)
    tax_info = Column(String, nullable=True)
    base_salary = Column(Float, default=0.0)   # 🟢 ฐานเงินเดือน
    account_no = Column(String, nullable=True) # 🟢 เลขบัญชี
    is_active = Column(Boolean, default=True)
    is_sso = Column(Boolean, default=True)     # 🟢 หักประกันสังคม
    service_type = Column(String, default="AUTO")
    service_percent = Column(Float, default=100.0)

# 💰 ตารางเก็บประวัติการจ่ายเงินเดือน
class PayrollTransaction(Base):
    __tablename__ = "payroll_transactions"

    id = Column(Integer, primary_key=True, index=True)
    cycle_name = Column(String, index=True)
    payment_date = Column(String)
    emp_code = Column(String)
    first_name = Column(String)
    last_name = Column(String)
    department = Column(String)
    position = Column(String)
    account_no = Column(String)
    
    base_salary = Column(Float, default=0.0)
    ot_15_hours = Column(Float, default=0.0)
    ot_15_amount = Column(Float, default=0.0)
    ot_1_hours = Column(Float, default=0.0)
    ot_1_amount = Column(Float, default=0.0)
    ot_amount = Column(Float, default=0.0)
    other_benefits = Column(Float, default=0.0)
    backpay = Column(Float, default=0.0)
    gross_salary = Column(Float, default=0.0)
    
    late_mins = Column(Float, default=0.0)
    unpaid_leave_days = Column(Float, default=0.0)
    leave_hours = Column(Float, default=0.0)
    leave_deduction = Column(Float, default=0.0)
    
    company_loan = Column(Float, default=0.0)
    student_loan = Column(Float, default=0.0)
    sso_deduction = Column(Float, default=0.0)
    
    net_salary = Column(Float, default=0.0)

# 📜 ตารางเก็บประวัติการใช้งาน
class AccessLog(Base):
    __tablename__ = "access_logs"

    id = Column(Integer, primary_key=True, index=True)
    user = Column(String, index=True)
    action = Column(String)
    timestamp = Column(String, index=True)

# 🧾 ตารางตั้งค่า Service Charge รายเดือน (Phase 1: โครงสร้างเท่านั้น)
class ServiceMonth(Base):
    __tablename__ = "service_months"

    id = Column(Integer, primary_key=True, index=True)
    month = Column(String, index=True)
    year = Column(Integer, index=True)
    room_service = Column(Float, default=0.0)
    fb_service = Column(Float, default=0.0)
    zipline_service = Column(Float, default=0.0)
    other_service = Column(Float, default=0.0)
    note = Column(String, nullable=True)

# 👥 ตาราง snapshot พนักงานที่เกี่ยวข้องกับ Service Charge
class ServiceEmployee(Base):
    __tablename__ = "service_employees"

    id = Column(Integer, primary_key=True, index=True)
    service_month_id = Column(Integer, index=True)
    emp_code = Column(String, index=True)
    service_type = Column(String, default="AUTO")
    service_percent = Column(Float, default=100.0)
    fixed_amount = Column(Float, default=0.0)

# 💳 ตารางเงินฝาก/รายการพักยอดของพนักงาน
class EmployeeDeposit(Base):
    __tablename__ = "employee_deposits"

    id = Column(Integer, primary_key=True, index=True)
    emp_code = Column(String, index=True)
    deposit_month = Column(String, index=True)
    deposit_year = Column(Integer, index=True)
    amount = Column(Float, default=0.0)
    note = Column(String, nullable=True)
