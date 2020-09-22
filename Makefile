build:
	docker-compose build

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
	# docker-compose exec web python manage.py loaddata deployments/fixtures/*.yaml
	docker-compose exec web python manage.py loaddata deployments/fixtures/platforms.yaml
	docker-compose exec web python manage.py loaddata deployments/fixtures/Alerts.yaml
	docker-compose exec web python manage.py loaddata deployments/fixtures/datatypes.yaml
	docker-compose exec web python manage.py loaddata deployments/fixtures/deployments.yaml
	docker-compose exec web python manage.py loaddata deployments/fixtures/erddapservers.yaml
	docker-compose exec web python manage.py loaddata deployments/fixtures/ErddapDataset.yaml
	docker-compose exec web python manage.py loaddata deployments/fixtures/programs.yaml
	docker-compose exec web python manage.py loaddata deployments/fixtures/platformattribution.yaml
	docker-compose exec web python manage.py loaddata deployments/fixtures/

user:
	docker-compose exec web python manage.py createsuperuser

shell:
	docker-compose exec web python manage.py shell

test:
	docker-compose exec web pytest --cov=. --cov-config=tox.ini

test-debug:
	docker-compose exec web pytest --cov=. --cov-config=tox.ini -v --pdb

coverage:
	docker-compose exec web coverage run --source='.' manage.py test
	docker-compose exec web coverage report
	docker-compose exec web coverage html
	open app/htmlcov/index.html

fixtures:
	docker-compose exec web python manage.py dumpdata --natural-primary --natural-foreign --format yaml deployments.Program -o deployments/fixtures/programs.yaml
	docker-compose exec web python manage.py dumpdata --natural-primary --natural-foreign --format yaml deployments.Platform -o deployments/fixtures/platforms.yaml
	docker-compose exec web python manage.py dumpdata --natural-primary --natural-foreign --format yaml deployments.ProgramAttribution -o deployments/fixtures/platformattribution.yaml
	docker-compose exec web python manage.py dumpdata --natural-primary --natural-foreign --format yaml deployments.Deployment -o deployments/fixtures/deployments.yaml
	docker-compose exec web python manage.py dumpdata --natural-primary --natural-foreign --format yaml deployments.DataType -o deployments/fixtures/datatypes.yaml
	docker-compose exec web python manage.py dumpdata --natural-primary --natural-foreign --format yaml deployments.ErddapServer -o deployments/fixtures/erddapservers.yaml
	docker-compose exec web python manage.py dumpdata --natural-primary --natural-foreign --format yaml deployments.TimeSeries -o deployments/fixtures/TimeSeries.yaml
	docker-compose exec web python manage.py dumpdata --natural-primary --natural-foreign --format yaml deployments.ErddapDataset -o deployments/fixtures/ErddapDataset.yaml
	docker-compose exec web python manage.py dumpdata --natural-primary --natural-foreign --format yaml deployments.Alert -o deployments/fixtures/Alerts.yaml

lint:
	docker-compose exec web prospector
