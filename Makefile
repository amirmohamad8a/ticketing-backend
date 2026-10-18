.PHONY: demo reset-demo migrate

demo:
	docker compose exec -T web python manage.py migrate
	docker compose exec -T web python manage.py seed_demo

reset-demo:
	docker compose exec -T web python manage.py reset_demo

migrate:
	docker compose exec -T web python manage.py migrate
