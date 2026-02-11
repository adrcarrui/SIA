# 🎓 TAMS -- Training Assets Management System

TAMS is an internal web-based system designed to manage training assets
across TCO and ITC departments.\
It provides full traceability, role-based access control, and
operational visibility over NFC cards, devices, and course assignments.

------------------------------------------------------------------------

## 🧠 Overview

TAMS enables:

-   User management (TCO / ITC staff)
-   NFC card management
-   Device management (RFID / Barcode capable)
-   Course management
-   Active assignments tracking
-   Automated alert system
-   Full movement auditing
-   Department-based visibility

------------------------------------------------------------------------

## 🏗 Architecture

**Technology Stack:**

-   Backend: Python + Flask\
-   ORM: SQLAlchemy\
-   Database: PostgreSQL\
-   Frontend: Jinja2 + Bootstrap\
-   Authentication: NFC (ACR122U)\
-   Local service: NFC Agent (Windows)

------------------------------------------------------------------------

## 👥 Roles

-   Admin\
-   Supervisor TCO\
-   Supervisor ITC\
-   Employee

Permissions and visibility depend on role and department.

------------------------------------------------------------------------

## 📦 Core Modules

### 👤 Users

-   NFC card association
-   Role & department control
-   Active / inactive status

### 💳 Cards

-   UID (NFC)
-   Internal card number
-   Card type (vending, instructor, guest, etc.)
-   Status (available, assigned, lost, annulled)

### 💻 Devices

-   Root type & subtype hierarchy
-   RFID / Barcode support
-   Status tracking
-   Advanced filtering and export (CSV, Excel, PDF)

### 📚 Courses

-   Course code
-   Client
-   Instructor / trainee
-   Start & end dates
-   TCO and ITC statuses
-   Asset requirements

### 🔄 Assignments

Live table representing currently assigned assets. Statuses: - Active -
Overdue_1 - Overdue_2

### 🚨 Alerts System

Automated alerts based on: - Missing cards - Asset mismatches - Overdue
devices - ITC pickups - Escalation logic

Each alert includes: - Severity (notice / warning / critical) - Status
(open / ack / snooze / done)

### 🧾 Movements (Audit Log)

Every relevant action is logged: - Create - Update - Delete - Assign -
Return - Login / Logout

Includes before/after data, user reference, and user agent.

------------------------------------------------------------------------

## 🔐 NFC Authentication Flow

1.  User scans NFC card.
2.  UID is validated.
3.  Session is created.
4.  All subsequent actions are tracked.

------------------------------------------------------------------------

## 🗄 Database

-   PostgreSQL
-   Strong referential integrity
-   Persistent audit log
-   State-driven logic

------------------------------------------------------------------------

## 🧪 Setup Instructions

### 1️⃣ Create virtual environment

python -m venv .venv

Activate:

Windows (PowerShell): .venv`\Scripts`{=tex}`\Activate`{=tex}

### 2️⃣ Install dependencies

pip install -r requirements.txt

### 3️⃣ Configure database connection

\$env:DATABASE_URL="postgresql://postgres:password@127.0.0.1:5432/tams"

### 4️⃣ Run application

flask run

Access at: http://127.0.0.1:5000

------------------------------------------------------------------------

## 🎯 System Goals

-   Reduce asset loss
-   Improve cross-department coordination
-   Provide operational transparency
-   Automate alerting logic
-   Maintain full action traceability

------------------------------------------------------------------------

## 👤 Author

Adrian Cardona\
Training & Simulation Asset Management
