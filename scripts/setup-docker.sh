#!/bin/bash -x

# Update deps to avoid missing dependencies
# from the UI tests when a PR adds new dependency
# that isn't yet built into the container.
make update_deps

# initialize_db:
python manage.py reset_db --noinput
python manage.py syncdb --noinput
python manage.py loaddata initial.json
python manage.py import_prod_versions
schematic --fake src/olympia/migrations/
#python manage.py createsuperuser
#python manage.py loaddata zadmin/users

# update_assets:
make update_assets

#populate_data:
make populate_data
