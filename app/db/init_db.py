import logging
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import settings
from app.core.database import Base, engine
from app.core.security import hash_password
from app.models.department import Department

from app.models.lab import LabTestCatalog
from app.models.permission import Permission
from app.models.pharmacy import PharmacyMedicine
from app.models.role import Role
from app.models.user import User
from app.models.emergency import EmergencyCodeGroup

logger = logging.getLogger(__name__)

DEFAULT_PERMISSIONS = [
    # System Wildcard
    {"code": "*", "name": "Super Admin All Access", "module": "SYSTEM", "description": "Full unconstrained administrative access"},
    
    # User Management
    {"code": "users:read", "name": "Read Users", "module": "USERS", "description": "View user profiles and accounts"},
    {"code": "users:create", "name": "Create Staff & Users", "module": "USERS", "description": "Register staff and patient accounts"},
    {"code": "users:update", "name": "Update Users", "module": "USERS", "description": "Edit user profile info"},
    {"code": "users:delete", "name": "Delete Users", "module": "USERS", "description": "Deactivate or delete users"},
    
    # Roles & Permissions
    {"code": "roles:read", "name": "Read Roles", "module": "ROLES", "description": "View roles and sub-roles"},
    {"code": "roles:create", "name": "Create Roles", "module": "ROLES", "description": "Create new dynamic roles and sub-roles"},
    {"code": "roles:update", "name": "Update Roles", "module": "ROLES", "description": "Modify role permissions and properties"},
    {"code": "roles:delete", "name": "Delete Roles", "module": "ROLES", "description": "Delete custom roles"},
    {"code": "roles:assign", "name": "Assign Roles", "module": "ROLES", "description": "Assign or reassign roles to users"},
    {"code": "permissions:read", "name": "Read Permissions", "module": "PERMISSIONS", "description": "View all available permissions"},
    {"code": "permissions:create", "name": "Create Permissions", "module": "PERMISSIONS", "description": "Create dynamic system permissions"},

    # Appointments
    {"code": "appointments:read", "name": "Read Appointments", "module": "APPOINTMENTS", "description": "View appointments"},
    {"code": "appointments:create", "name": "Create Appointments", "module": "APPOINTMENTS", "description": "Book new appointments"},
    {"code": "appointments:approve", "name": "Approve Appointments", "module": "APPOINTMENTS", "description": "Compounder approves and verifies appointments"},
    {"code": "appointments:cancel", "name": "Cancel Appointments", "module": "APPOINTMENTS", "description": "Cancel appointments"},

    # Queue & Tokens
    {"code": "queue:read", "name": "View Queue", "module": "QUEUE", "description": "View live queue status and token numbers"},
    {"code": "queue:manage", "name": "Manage Queue", "module": "QUEUE", "description": "Compounder activates, holds, or skips tokens"},
    {"code": "queue:call_patient", "name": "Call Patient", "module": "QUEUE", "description": "Notify patient and doctor for consultation"},

    # Triage & Vitals
    {"code": "vitals:read", "name": "Read Vitals", "module": "VITALS", "description": "View recorded blood pressure, pulse, etc."},
    {"code": "vitals:create", "name": "Record Vitals", "module": "VITALS", "description": "Compounder records pre-consultation vitals"},

    # Consultations & Doctor Notes
    {"code": "consultations:read", "name": "Read Consultations", "module": "CONSULTATIONS", "description": "View consultation notes and diagnosis"},
    {"code": "consultations:create", "name": "Create Consultation", "module": "CONSULTATIONS", "description": "Doctor starts consultation and records notes"},
    {"code": "consultations:update", "name": "Update Consultation", "module": "CONSULTATIONS", "description": "Edit or finalize consultation"},

    # Prescriptions
    {"code": "prescriptions:read", "name": "Read Prescriptions", "module": "PRESCRIPTIONS", "description": "View prescriptions and medication instructions"},
    {"code": "prescriptions:create", "name": "Create Prescriptions", "module": "PRESCRIPTIONS", "description": "Doctor prescribes medicines"},
    {"code": "prescriptions:dispense", "name": "Dispense Prescriptions", "module": "PRESCRIPTIONS", "description": "Pharmacist dispenses prescribed drugs"},

    # Lab Diagnostics
    {"code": "lab:read_orders", "name": "Read Lab Orders", "module": "LAB", "description": "View diagnostic test requests"},
    {"code": "lab:order_test", "name": "Order Lab Test", "module": "LAB", "description": "Doctor orders blood, x-ray, or imaging tests"},
    {"code": "lab:upload_result", "name": "Upload Lab Result", "module": "LAB", "description": "Lab assistant enters test results and uploads reports"},
    {"code": "lab:manage_catalog", "name": "Manage Lab Catalog", "module": "LAB", "description": "Lab assistant configures available test catalog"},

    # Pharmacy & Inventory
    {"code": "pharmacy:read_inventory", "name": "Read Inventory", "module": "PHARMACY", "description": "View pharmacy drug stock"},
    {"code": "pharmacy:manage_inventory", "name": "Manage Inventory", "module": "PHARMACY", "description": "Pharmacist updates drug stock, prices, and batches"},
    {"code": "pharmacy:dispense", "name": "Dispense Medicine", "module": "PHARMACY", "description": "Pharmacist confirms medicine dispensation"},

    # Emergency Codes & Responders
    {"code": "emergency:trigger", "name": "Trigger Emergency Code", "module": "EMERGENCY", "description": "Trigger hospital emergency color code broadcast"},
    {"code": "emergency:read", "name": "Read Emergency Alerts", "module": "EMERGENCY", "description": "View active and historical hospital code alerts"},
    {"code": "emergency:manage_groups", "name": "Manage Emergency Groups", "module": "EMERGENCY", "description": "Assign staff members to emergency code responder teams"},
]

