import itertools
import logging

from django.core import mail
from django.conf import settings
from django.core.management.base import BaseCommand

import amo
from addons.models import Addon, AddonUser

log = logging.getLogger('z.mailer')
FROM = settings.DEFAULT_FROM_EMAIL


class Command(BaseCommand):
    args = '[listed|unreviewed] [no really]'
    help = "Send the email for bug 612050, but only with the args 'no really'"

    def handle(self, *args, **options):
        groups = {'listed': LISTED, 'unreviewed': UNREVIEWED}
        assert args and args[0] in groups
        backend = None
        if ' '.join(args[1:]) != 'no really':
            backend = 'django.core.mail.backends.console.EmailBackend'
        log.info('Using email backend: %r' % (backend or 'default'))
        cxn = mail.get_connection(backend=backend)
        sendmail(groups[args[0]], cxn)


def sendmail(cfg, cxn):
    from amo.utils import chunked
    counter = itertools.count()
    qs = (AddonUser.objects.filter(addon__status=cfg['status'],
                                   addon__disabled_by_user=False,
                                   user__email__isnull=False)
          .order_by('user').values_list('user__email', 'addon'))
    qs = [(user, [addon for user, addon in vals])
          for user, vals in itertools.groupby(qs, lambda x: x[0])]
    log.info('There are %d emails to send.' % len(qs))
    for chunk in chunked(qs, 100):
        send_to_addons(chunk, cfg, cxn, counter)


def send_to_addons(chunk, cfg, cxn, counter):
    ids = set(addon for _, addons in chunk for addon in addons)
    qs = (Addon.objects.filter(id__in=ids).no_cache()
          .only_translations())
    addon_dict = dict((a.id, a) for a in qs)
    for user, ids in chunk:
        user_addons = [addon_dict[id] for id in ids]
        try:
            addon = 'add-on' if len(ids) == 1 else 'add-ons'
            addons = '\n'.join(cfg['addons'].format(addon=a)
                                 for a in user_addons)
            msg = cfg['message'].format(addon=addon, addons=addons)
            subject = cfg['subject'].format(addon=addon)
            mail.send_mail(subject, msg, FROM, [user], connection=cxn)
            log.info('%s. DONE: %s' % (counter.next(), user))
        except Exception, e:
            log.info('%s. FAIL: %s (%s)' % (counter.next(), user, e))


LISTED = {
    'status': amo.STATUS_LISTED,
    'subject': 'Important information about self-hosted add-ons',
    'addons': '* {addon.name} - https://addons.mozilla.org/developers/addon/status/{addon.id}',
    'message': """\
As announced in October, support for self-hosted add-ons in the Mozilla Add-ons
Gallery (addons.mozilla.org) will be discontinued in the coming weeks. We will
soon be requiring that all add-ons listed in our gallery be reviewed by an
editor, so self-hosted add-ons no longer fit with the security policies we'll
have in place.

You can read more about this change in our announcement post:
http://blog.mozilla.com/addons/2010/10/06/discontinuing-several-features-of-amo/

If you wish for your {addon} to stay on addons.mozilla.org, please convert it to
fully-hosted no later than December 24. Once our new Developer Tools
launch, support for managing self-hosted add-ons will be removed and any
remaining self-hosted add-ons will be disabled.

You can convert your {addon} to fully-hosted from its status page:

{addons}

Thanks for participating in our self-hosted add-ons pilot, and we hope you'll
choose to host your {addon} in our gallery.

If you have any questions, please email amo-admins@mozilla.org.

Mozilla Add-ons Team
https://addons.mozilla.org""",
}

UNREVIEWED = {
    'status': amo.STATUS_PURGATORY,
    'addons': '* {addon.name} - https://addons.mozilla.org/developers/addon/{addon.id}/versions',
    'subject': 'Important information about your {addon}',
    'message': """\
* Action is required if you wish for Mozilla to continue hosting your {addon}. *

As part of Mozilla's commitment to ensuring that all add-ons hosted in our
gallery are safe for users to install, earlier this year we determined that we
could no longer allow add-ons to remain unreviewed indefinitely, as the sandbox
review process currently allows.

We proposed several different methods of increasing the security of the gallery
while still allowing add-on developers to host experimental add-ons, and after
extensive discussion with developers on our blog and forums, we selected the
new review process in May.

New Review Process
---
All add-ons in our gallery must now be reviewed by an editor. There are two
types of reviews:

1. Full review. This is the same review process that we have had in place for
   years, and involves an editor installing your add-on to check for bugs and
   policy compliance, as well as a source code review. We aim to complete these
   reviews in under 10 days, though currently these reviews are completed in
   under 5 days for both new add-ons and updates.

2. Preliminary review. This is a much lighter review and will involve the
   editor reviewing the source code for malicious code and security problems,
   but without checking for 100% policy compliance or testing the add-on
   thoroughly.  Add-ons that undergo preliminary review will have cautions
   placed on their install buttons and have a slight penalty in search results.
   Certain features will also be unavailable to these add-ons, such as beta
   channels and contributions. However, these add-ons will receive automatic
   updates and be listed everywhere on the site, both of which are not
   currently available to add-ons in the sandbox.

   Preliminary review is intended for experimental add-ons hoping to gather
   feedback before being marked ready for prime-time. We aim to complete these
   reviews in under 3 days, but hope they will be completed in even less than
   than that.

For new add-ons, developers will select which review process they'd like, and
existing "public" add-ons will automatically be marked as fully reviewed.

Action Required
---
You are receiving this email because you have at least one add-on currently in
the sandbox that has not been reviewed by an editor. As we will now require
all add-ons to be reviewed, you must select which review process you wish
your {addon} to undergo. Add-ons that have not selected a review process
before February 1, 2011 will be disabled.

You can select a review process from the status page for your {addon}:

{addons}

To read more about the review process, visit our review policy page:
https://addons.mozilla.org/developers/docs/policies/reviews#selection

Thank you for your attention to this matter, and we hope you'll choose to
continue hosting your {addon} in our gallery. If you have any questions, please
email amo-admins@mozilla.org.

Mozilla Add-ons Team
https://addons.mozilla.org""",
}
