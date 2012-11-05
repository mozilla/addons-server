#!/bin/bash
# This mostly exists until this bug gets fixed:
# https://github.com/mitchellh/vagrant/issues/516
echo "Running ./project/vagrant/bin/start.sh"
cd ~/project
echo "Seeding product details JSON..."
./scripts/seed-prod-details.sh
echo "Checking for DB migrations..."
python schematic migrations/
if [ $? -eq 0 ]; then
    echo "Running python manage.py runserver 0.0.0.0:8000"
    python manage.py runserver 0.0.0.0:8000
fi