DEFAULT_ROLES = {
    "SUPER_ADMIN": {
        "name": "Super Administrator",
        "description": "Full access to entire hospital management system",
        "is_system": True,
        "permissions": ["*"],
    },
    "DOCTOR": {
        "name": "Doctor / Physician",
        "description": "Examines patients, records diagnosis, prescribes medications, orders lab tests",
        "is_system": True,
        "permissions": [
            "appointments:read",
            "queue:read",
            "queue:manage",
            "queue:call_patient",
            "vitals:read",
            "vitals:create",
            "consultations:read",
            "consultations:create",
            "consultations:update",
            "prescriptions:read",
            "prescriptions:create",
            "pharmacy:read_inventory",
            "lab:order_test",
            "lab:read_orders",
            "emergency:trigger",
            "emergency:read",
        ],
    },
    "COMPOUNDER": {
        "name": "Compounder / Triage Staff",
        "description": "Verifies appointments, manages live queues, records vitals, registers walk-in patients",
        "is_system": True,
        "permissions": [
            "appointments:read",
            "appointments:create",
            "appointments:approve",
            "appointments:cancel",
            "queue:read",
            "queue:manage",
            "queue:call_patient",
            "vitals:read",
            "vitals:create",
            "users:create",
            "emergency:trigger",
            "emergency:read",
        ],
    },
    "NURSE": {
        "name": "Nurse / Ward Staff",
        "description": "Ward care, vitals logging, patient monitoring, and rapid emergency response",
        "is_system": True,
        "permissions": [
            "appointments:read",
            "queue:read",
            "vitals:read",
            "vitals:create",
            "consultations:read",
            "prescriptions:read",
            "lab:read_orders",
            "emergency:trigger",
            "emergency:read",
        ],
    },
    "LAB_ASSISTANT": {
        "name": "Lab Assistant / Pathologist",
        "description": "Manages test orders, performs lab tests, records results and uploads reports",
        "is_system": True,
        "permissions": [
            "lab:read_orders",
            "lab:upload_result",
            "lab:manage_catalog",
        ],
    },
    "PHARMACIST": {
        "name": "Pharmacist",
        "description": "Manages medication inventory, views prescriptions, and dispenses medicine",
        "is_system": True,
        "permissions": [
            "prescriptions:read",
            "prescriptions:dispense",
            "pharmacy:read_inventory",
            "pharmacy:manage_inventory",
            "pharmacy:dispense",
        ],
    },
    "PATIENT": {
        "name": "Patient",
        "description": "Books appointments, views queue number, accesses prescriptions and lab reports",
        "is_system": True,
        "permissions": [
            "appointments:read",
            "appointments:create",
            "queue:read",
            "vitals:read",
            "vitals:create",
            "consultations:read",
            "prescriptions:read",
            "lab:read_orders",
        ],
    },
}

