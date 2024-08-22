"""
Celery endpoint for addons-server.

It exposes the celery worker as a callable python module.

"""

from olympia.amo.celery import app

# This is referenced in docker/uwsgi-celery.ini: module = olympia.celery:application
# This is how uwsgi knows how to start the celery worker
application = app.Worker(loglevel='INFO', concurrency=2, task_events=True).start
