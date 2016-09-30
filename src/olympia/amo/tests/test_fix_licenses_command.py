import pytest

from django.core.management import call_command
from django.utils import translation

from olympia.amo.log import CHANGE_LICENSE
from olympia.amo.tests import addon_factory, version_factory
from olympia.devhub.models import ActivityLog
from olympia.versions.models import License
from olympia.translations.models import Translation


@pytest.mark.django_db
def test_fix_licenses():
    """What happened on our production system:

    * Mozilla MPL 1.1 got degraded to a "custom license"
    * `builtin` and `on_form` got set to 0 and `False` respectively

    This lead to the fact that about 9k add-ons had a custom license
    which they were able to rename and change which meant in return
    that one add-on developer could change the name of the license for
    all those add-ons because the actual translation instances were still
    the same.
    """
    a1 = addon_factory(name='addon 1')
    a2 = addon_factory(name='addon 2')
    still_mpl = addon_factory(name='this addon still has the mpl')

    original_mpl11 = License(
        # we actively filter by pk=5 in our script
        pk=5,
        on_form=False, builtin=License.OTHER,
        name={
            'en-us': 'some english text',
            'fr': 'some french text',
            'de': 'some german text',
            'ru': 'correct mpl 1.1'
        }
    )
    original_mpl11.save()

    for addon in (a1, a2, still_mpl):
        for version in addon.versions.all():
            version.license = original_mpl11
            version.save()

    a1_v1 = version_factory(addon=a1, license=original_mpl11)
    a1_v2 = version_factory(addon=a1, license=original_mpl11)
    a2_v1 = version_factory(addon=a2, license=original_mpl11)
    a2_v2 = version_factory(addon=a2, license=original_mpl11)
    still_mpl_v1 = version_factory(addon=still_mpl, license=original_mpl11)
    still_mpl_v2 = version_factory(addon=still_mpl, license=original_mpl11)

    english_license_name = Translation.objects.get(
        locale='en-us', id=original_mpl11.name.id)
    english_license_name.localized_string = 'Copyright Jason Savard'
    english_license_name.localized_string_clean = 'Copyright Jason Savard'
    english_license_name.save()

    french_license_name = Translation.objects.get(
        locale='fr', id=original_mpl11.name.id)
    french_license_name.localized_string = 'FR Copyright Jason Savard'
    french_license_name.localized_string_clean = 'FR Copyright Jason Savard'
    french_license_name.save()

    # Let's create the ActivityLog entries that we use to filter broken add-ons
    # and fix 'em
    for addon in (a1, a2):
        arguments = (
            '[{{"versions.license": 5}}, {{"addons.addon": {}}}]'
            .format(addon.pk))

        ActivityLog.objects.create(
            action=CHANGE_LICENSE.id,
            _arguments=arguments)

    # Tadaaa, we changed the version name of addon-1 indirectly...
    assert str(a1.get_version().license.name) == 'Copyright Jason Savard'
    assert str(a2.get_version().license.name) == 'Copyright Jason Savard'
    assert (
        str(still_mpl.get_version().license.name) == 'Copyright Jason Savard')

    a1_v1.license.name.refresh_from_db()
    a1_v2.license.name.refresh_from_db()
    a2_v1.license.name.refresh_from_db()
    a2_v2.license.name.refresh_from_db()

    assert str(a1_v1.license.name) == 'Copyright Jason Savard'
    assert str(a1_v2.license.name) == 'Copyright Jason Savard'
    assert str(a2_v1.license.name) == 'Copyright Jason Savard'
    assert str(a2_v2.license.name) == 'Copyright Jason Savard'

    # Now, let's fix this mess.
    with translation.override('en-us'):
        call_command('fix_licenses')

    for locale in ('en-us', 'fr', 'de'):
        name = Translation.objects.get(
            id=original_mpl11.name.id, locale=locale)
        assert name.localized_string == 'Mozilla Public License Version 1.1'

    # We didn't touch anything but de, fr and en-us
    name = Translation.objects.get(id=original_mpl11.name.id, locale='ru')
    assert name.localized_string == 'correct mpl 1.1'

    # They were both changed (in the activity log),
    # they both have the original translations
    assert str(a1.get_version().license.name) == 'Copyright Jason Savard'
    assert str(a2.get_version().license.name) == 'Copyright Jason Savard'

    with translation.override('de'):
        assert str(a1.get_version().license.name) == 'some german text'
        assert str(a2.get_version().license.name) == 'some german text'

    with translation.override('fr'):
        assert (
            str(a1.get_version().license.name) == 'FR Copyright Jason Savard')
        assert (
            str(a2.get_version().license.name) == 'FR Copyright Jason Savard')

    # But we copied them to a new license object
    assert a2.get_version().license.pk != a1.get_version().license.pk

    # And made sure the translation instance is different
    assert a2.get_version().license.name.pk != a1.get_version().license.name.pk
    assert a2.get_version().license.name.id != a1.get_version().license.name.id
    assert (
        a2.get_version().license.name.autoid !=
        a1.get_version().license.name.autoid)

    # But all other add-ons still refer to the original mpl 1.1 instance
    # but we changed it to not be on_form *but* to be a builtin one
    # so that it cannot be changed anymore.
    assert still_mpl.get_version().license == original_mpl11
    assert still_mpl.get_version().license.on_form is False
    assert still_mpl.get_version().license.builtin == 1

    # And it has the correct name
    actual_license = still_mpl.get_version().license
    actual_license.name.refresh_from_db()
    assert actual_license.name == 'Mozilla Public License Version 1.1'
    assert still_mpl_v1.license == original_mpl11
    assert still_mpl_v2.license == original_mpl11

    # Check we are changing only the correct versions.
    a1_v1.license.name.refresh_from_db()
    a1_v2.license.name.refresh_from_db()
    a2_v1.license.name.refresh_from_db()
    a2_v2.license.name.refresh_from_db()
    still_mpl_v1.license.name.refresh_from_db()
    still_mpl_v2.license.name.refresh_from_db()

    # All versions that are not the current public one (addon.get_version())
    # are changed back to the original MPL 1.1
    assert still_mpl_v1.license.name == 'Mozilla Public License Version 1.1'
    assert still_mpl_v2.license.name == 'Mozilla Public License Version 1.1'
    assert a1_v1.license.name == 'Mozilla Public License Version 1.1'
    assert a1_v2.license.name == 'Mozilla Public License Version 1.1'
    assert a2_v1.license.name == 'Mozilla Public License Version 1.1'
    assert a2_v2.license.name == 'Mozilla Public License Version 1.1'
