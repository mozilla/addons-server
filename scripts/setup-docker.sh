#!/bin/bash -x

# initialize_db:
python manage.py reset_db --noinput
python manage.py syncdb --noinput
python manage.py loaddata initial.json
python manage.py import_prod_versions
schematic --fake src/olympia/migrations/

#create Superuser
RANDOM=$(cat /dev/urandom | tr -dc 'a-zA-Z0-9' | fold -w 32 | head -n 1)
python manage.py createsuperuser \
  --username ${RANDOM} \
  --email ${RANDOM}@restmail.net \
  --add-to-supercreate-group \
  --ui-testing \
  --noinput
python manage.py waffle_switch --create super-create-accounts on
#python manage.py loaddata zadmin/users

# update_assets:
make update_assets

#populate_data:
make populate_data