DEFAULT_DEPARTMENTS = [
    {"code": "GENERAL_MEDICINE", "name": "General Medicine", "description": "Primary healthcare, chronic diseases, infections, and fever evaluation"},
    {"code": "CARDIOLOGY", "name": "Cardiology", "description": "Cardiovascular, heart health, hypertension, and chest discomfort care"},
    {"code": "DERMATOLOGY", "name": "Dermatology", "description": "Skin, hair, nails, allergies, and rash management"},
    {"code": "NEUROLOGY", "name": "Neurology", "description": "Brain, nerve, migraine, stroke, and dizziness treatment"},
    {"code": "ORTHOPEDICS", "name": "Orthopedics", "description": "Bone fractures, joints, spine, arthritis, and sports injuries"},
    {"code": "PEDIATRICS", "name": "Pediatrics", "description": "Infant, child health, and pediatric development"},
    {"code": "ENT", "name": "Ear Nose & Throat (ENT)", "description": "Sinus, ear infections, throat pain, and hearing disorders"},
]



DEFAULT_LAB_TESTS = [
    {"code": "CBC", "name": "Complete Blood Count (CBC)", "category": "HEMATOLOGY", "description": "RBC, WBC, Platelets, Hemoglobin, Hematocrit", "standard_turnaround_hours": 4},
    {"code": "LIPID_PROFILE", "name": "Fasting Lipid Profile", "category": "BIOCHEMISTRY", "description": "Total Cholesterol, HDL, LDL, Triglycerides", "standard_turnaround_hours": 8},
    {"code": "XRAY_CHEST", "name": "Chest X-Ray (PA View)", "category": "RADIOLOGY", "description": "Thoracic radiography for lung and heart enlargement evaluation", "standard_turnaround_hours": 2},
    {"code": "ECG", "name": "12-Lead Electrocardiogram", "category": "CARDIOLOGY", "description": "Cardiac electrical activity recording", "standard_turnaround_hours": 1},
    {"code": "URINE_ROUTINE", "name": "Urine Routine & Microscopy", "category": "PATHOLOGY", "description": "Urinalysis for renal and urinary tract assessment", "standard_turnaround_hours": 4},
    {"code": "BLOOD_SUGAR_FASTING", "name": "Fasting Blood Sugar (FBS)", "category": "BIOCHEMISTRY", "description": "Plasma glucose after 8-10 hours fasting", "standard_turnaround_hours": 2},
]

DEFAULT_PHARMACY_MEDICINES = [
    {
        "name": "Atorvastatin 20mg",
        "generic_name": "Atorvastatin",
        "category": "CARDIOVASCULAR",
        "dosage_form": "TABLET",
        "unit_price": 1.20,
        "stock_quantity": 250,
        "reorder_level": 50,
    },
    {
        "name": "Aspirin 75mg",
        "generic_name": "Acetylsalicylic Acid",
        "category": "CARDIOVASCULAR",
        "dosage_form": "TABLET",
        "unit_price": 0.45,
        "stock_quantity": 400,
        "reorder_level": 100,
    },
    {
        "name": "Amoxicillin 500mg",
        "generic_name": "Amoxicillin",
        "category": "ANTIBIOTIC",
        "dosage_form": "CAPSULE",
        "unit_price": 0.85,
        "stock_quantity": 300,
        "reorder_level": 60,
    },
    {
        "name": "Paracetamol 650mg",
        "generic_name": "Acetaminophen",
        "category": "ANALGESIC",
        "dosage_form": "TABLET",
        "unit_price": 0.30,
        "stock_quantity": 600,
        "reorder_level": 100,
    },
    {
        "name": "Azithromycin 500mg",
        "generic_name": "Azithromycin",
        "category": "ANTIBIOTIC",
        "dosage_form": "TABLET",
        "unit_price": 2.10,
        "stock_quantity": 180,
        "reorder_level": 40,
    },
    {
        "name": "Metformin 500mg",
        "generic_name": "Metformin Hydrochloride",
        "category": "ANTIDIABETIC",
        "dosage_form": "TABLET",
        "unit_price": 0.50,
        "stock_quantity": 500,
        "reorder_level": 80,
    },
]

