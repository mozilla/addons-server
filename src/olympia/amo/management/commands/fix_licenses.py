from django.core.management.base import BaseCommand
from django.utils.translation import activate
from django.db.models import Max

from olympia.amo.log import CHANGE_LICENSE
from olympia.versions.models import License
from olympia.addons.models import Addon
from olympia.devhub.models import ActivityLog
from olympia.translations.models import Translation


class Command(BaseCommand):
    def handle(self, *args, **kwargs):
        activate('en-us')

        mpl11 = License.objects.get(pk=5)

        msg = 'wrong license, got %s' % str(mpl11.name)
        assert str(mpl11.name) == 'Copyright Jason Savard', msg
        assert not mpl11.text

        # set on_form explicitly to False to make sure it's not
        # visible and set `builtin` not to `OTHER` to make sure it's filtered
        # everywhere.
        max_builtin = License.objects.aggregate(
            max_builtin=Max('builtin'))['max_builtin']
        mpl11.on_form = False
        mpl11.builtin = max_builtin + 1
        mpl11.save()

        search = '"versions.license": 5}'
        changed_addons = ActivityLog.objects.filter(
            action=CHANGE_LICENSE.id,
            _arguments__contains=search)

        for log in changed_addons:
            license, addon = log.arguments

            assert isinstance(license, License)
            assert isinstance(addon, Addon)

            last_version = addon.get_version()

            assert license == last_version.license

            name_values_qset = (
                Translation.objects
                .filter(id=last_version.license.name.id)
                .values_list('locale', 'localized_string'))

            name_values = {locale: value for locale, value in name_values_qset}

            # Create new object of broken license since they were supposed
            # to change and show them in the list again
            new_name_trans = Translation.new(name_values['en-us'], 'en-us')
            new_name_trans.save()

            for locale, name in name_values.items():
                obj = Translation.new(name, locale, id=new_name_trans.id)
                obj.save()

            assert new_name_trans.id != mpl11.name.id

            license = last_version.license

            license.pk = None
            license.on_form = False
            license.builtin = License.OTHER
            license.name = new_name_trans
            license.save(force_insert=True)

            last_version.license = license
            last_version.save(update_fields=('license',))

            last_version = addon.get_version()
            assert last_version.license.name.id == new_name_trans.id

        # Now we're able to fix the actual strings.
        # Broken are: de, en-us, and fr. We untangled those three above
        # already.
        translations = Translation.objects.filter(
            id=mpl11.name.id,
            locale__in=('en-us', 'fr', 'de'))

        mpl11_name = 'Mozilla Public License Version 1.1'

        for translation in translations:
            translation.localized_string = mpl11_name
            translation.localized_string_clean = mpl11_name
            translation.save(
                update_fields=('localized_string', 'localized_string_clean'))
