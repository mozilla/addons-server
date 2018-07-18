from django.conf import settings


def test_celery_routes_in_queues():
    queues_in_queues = set([q.name for q in settings.CELERY_TASK_QUEUES])

    # check the default queue is defined in CELERY_QUEUES
    assert settings.CELERY_TASK_DEFAULT_QUEUE in queues_in_queues

    # then remove it as it won't be in CELERY_ROUTES
    queues_in_queues.remove(settings.CELERY_TASK_DEFAULT_QUEUE)

    queues_in_routes = set(
        [c['queue'] for c in settings.CELERY_TASK_ROUTES.values()]
    )
    assert queues_in_queues == queues_in_routes
