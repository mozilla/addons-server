import random

from django.contrib.auth.models import User as DjangoUser
from django.db import IntegrityError

import commonware.log
from celery.decorators import task

from . import cron
from amo.utils import slugify
from users.models import UserProfile

task_log = commonware.log.getLogger('z.task')


@task(rate_limit='20/m')
def add_usernames(data, **kw):
    """Temporary method.  Roll me back in 5.11.9.  See bug 582727."""

    task_log.info("[%s@%s] Bulk touching users" %
                   (len(data), add_usernames.rate_limit))

    def old_display_name(user):
        if not user[3]:
            return u'%s %s' % (user[1], user[2])
        else:
            return user[3]

    for user in data:
        name = old_display_name(user)
        name_slug = slugify(name)
        try:
            UserProfile.objects.filter(id=user[0]).update(username=name_slug,
                                                          display_name=name)
        except IntegrityError, e:
            try:
                name_slug = "%s%s" % (name_slug, user[0])
                if not len(name_slug) > 10:
                    # This can happen if they have a blank name_slug and then
                    # there is already a username in the system that corresponds
                    # to their user id.  It's a total edge case.
                    name_slug = "%s%s" % (random.randint(1000,100000),
                                          name_slug)

                UserProfile.objects.filter(id=user[0]).update(username=name_slug,
                                                              display_name=name)
            except IntegrityError, e:
                task_log.error(u"""F-F-Fail!  I tried setting a user's (id:%s)
                username to to %s and it was already taken.  This should never
                happen.""" % (user[0], name_slug))


@task(rate_limit='40/m')
def _delete_users(data, **kw):
    """Feed me a list of user ids you want to delete from the database.  This
    isn't a flag, it actually deletes rows."""

    task_log.info("[%s@%s] Bulk deleting users" %
                   (len(data), _delete_users.rate_limit))

    UserProfile.objects.filter(pk__in=data).delete()
    DjangoUser.objects.filter(pk__in=data).delete()
