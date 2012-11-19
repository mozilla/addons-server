import json
from optparse import make_option

from django.conf import settings
from django.core.management.base import BaseCommand

import amo
from amo.helpers import absolutify
from amo.utils import send_mail
from addons.models import Addon

subj = "Important information regarding your app on the Firefox Marketplace"

msg = """Hello,

On November 15 Mozilla changed the name of the Mozilla Marketplace to
Firefox Marketplace. We changed the name so we can more quickly build
a Marketplace audience by using the highly recognizable and trusted Firefox
brand.

You're receiving this email because one or more of your apps in the
Firefox Marketplace include "marketplace.mozilla.org" in the
installs_allowed_from directive in the manifest.  With the
transition to the new domain your apps will no longer install from the
marketplace until you change the domain in your manifest.

You should change your app's manifest by replacing "marketplace.mozilla.org" with
"marketplace.firefox.com" in the installs_allowed_from directive.  You do not
need to resubmit your manifest to the Firefox Marketplace after making this
change.

If you have any questions, please visit MDN at
https://developer.mozilla.org/en-US/docs/Apps/Manifest

Firefox Marketplace Team."""


class Command(BaseCommand):
    option_list = BaseCommand.option_list + (
        make_option('--mail', action='store_true', default=False,
                    dest='mail', help='Actually send the email'),
    )

    def handle(self, *args, **options):
        actually_mail = options.get('mail')
        if not actually_mail:
            print 'Not sending actual email, pass --mail to email'

        apps = (Addon.objects
                .filter(status__in=[amo.STATUS_PUBLIC, amo.STATUS_PENDING],
                        type=amo.ADDON_WEBAPP, is_packaged=False)
                .no_transforms())
        # Not chunking because I know there are very few of these apps at
        # this time.

        emails = set()
        print 'Found %d apps' % len(apps)
        for app in apps:
            try:
                data = json.load(open(app.get_latest_file().file_path))
            except:
                print 'Failed to read manifest for: %s, skipped.' % app.pk
                continue

            installs = data.get('installs_allowed_from', [])
            if not installs:
                continue

            if u'*' in installs or 'marketplace.firefox.com' in installs:
                continue

            # Unsure we don't send mulitple emails by using a set.
            emails.update(list(app.authors.values_list('email', flat=True)))

        print 'Found %d emails' % len(emails)
        for email in emails:
            if actually_mail:
                send_mail(subj, msg,
                          from_email=settings.NOBODY_EMAIL,
                          recipient_list=[email])
                continue

            print 'Email not sent to: %s' % email
