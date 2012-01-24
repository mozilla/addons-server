#!/bin/bash
# This is a stupid script to run when you start vagrant
# until this bug gets fixed: https://github.com/mitchellh/vagrant/issues/516
cd ~/project
echo 'Checking for DB migrations...'
python ./vendor/src/schematic/schematic migrations/
if [ $? -eq 0 ]; then
    echo 'Starting the server...'
    python manage.py runserver 0.0.0.0:8000
fi
