build:
	docker-compose build --parallel

up: down build
	# docker-compose up -d --build
	docker-compose up -d
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

load:
	docker-compose exec web python manage.py loaddata deployments/fixtures/*.yaml

user:
	docker-compose exec web python manage.py createsuperuser

shell:
	docker-compose exec web python manage.py shell

test:
	docker-compose exec web python manage.py test -v 2

coverage:
	docker-compose exec web coverage run --source='.' manage.py test
	docker-compose exec web coverage report
	docker-compose exec web coverage html
	open app/htmlcov/index.html

requirements-compile:
	docker-compose exec web pip-compile requirements.in

requirements-tree:
	docker-compose exec web pipdeptree

fixtures:
	docker-compose exec web python manage.py dumpdata --format yaml deployments.Program -o deployments/fixtures/programs.yaml
	docker-compose exec web python manage.py dumpdata --format yaml deployments.Platform -o deployments/fixtures/platforms.yaml
	docker-compose exec web python manage.py dumpdata --format yaml deployments.ProgramAttribution -o deployments/fixtures/platformattribution.yaml
	docker-compose exec web python manage.py dumpdata --format yaml deployments.Deployment -o deployments/fixtures/deployments.yaml
	docker-compose exec web python manage.py dumpdata --format yaml deployments.DataType -o deployments/fixtures/datatypes.yaml
	docker-compose exec web python manage.py dumpdata --format yaml deployments.ErddapServer -o deployments/fixtures/erddapservers.yaml
	docker-compose exec web python manage.py dumpdata --format yaml deployments.TimeSeries -o deployments/fixtures/TimeSeries.yaml
	docker-compose exec web python manage.py dumpdata --format yaml deployments.Alert -o deployments/fixtures/Alerts.yaml

lint:
	docker-compose exec web prospector
