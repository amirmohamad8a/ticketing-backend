.PHONY: up setup demo reset-demo migrate

up:
	docker compose build
	docker compose up -d

setup:
	sh scripts/bootstrap.sh $(MODE)

demo:
	docker compose exec -T web python manage.py migrate
	docker compose exec -T web python manage.py seed_demo

reset-demo:
	docker compose exec -T web python manage.py reset_demo

migrate:
	docker compose exec -T web python manage.py migrate
