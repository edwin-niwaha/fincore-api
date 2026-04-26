# FinCore Platform

FinCore is a production-oriented MVP for microfinance and accounting operations. It includes:

- `fincore-api` — Django + Django REST Framework backend
- `fincore-web` — Next.js + TypeScript internal dashboard

The platform supports admin, staff, and client-facing workflows such as client onboarding, savings, loans, accounting, reports, dashboards, audit logs, and self-service APIs.

---

# FinCore API

`fincore-api` is the backend service for FinCore. It provides secure REST APIs for authentication, microfinance operations, accounting, dashboards, and reporting.

## Core Features

- JWT authentication
- Role-based access control
- Institutions and branches
- Client onboarding and KYC
- Savings accounts
- Deposits and withdrawals
- Account statements
- Loan products
- Loan applications
- Loan approvals and rejections
- Loan disbursements
- Repayment schedules
- Loan repayments
- Double-entry accounting foundation
- Chart of accounts
- Journal entries
- Ledger foundation
- Transactions
- Notifications
- Audit logs
- Admin/staff dashboards
- Reports
- OpenAPI/Swagger documentation

---

## API Setup

```bash
git clone https://github.com/your-org/fincore-api.git
cd fincore-api

python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

pip install -r requirements.txt

cp .env.example .env

python manage.py makemigrations
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver