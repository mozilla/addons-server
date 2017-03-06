"""Deleting add-ons is in fact soft deleting them, and emptying some of its
fields with a unique constraint (like the slug).
We now also empty the GUID field, to allow re-submitting those add-ons (once
the GUID has been removed from the BlacklistedGuid through the admin.

This migration empties all the previously soft deleted add-ons.

Now we don't clear the GUID so this migration is unneeded."""

# from django.conf import settings
#
# import amo
# from addons.models import Addon
# from users.models import UserProfile
#
#
# addons = Addon.unfiltered.no_cache().filter(status=amo.STATUS_DELETED,
#                                             guid__isnull=False)
# user = UserProfile.objects.get(pk=settings.TASK_USER_ID)
# core.set_user(user)
# for addon in addons:
#     amo.log(amo.LOG.DELETE_ADDON, addon.pk, addon.guid, addon,
#             created=addon.modified)
#     addon.guid = None
#     addon.save()
