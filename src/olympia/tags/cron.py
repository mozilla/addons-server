import cronjobs
from addons.models import Addon
from tags.models import AddonTag, Tag


@cronjobs.register
def tag_jetpacks():
    # A temporary solution for singling out jetpacks on AMO.  See bug 580827
    tags = (
        ('jetpack', {
            '_current_version__files__jetpack_version__isnull': False
        }),
        ('restartless', {
            '_current_version__files__no_restart': True
        })
    )
    qs = Addon.objects.values_list('id', flat=True)

    for tag, q in tags:
        tag = Tag.objects.get(tag_text=tag)
        for addon in set(qs.filter(**q).exclude(tags=tag)):
            AddonTag.objects.create(addon_id=addon, tag=tag)

        d = {}
        for k, v in q.items():
            # Reverse the sense of the argument and use `.filter()`.
            # `.exclude()` does not work as expected here, for some reason.
            d['addon__%s' % k] = not v

        AddonTag.objects.filter(tag=tag).filter(**d).delete()
