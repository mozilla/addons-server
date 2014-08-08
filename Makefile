.PHONY: help docs test test_force_db tdd test_failed update_code update_submodules update_deps update_db update_assets update_landfill full_update reindex

help:
	@echo "Please use \`make <target>' where <target> is one of"
	@echo "  docs              to builds the docs for Zamboni"
	@echo "  test              to run all the test suite"
	@echo "  test_force_db     to run all the test suite with a new database"
	@echo "  tdd               to run all the test suite, but stop on the first error"
	@echo "  test_failed       to rerun the failed tests from the previous run"
	@echo "  update_code       to update the git repository and submodules"
	@echo "  update_submodules to only update the submodules"
	@echo "  update_deps       to update the python and npm dependencies"
	@echo "  update_db         to run the database migrations"
	@echo "  full_update       to update the code, the dependencies and the database"
	@echo "  update_landfill   to load the landfill database data"
	@echo "  reindex           to reindex everything in elasticsearch, for AMO"
	@echo "Check the Makefile  to know exactly what each target is doing. If you see a "

docs:
	$(MAKE) -C docs html

test:
	python manage.py test --with-blockage --noinput --logging-clear-handlers --with-id -v 2 $(ARGS)

test_force_db:
	FORCE_DB=1 python manage.py test --with-blockage --noinput --logging-clear-handlers --with-id -v 2 $(ARGS)

tdd:
	python manage.py test --with-blockage --noinput --failfast --pdb --with-id -v 2 $(ARGS)

test_failed:
	python manage.py test --with-blockage --noinput --logging-clear-handlers --with-id -v 2 --failed $(ARGS)

update_code:
	git checkout master && git pull
	$(MAKE) update_submodules

update_submodules:
	git submodule --quiet foreach 'git submodule --quiet sync'
	git submodule --quiet sync && git submodule update --init --recursive

update_deps:
	pip install --no-deps --exists-action=w --download-cache=/tmp/pip-cache -r requirements/dev.txt --find-links https://pyrepo.addons.mozilla.org/ --allow-external PIL --allow-unverified PIL
	npm install

update_db:
	schematic migrations

update_assets:
	python manage.py compress_assets
	python manage.py collectstatic --noinput

full_update: update_code update_deps update_db update_assets

update_landfill:
	python manage.py install_landfill $(ARGS)

reindex:
	python manage.py reindex $(ARGS)
