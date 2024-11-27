web: uwsgi --ini /data/olympia/docker/uwsgi.ini
worker: DJANGO_SETTINGS_MODULE=settings watchmedo auto-restart --directory=/data/olympia/src --pattern=*.py --recursive -- celery -A olympia.amo.celery:app worker -E -c 2 --loglevel=INFO
