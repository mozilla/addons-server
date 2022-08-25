from datetime import datetime

from django.db.models import Q

from olympia.amo.management import ProcessObjectsCommand
from olympia.users.models import UserProfile
from olympia.users.tasks import (
    backfill_activity_and_iplog,
)


class Command(ProcessObjectsCommand):
    def get_model(self):
        return UserProfile

    def get_tasks(self):
        return {
            # Don't forget to use the --with_deleted argument when triggering
            # this task!
            'backfill_activity_and_iplog': {
                'task': backfill_activity_and_iplog,
                'queryset_filters': [
                    ~Q(last_login_ip='') & Q(last_login__gte=datetime(2019, 1, 1))
                ],
            },
        }
