up: down
	docker-compose up -d --build
	docker-compose logs -f

down:
	docker-compose down

stop:
	docker-compose stop

logs:
	docker-compose logs -f

migrations:
	docker-compose exec web python manage.py makemigrations

migrate:
	docker-compose exec web python manage.py migrate

prune:
	docker volume rm $(shell docker volum ls -qf dangling=true)
	docker system prune -a
