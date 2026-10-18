.PHONY: setup migrate backend frontend test test-backend test-e2e lint build

setup:
	python3 -m venv backend/.venv
	backend/.venv/bin/python -m pip install --upgrade pip
	backend/.venv/bin/pip install -r backend/requirements.txt
	npm --prefix frontend-react ci
	cd frontend-react && npx playwright install chrome
	@if [ ! -f backend/.env ]; then cp backend/.env.example backend/.env; fi

migrate:
	cd backend && .venv/bin/python manage.py migrate

backend:
	cd backend && .venv/bin/python manage.py runserver 0.0.0.0:8000

frontend:
	cd frontend-react && npm run dev -- --host 0.0.0.0

test: test-backend test-e2e

test-backend:
	cd backend && .venv/bin/python manage.py test --keepdb --verbosity 1

test-e2e:
	cd frontend-react && npm run test:e2e

lint:
	cd backend && .venv/bin/pyflakes users/
	cd frontend-react && npm run lint

build:
	cd frontend-react && npm run build
