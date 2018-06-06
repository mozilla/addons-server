import logging
import os
import sys
import time

# due to locust sys.path manipulation, we need to re-add the project root.
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'settings')
import olympia  # noqa

from locust import HttpLocust  # noqa

import tasks.user  # noqa
import helpers  # noqa


logging.Formatter.converter = time.gmtime

log = logging.getLogger(__name__)
helpers.install_event_markers()


class WebsiteUser(HttpLocust):
    weight = 1
    task_set = tasks.user.UserTaskSet
    min_wait = 120
    max_wait = 240


# class Developer(HttpLocust):
#     weight = 10
#     task_set = tasks.developer.DeveloperTaskSet
#     min_wait = 120
#     max_wait = 240
