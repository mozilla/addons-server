from celeryutils import task
import commonware.log

from amo.utils import slugify
from tags.models import AddonTag, Tag
from . import cron


task_log = commonware.log.getLogger('z.task')


@task(rate_limit='1000/m')
def clean_tag(pk, **kw):
    task_log.info("[1@%s] Cleaning tag %s" % (clean_tag.rate_limit, pk))

    try:
        # It could be that a previous run of this has deleted our
        # tag, if so we just leave.
        tag = Tag.objects.no_cache().get(pk=pk)
    except Tag.DoesNotExist:
        return

    old = tag.tag_text
    new = slugify(old, spaces=True, lower=True)
    if old != new:
        # Find out if there's any existing tags with this tag.
        existing = (Tag.objects.no_cache().filter(tag_text=new)
                       .select_related()
                       .exclude(pk=tag.pk).order_by("pk"))
        blacklisted = tag.blacklisted
        if existing:
            # Before deleting them, see if any AddonTags need to
            # be moved over.
            for existing_tag in existing:
                for addon_tag in existing_tag.addon_tags.all():
                    if not (AddonTag.objects.no_cache()
                                    .filter(addon=addon_tag.addon, tag=tag)
                                    .exists()):
                        # If there are no tags for this addon, but there is
                        # for an existing and about to be deleted addon tag,
                        # move just one addon tag over.
                        addon_tag.update(tag=tag)
                # If there's a tag in all this that's blacklisted, keep that
                # around.
                if existing_tag.blacklisted:
                    blacklisted = True

            Tag.objects.filter(pk__in=[e.pk for e in existing]).delete()
        tag.update(tag_text=new, blacklisted=blacklisted)
