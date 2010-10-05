from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import translation

from licenses import license_text
from tower import ugettext, activate


class Command(BaseCommand):
    help = "Upgrade the license schema to support zamboni"

    def handle(self, *args, **kw):
        from versions.models import License
        qs = License.objects.all()
        print 'Updating %s licenses.' % len(qs)
        for idx, license in enumerate(qs):
            if idx % 100 == 0:
                print 'Finished', idx
            if license.builtin:
                self.handle_builtin(license)
            elif not license.name:
                license.name = 'Custom License'
                license.save()

    def handle_builtin(self, license):
        import amo
        # License.builtin is off by one!
        data = amo.LICENSE_IDS[license.builtin - 1]
        license.url = data.url
        license.on_form = data.on_form
        if data.icons:
            license.icons = ' '.join(data.icons)
        license.some_rights = bool(data.linktext)

        if data.shortname:
            license.text = license_text(data.shortname)

        # Gather all the translated names.
        activate('en-us')
        license.name = en_name = unicode(data.name)
        names = {}
        for lang in settings.AMO_LANGUAGES:
            activate(lang)
            trans = ugettext(en_name)
            if trans and trans != en_name:
                names[lang] = trans
        activate('en-us')
        license.name = names
        license.save()
