#!/usr/bin/env python
import amo
from addons.models import Preview
from translations.models import delete_translation


def run():
    """
    Remove captions from Webapp Previews.
    """

    for prev in Preview.objects.filter(
                addon__type=amo.ADDON_WEBAPP,
                caption__isnull=False).no_transforms().no_cache().iterator():
        delete_translation(prev, 'caption')
