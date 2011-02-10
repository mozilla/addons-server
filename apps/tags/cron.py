from django.db.models import Q

import commonware.log

from addons.models import Addon
import cronjobs
from tags.models import AddonTag, Tag

task_log = commonware.log.getLogger('z.task')


@cronjobs.register
def tag_jetpacks():
    # A temporary solution for singling out jetpacks on AMO.  See bug 580827
    tags = (('jetpack', Q(versions__files__jetpack=True)),
            ('restartless', Q(versions__files__no_restart=True)))
    qs = Addon.objects.values_list('id', flat=True)

    for tag, q in tags:
        tag_id = Tag.objects.get(tag_text=tag).id
        for addon in set(qs.filter(q).exclude(tags__id=tag_id)):
            AddonTag.objects.create(addon_id=addon, tag_id=tag_id)
