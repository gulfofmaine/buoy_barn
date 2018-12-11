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

dump:
	docker-compose exec web python manage.py dumpdata deployments.Program deployments.Platform deployments.ProgramAttribution deployments.Deployment deployments.ErddapServer deployments.TimeSeries -o dump.json

load:
	docker-compose exec web python manage.py loaddata dump.json

user:
	docker-compose exec web python manage.py createsuperuser

shell:
	docker-compose exec web python manage.py shell