DEFAULT_EMERGENCY_GROUPS = [
    {
        "code": "CODE_BLUE",
        "name": "Code Blue — Cardiac Arrest / CPR",
        "color_hex": "#2563EB",
        "badge_color": "blue",
        "description": "Adult or pediatric cardiac/respiratory arrest requiring immediate CPR resuscitation & crash cart.",
        "call_to_action": "Resuscitation team proceed immediately with crash cart & defibrillator",
    },
    {
        "code": "CODE_RED",
        "name": "Code Red — Fire & Smoke Alert",
        "color_hex": "#DC2626",
        "badge_color": "red",
        "description": "Active fire, electrical short circuit, or dense smoke detected. Execute hospital RACE evacuation protocol.",
        "call_to_action": "Fire marshals and emergency safety team assemble; secure zone",
    },
    {
        "code": "CODE_PINK",
        "name": "Code Pink — Infant / Pediatric Emergency",
        "color_hex": "#DB2777",
        "badge_color": "pink",
        "description": "Pediatric acute respiratory compromise, infant cardiac arrest, or suspected child abduction.",
        "call_to_action": "Pediatric rapid response code team assemble immediately",
    },
    {
        "code": "CODE_YELLOW",
        "name": "Code Yellow — Disaster / Mass Casualty",
        "color_hex": "#D97706",
        "badge_color": "yellow",
        "description": "External multi-trauma disaster, vehicle collision, or explosion resulting in mass patient influx.",
        "call_to_action": "All available ER physicians, triage staff, and trauma surgeons report to triage bay",
    },
    {
        "code": "CODE_ORANGE",
        "name": "Code Orange — Hazardous Spill / Biohazard",
        "color_hex": "#EA580C",
        "badge_color": "orange",
        "description": "Toxic chemical, concentrated acid, radiation, or infectious biohazard leak.",
        "call_to_action": "Hazmat decontamination team proceed with Level B/C PPE",
    },
    {
        "code": "CODE_BLACK",
        "name": "Code Black — Security / Armed Intruder",
        "color_hex": "#1E293B",
        "badge_color": "dark",
        "description": "Violent assailant, weapon threat, or combative intruder endangering patients or staff.",
        "call_to_action": "Hospital security and local police respond; ward shelter-in-place initiated",
    },
    {
        "code": "RAPID_RESPONSE",
        "name": "Rapid Response — Vital Deterioration",
        "color_hex": "#059669",
        "badge_color": "emerald",
        "description": "Acute bedside clinical decompensation, severe hypoxia, hypotension, or GCS drop before cardiac arrest.",
        "call_to_action": "ICU physician and critical care nurse bedside evaluation within 3 minutes",
    },
]

