.PHONY: setup demo reset-demo migrate

setup:
	docker compose run --rm web python manage.py migrate
	docker compose up -d --build
	docker compose exec -T web python manage.py seed_demo

demo:
	docker compose exec -T web python manage.py migrate
	docker compose exec -T web python manage.py seed_demo

reset-demo:
	docker compose exec -T web python manage.py reset_demo

migrate:
	docker compose exec -T web python manage.py migrate
