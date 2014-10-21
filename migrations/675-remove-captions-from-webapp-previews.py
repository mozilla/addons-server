#!/usr/bin/env python


def run():
    """
    Remove captions from Webapp Previews.
    """
    # This should be done in a separate script, it's taking too long to be
    # a migration, and it doesn't need to be done as soon as we have deployed,
    # it can be done later.
    pass
    # for prev in Preview.objects.filter(
    #             addon__type=amo.ADDON_WEBAPP,
    #             caption__isnull=False).no_transforms().no_cache().iterator():
    #     delete_translation(prev, 'caption')
