.PHONY: build up down logs migrate test css lint check shell dbshell

COMPOSE = docker compose

build:
	$(COMPOSE) build

up:
	$(COMPOSE) up -d

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f app

migrate:
	$(COMPOSE) run --rm app python manage.py migrate

test:
	$(COMPOSE) run --rm app pytest -q

css:
	$(COMPOSE) run --rm app tailwindcss -c tailwind.config.js -i static/src/input.css -o static/css/app.css --minify

lint:
	$(COMPOSE) run --rm app ruff check apps tests config
	$(COMPOSE) run --rm app ruff format --check apps tests config

check:
	$(COMPOSE) run --rm app python manage.py makemigrations --check --dry-run
	$(COMPOSE) run --rm app python manage.py check
	$(COMPOSE) run --rm app pytest -q

shell:
	$(COMPOSE) run --rm app python manage.py shell

dbshell:
	$(COMPOSE) exec db psql -U $${POSTGRES_USER:-telur} -d $${POSTGRES_DB:-telur_finance}
