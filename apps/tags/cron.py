import commonware.log
from celery.messaging import establish_connection
from celeryutils import task

from amo.utils import chunked
from addons.models import Addon
import cronjobs
from tags.models import AddonTag, Tag
from users.models import UserProfile

task_log = commonware.log.getLogger('z.task')


@cronjobs.register
def tag_jetpacks():
    # A temporary solution for singling out jetpacks on AMO.  See bug 580827

    addons = (Addon.objects.distinct()
              .filter(versions__files__jetpack=True)
              .exclude(tags__tag_text__exact="jetpack"))

    with establish_connection() as conn:
        for chunk in chunked(addons, 30):
            _tag_jetpacks.apply_async(args=[chunk], connection=conn)


@task(rate_limit='60/m')
def _tag_jetpacks(data, **kw):
    task_log.info("[%s@%s] Adding Jetpack tag to add-ons" %
                   (len(data), _tag_jetpacks.rate_limit))

    # The "Mozilla" user
    user = UserProfile.objects.get(pk=4757633)

    # The "Jetpack" tag
    tag = Tag.objects.get(pk=7758)

    for addon in data:
        AddonTag(addon=addon, tag=tag, user=user).save()
