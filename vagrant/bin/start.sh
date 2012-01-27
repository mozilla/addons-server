#!/bin/bash
# This mostly exists until this bug gets fixed:
# https://github.com/mitchellh/vagrant/issues/516
echo "Running ./project/vagrant/bin/start.sh"
cd ~/project
echo 'Checking for DB migrations...'
python ./vendor/src/schematic/schematic migrations/
if [ $? -eq 0 ]; then
    echo 'Starting the server...'
    python manage.py runserver 0.0.0.0:8000
fi