async def init_db(db: AsyncSession) -> None:
    """
    Initializes database schema, seeds permissions, roles, superadmin,
    clinical departments, compounder, pharmacist, lab assistant, and doctors with schedules.
    """
    # 1. Create tables if they do not exist
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # 2. Seed Permissions
    permissions_map = {}
    for perm_data in DEFAULT_PERMISSIONS:
        stmt = select(Permission).where(Permission.code == perm_data["code"])
        result = await db.execute(stmt)
        existing_perm = result.scalar_one_or_none()
        if not existing_perm:
            new_perm = Permission(
                code=perm_data["code"],
                name=perm_data["name"],
                module=perm_data["module"],
                description=perm_data["description"],
            )
            db.add(new_perm)
            await db.flush()
            permissions_map[perm_data["code"]] = new_perm
        else:
            permissions_map[perm_data["code"]] = existing_perm

    # 3. Seed Roles
    roles_map = {}
    for role_code, role_info in DEFAULT_ROLES.items():
        stmt = select(Role).where(Role.code == role_code)
        result = await db.execute(stmt)
        existing_role = result.scalar_one_or_none()

        role_perms = [
            permissions_map[code]
            for code in role_info["permissions"]
            if code in permissions_map
        ]

        if not existing_role:
            new_role = Role(
                code=role_code,
                name=role_info["name"],
                description=role_info["description"],
                is_system=role_info["is_system"],
                permissions=role_perms,
            )
            db.add(new_role)
            await db.flush()
            roles_map[role_code] = new_role
        else:
            existing_role.permissions = role_perms
            db.add(existing_role)
            roles_map[role_code] = existing_role

    # 4. Seed Super Admin User
    admin_email = settings.FIRST_SUPERADMIN_EMAIL.lower().strip()
    stmt = select(User).where(User.email == admin_email)
    result = await db.execute(stmt)
    admin_user = result.scalar_one_or_none()

    if not admin_user:
        admin_role = roles_map.get("SUPER_ADMIN")
        admin_user = User(
            email=admin_email,
            phone="+10000000000",
            full_name=settings.FIRST_SUPERADMIN_NAME,
            hashed_password=hash_password(settings.FIRST_SUPERADMIN_PASSWORD),
            is_active=True,
            is_verified=True,
            roles=[admin_role] if admin_role else [],
        )
        db.add(admin_user)
        await db.flush()
        logger.info(f"Created default Super Admin user: {admin_email}")



    # 6. Seed Departments
    dept_map = {}
    for d_data in DEFAULT_DEPARTMENTS:
        stmt = select(Department).where(Department.code == d_data["code"])
        result = await db.execute(stmt)
        existing_dept = result.scalar_one_or_none()
        if not existing_dept:
            new_dept = Department(
                code=d_data["code"],
                name=d_data["name"],
                description=d_data["description"],
                is_active=True,
            )
            db.add(new_dept)
            await db.flush()
            dept_map[d_data["code"]] = new_dept
        else:
            dept_map[d_data["code"]] = existing_dept


    # 8. Seed Lab Test Catalog
    for lt in DEFAULT_LAB_TESTS:
        stmt = select(LabTestCatalog).where(LabTestCatalog.code == lt["code"])
        result = await db.execute(stmt)
        existing_test = result.scalar_one_or_none()
        if not existing_test:
            new_test = LabTestCatalog(
                code=lt["code"],
                name=lt["name"],
                category=lt["category"],
                description=lt["description"],
                standard_turnaround_hours=lt["standard_turnaround_hours"],
                is_active=True,
            )
            db.add(new_test)

    # 9. Seed Pharmacy Medicines
    for med_data in DEFAULT_PHARMACY_MEDICINES:
        stmt = select(PharmacyMedicine).where(PharmacyMedicine.name == med_data["name"])
        result = await db.execute(stmt)
        existing_med = result.scalar_one_or_none()
        if not existing_med:
            new_med = PharmacyMedicine(
                name=med_data["name"],
                generic_name=med_data["generic_name"],
                category=med_data["category"],
                dosage_form=med_data["dosage_form"],
                unit_price=med_data["unit_price"],
                stock_quantity=med_data["stock_quantity"],
                reorder_level=med_data["reorder_level"],
                is_active=True,
            )
            db.add(new_med)

    # 10. Seed Default Nurse User
    nurse_email = "nurse@hospital.com"
    stmt = select(User).where(User.email == nurse_email)
    result = await db.execute(stmt)
    nurse_user = result.scalar_one_or_none()
    nurse_role = roles_map.get("NURSE")
    if not nurse_user:
        nurse_user = User(
            email=nurse_email,
            phone="+10000000004",
            full_name="Nurse Sarah Jenkins, RN",
            hashed_password=hash_password("Nurse@123"),
            is_active=True,
            is_verified=True,
            roles=[nurse_role] if nurse_role else [],
        )
        db.add(nurse_user)
        await db.flush()
        logger.info(f"Created default Nurse user: {nurse_email}")

    # 11. Seed Emergency Code Groups
    groups_map = {}
    for g_data in DEFAULT_EMERGENCY_GROUPS:
        stmt = select(EmergencyCodeGroup).where(EmergencyCodeGroup.code == g_data["code"])
        result = await db.execute(stmt)
        existing_group = result.scalar_one_or_none()
        if not existing_group:
            new_group = EmergencyCodeGroup(
                code=g_data["code"],
                name=g_data["name"],
                color_hex=g_data["color_hex"],
                badge_color=g_data["badge_color"],
                description=g_data["description"],
                call_to_action=g_data["call_to_action"],
                is_active=True,
            )
            # Default assign Nurse & Super Admin to CODE_BLUE and RAPID_RESPONSE
            if g_data["code"] in ["CODE_BLUE", "RAPID_RESPONSE"]:
                if nurse_user and nurse_user not in new_group.members:
                    new_group.members.append(nurse_user)
                if admin_user and admin_user not in new_group.members:
                    new_group.members.append(admin_user)
            elif g_data["code"] in ["CODE_RED", "CODE_YELLOW"]:
                if admin_user and admin_user not in new_group.members:
                    new_group.members.append(admin_user)

            db.add(new_group)
            groups_map[g_data["code"]] = new_group
        else:
            groups_map[g_data["code"]] = existing_group

    await db.commit()
    logger.info("Database initialized with staff, departments, doctors, emergency code groups, and pharmacy stock successfully.")
