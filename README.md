# FinCore API

`fincore-api` is the Django REST Framework backend for FinCore. It serves the microfinance MVP APIs for authentication, institutions, clients, savings, loans, accounting, transactions, dashboards, notifications, audit logs, and reports.

## Core routes

- API base path: `/api/v1/`
- Health endpoint: `/api/v1/health/`
- OpenAPI schema: `/api/v1/schema/`
- Swagger UI: `/api/v1/docs/`

Legacy `/api/schema/` and `/api/docs/` routes redirect to the canonical `/api/v1/` paths.

## Local setup

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python manage.py makemigrations
python manage.py migrate
python manage.py runserver
```

Local development does not require a checked-in `.env` file. The default development settings can boot with SQLite, and you can optionally create a local `.env` from `.env.example` when you want to override defaults.

## Docker development

`docker-compose.yml` now provides safe development defaults directly, so it does not depend on a committed `.env` file.

```bash
docker compose up --build
```

## Production checklist

- Set `DJANGO_SETTINGS_MODULE=core.settings.production`.
- Provide a long random `SECRET_KEY`.
- Point `DATABASE_URL` to PostgreSQL.
- Set `ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS`, and `CSRF_TRUSTED_ORIGINS` for the deployed domains.
- Set `DEFAULT_FROM_EMAIL` and the production `EMAIL_BACKEND`.
- Decide whether to enable Cloudinary with `ENABLE_CLOUDINARY=True`; if enabled, set all Cloudinary credentials.
- Run `python manage.py migrate`.
- Run `python manage.py collectstatic --noinput`.
- Run `python manage.py check --deploy --settings=core.settings.production`.
- Confirm `/api/v1/health/` returns HTTP 200 in the deployed environment.
- Ensure `.env`, SQLite files, and other local-only artifacts are not committed.
