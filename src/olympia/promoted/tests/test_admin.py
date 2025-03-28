# TODO: Convert to PromotedAddonPromotionAdmin Test
from django.urls import reverse

from olympia import amo
from olympia.amo.reverse import django_reverse
from olympia.amo.tests import (
    PromotedAddonPromotion,
    TestCase,
    addon_factory,
    user_factory,
    version_factory,
)
from olympia.constants.promoted import PROMOTED_GROUP_CHOICES
from olympia.hero.models import PrimaryHero
from olympia.promoted.models import PromotedAddon, PromotedAddonVersion, PromotedGroup


class TestPromotedAddonPromotionAdmin(TestCase):
    def setUp(self):
        self.list_url = reverse('admin:discovery_promotedaddonpromotion_changelist')
        self.detail_url_name = 'admin:discovery_promotedaddonpromotion_change'

    def _get_approval_form(self, item, approvals):
        count = str(len(approvals))
        out = {
            'addon': str(item.addon_id) if item else '',
            'group_id': str(item.group_id) if item else '0',
            'application_id': str(getattr(item, 'application_id', None) or ''),
            'form-TOTAL_FORMS': str(count),
            'form-INITIAL_FORMS': str(count),
            'form-MIN_NUM_FORMS': '0',
            'form-MAX_NUM_FORMS': '0',
        }
        for index in range(0, len(approvals)):
            out.update(
                **{
                    f'form-{index}-id': str(approvals[index].id),
                }
            )
        return out

    def test_can_see_in_admin_with_discovery_edit(self):
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Discovery:Edit')
        self.client.force_login(user)
        url = reverse('admin:index')
        response = self.client.get(url)
        assert response.status_code == 200

        # Use django's reverse, since that's what the admin will use. Using our
        # own would fail the assertion because of the locale that gets added.
        self.list_url = django_reverse(
            'admin:discovery_promotedaddonpromotion_changelist'
        )
        assert self.list_url in response.content.decode('utf-8')

    def test_can_list_with_discovery_edit_permission(self):
        PromotedAddon.objects.create(addon=addon_factory(name='FooBâr'))
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Discovery:Edit')
        self.client.force_login(user)

        with self.assertNumQueries(7):
            # 1. select current user
            # 2. savepoint (because we're in tests)
            # 3. select groups
            # 4. pagination count
            #    (show_full_result_count=False so we avoid the duplicate)
            # 5. prefetch add-ons
            # 6. select translations for add-ons from 7.
            # 7. savepoint (because we're in tests)
            response = self.client.get(self.list_url, follow=True)

        assert response.status_code == 200
        assert 'FooBâr' in response.content.decode('utf-8')

        # double check it scales.
        PromotedAddon.objects.create(addon=addon_factory(name='FooBâr'))
        # throw in a promoted addon that doesn't have a current_version
        unlisted = PromotedAddon.objects.create(
            addon=addon_factory(
                name='FooBâr', version_kw={'channel': amo.CHANNEL_UNLISTED}
            )
        )
        assert not unlisted.addon.current_version
        assert not unlisted.addon._current_version
        with self.assertNumQueries(9):
            self.client.get(self.list_url, follow=True)

    def test_can_edit_with_discovery_edit_permission(self):
        addon = addon_factory()
        item = PromotedAddonPromotion.objects.create(
            addon=addon,
            promoted_group=PromotedGroup.objects.get(
                group_id=PROMOTED_GROUP_CHOICES.RECOMMENDED
            ),
        )
        ver1 = addon.current_version
        ver1.update(version='1.111')
        ver2 = version_factory(addon=addon, version='1.222')
        ver3 = version_factory(addon=addon, version='1.333')
        item.reload()
        assert item.addon.current_version == ver3
        approvals = [
            PromotedAddonVersion.objects.create(
                version=ver1,
                promoted_group=PromotedGroup.objects.get(
                    group_id=PROMOTED_GROUP_CHOICES.RECOMMENDED
                ),
                application_id=amo.FIREFOX.id,
            ),
            PromotedAddonVersion.objects.create(
                version=ver2,
                promoted_group=PromotedGroup.objects.get(
                    group_id=PROMOTED_GROUP_CHOICES.RECOMMENDED
                ),
                application_id=amo.ANDROID.id,
            ),
            PromotedAddonVersion.objects.create(
                version=ver2,
                promoted_group=PromotedGroup.objects.get(
                    group_id=PROMOTED_GROUP_CHOICES.LINE
                ),
                application_id=amo.FIREFOX.id,
            ),
            PromotedAddonVersion.objects.create(
                version=ver3,
                promoted_group=PromotedGroup.objects.get(
                    group_id=PROMOTED_GROUP_CHOICES.RECOMMENDED
                ),
                application_id=amo.FIREFOX.id,
            ),
        ]
        approvals.reverse()  # we order by -version_id so match it.
        item.reload()
        assert item.approved_applications
        detail_url = reverse(self.detail_url_name, args=(item.pk,))
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Discovery:Edit')
        self.client.force_login(user)
        response = self.client.get(detail_url, follow=True)
        assert response.status_code == 200
        content = response.content.decode('utf-8')
        assert '1.111' in content
        assert '1.222' in content
        assert '1.333' in content

        response = self.client.post(
            detail_url,
            dict(
                self._get_approval_form(item, approvals),
                **{
                    'group_id': PROMOTED_GROUP_CHOICES.LINE,  # change the group
                },
            ),
            follow=True,
        )
        assert response.status_code == 200
        assert 'errors' not in response.context_data, response.context_data['errors']
        item.reload()
        assert PromotedAddon.objects.count() == 1
        assert item.group.id == PROMOTED_GROUP_CHOICES.LINE
        assert PromotedAddonVersion.objects.count() == 4  # same
        # now it's not promoted because the current_version isn't approved for
        # LINE group
        assert not item.approved_applications

        # Try to delete one of the approvals
        response = self.client.post(
            detail_url,
            dict(
                self._get_approval_form(item, approvals),
                **{
                    'form-0-DELETE': 'on',  # delete the latest approval
                },
            ),
            follow=True,
        )
        assert response.status_code == 200
        assert 'errors' not in response.context_data, response.context_data['errors']
        assert PromotedAddon.objects.count() == 1
        assert PromotedAddonVersion.objects.count() == 3
        assert PrimaryHero.objects.count() == 0  # check we didn't add

    def test_cannot_add_or_change_approval(self):
        addon = addon_factory()
        item = PromotedAddon.objects.create(
            addon=addon, group_id=PROMOTED_GROUP_CHOICES.RECOMMENDED
        )
        ver1 = addon.current_version
        approval = PromotedAddonVersion.objects.create(
            version=ver1,
            promoted_group=PromotedGroup.objects.get(
                group_id=PROMOTED_GROUP_CHOICES.RECOMMENDED
            ),
            application_id=amo.FIREFOX.id,
        )
        detail_url = reverse(self.detail_url_name, args=(item.pk,))
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Discovery:Edit')
        self.client.force_login(user)

        # try to change the approval group
        response = self.client.post(
            detail_url,
            dict(
                self._get_approval_form(item, [approval]),
                **{
                    'form-0-group_id': str(PROMOTED_GROUP_CHOICES.LINE),
                },
            ),
            follow=True,
        )
        approval.reload()
        assert approval.group_id == PROMOTED_GROUP_CHOICES.RECOMMENDED
        assert response.status_code == 200
        assert PromotedAddon.objects.count() == 1

        # try to add another approval
        response = self.client.post(
            detail_url,
            dict(
                self._get_approval_form(item, [approval]),
                **{
                    'form-1-id': '',
                    'form-1-group_id': str(PROMOTED_GROUP_CHOICES.LINE),
                    'form-1-version': str(ver1.id),
                },
            ),
            follow=True,
        )
        assert response.status_code == 200
        assert PromotedAddon.objects.count() == 1
        assert PromotedAddonVersion.objects.count() == 1

    def test_cannot_edit_without_discovery_edit_permission(self):
        addon = addon_factory()
        item = PromotedAddon.objects.create(
            addon=addon, group_id=PROMOTED_GROUP_CHOICES.RECOMMENDED
        )
        ver1 = addon.current_version
        approvals = [
            PromotedAddonVersion.objects.create(
                version=ver1,
                promoted_group=PromotedGroup.objects.get(
                    group_id=PROMOTED_GROUP_CHOICES.RECOMMENDED
                ),
                application_id=amo.FIREFOX.id,
            ),
        ]
        approvals.reverse()
        addon.reload()
        assert item.approved_applications
        detail_url = reverse(self.detail_url_name, args=(item.pk,))
        user = user_factory(email='someone@mozilla.com')
        self.client.force_login(user)
        # can't access
        response = self.client.get(detail_url, follow=True)
        assert response.status_code == 403

        # can't edit either
        response = self.client.post(
            detail_url,
            dict(
                self._get_approval_form(item, approvals),
                **{
                    'group_id': PROMOTED_GROUP_CHOICES.LINE,  # change the group
                },
            ),
            follow=True,
        )
        assert response.status_code == 403

        item.reload()
        assert PromotedAddon.objects.count() == 1
        assert item.group.id == PROMOTED_GROUP_CHOICES.RECOMMENDED
        assert PromotedAddonVersion.objects.count() == 1

        # Try to delete the approval instead
        response = self.client.post(
            detail_url,
            dict(
                self._get_approval_form(item, approvals),
                **{
                    'form-0-DELETE': 'on',  # delete the latest approval
                },
            ),
            follow=True,
        )
        assert response.status_code == 403
        assert PromotedAddon.objects.count() == 1
        assert PromotedAddonVersion.objects.count() == 1

    def test_can_delete_with_discovery_edit_permission(self):
        addon = addon_factory()
        item = self.make_addon_promoted(
            addon, PROMOTED_GROUP_CHOICES.LINE, approve_version=True
        )[0]
        delete_url = reverse(
            'admin:discovery_promotedaddonpromotion_delete', args=(item.pk,)
        )
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Discovery:Edit')
        self.client.force_login(user)
        # Can access delete confirmation page.
        response = self.client.get(delete_url, follow=True)
        assert response.status_code == 200
        assert PromotedAddon.objects.filter(pk=item.pk).exists()

        # And can actually delete.
        response = self.client.post(
            delete_url, dict(self._get_approval_form(item, []), post='yes'), follow=True
        )
        assert response.status_code == 200
        assert not PromotedAddon.objects.filter(pk=item.pk).exists()
        # The approval *won't* have been deleted though
        assert PromotedAddonVersion.objects.filter().exists()

    def test_cannot_delete_without_discovery_edit_permission(self):
        addon = addon_factory()
        item = self.make_addon_promoted(
            addon, PROMOTED_GROUP_CHOICES.RECOMMENDED, approve_version=True
        )[0]
        delete_url = reverse(
            'admin:discovery_promotedaddonpromotion_delete', args=(item.pk,)
        )
        user = user_factory(email='someone@mozilla.com')
        self.client.force_login(user)
        # Can't access delete confirmation page.
        response = self.client.get(delete_url, follow=True)
        assert response.status_code == 403
        assert PromotedAddon.objects.filter(pk=item.pk).exists()

        # And can't actually delete either
        response = self.client.post(
            delete_url, dict(self._get_approval_form(item, []), post='yes'), follow=True
        )
        assert response.status_code == 403
        assert PromotedAddon.objects.filter(pk=item.pk).exists()

    def test_can_add_with_discovery_edit_permission(self):
        addon = addon_factory()
        add_url = reverse('admin:discovery_promotedaddonpromotion_add')
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Discovery:Edit')
        self.client.force_login(user)
        response = self.client.get(add_url, follow=True)
        assert response.status_code == 200
        assert PromotedAddon.objects.count() == 0
        response = self.client.post(
            add_url,
            dict(
                self._get_approval_form(None, []),
                **{
                    'addon': str(addon.id),
                    'group_id': str(PROMOTED_GROUP_CHOICES.RECOMMENDED),
                },
            ),
            follow=True,
        )
        assert response.status_code == 200
        assert 'errors' not in response.context_data
        assert PromotedAddon.objects.count() == 1
        item = PromotedAddon.objects.get()
        assert item.addon == addon
        assert item.group.id == PROMOTED_GROUP_CHOICES.RECOMMENDED
        assert item.application_id is None
        assert item.all_applications == [amo.FIREFOX, amo.ANDROID]
        assert PromotedAddonVersion.objects.count() == 0  # we didn't create any
        assert not addon.promoted_groups()

    def test_can_add_when_existing_approval(self):
        addon = addon_factory(name='unattached')
        add_url = reverse('admin:discovery_promotedaddonpromotion_add')
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Discovery:Edit')
        self.client.force_login(user)
        # create an approval that doesn't have a matching PromotedAddon yet
        PromotedAddonVersion.objects.create(
            version=addon.current_version,
            promoted_group=PromotedGroup.objects.get(
                group_id=PROMOTED_GROUP_CHOICES.LINE
            ),
            application_id=amo.FIREFOX.id,
        )
        response = self.client.get(add_url, follow=True)
        assert response.status_code == 200
        # this *shouldn't* be in the response - the add page doesn't know what
        # addon will be attached to the PromotedAddon beforehand.
        assert b'unattached' not in response.content
        assert PromotedAddon.objects.count() == 0
        response = self.client.post(
            add_url,
            dict(
                self._get_approval_form(None, []),
                **{
                    'addon': str(addon.id),
                    'group_id': str(PROMOTED_GROUP_CHOICES.LINE),
                },
            ),
            follow=True,
        )
        assert response.status_code == 200
        assert 'errors' not in response.context_data
        assert PromotedAddonVersion.objects.count() == 1  # still one
        assert (
            PROMOTED_GROUP_CHOICES.LINE in addon.promoted_groups().group_id
        )  # now approved

    def test_cannot_add_without_discovery_edit_permission(self):
        addon = addon_factory()
        add_url = reverse('admin:discovery_promotedaddonpromotion_add')
        user = user_factory(email='someone@mozilla.com')
        self.client.force_login(user)
        response = self.client.get(add_url, follow=True)
        assert response.status_code == 403
        # try to add anyway
        response = self.client.post(
            add_url,
            dict(
                self._get_approval_form(None, []),
                **{
                    'addon': str(addon.id),
                    'group_id': str(PROMOTED_GROUP_CHOICES.RECOMMENDED),
                },
            ),
            follow=True,
        )
        assert response.status_code == 403
        assert PromotedAddon.objects.count() == 0

    def test_updates_not_promoted_to_line(self):
        item = self.make_addon_promoted(
            addon=addon_factory(), group_id=PROMOTED_GROUP_CHOICES.RECOMMENDED
        )[0]
        detail_url = reverse(self.detail_url_name, args=(item.pk,))
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Discovery:Edit')
        self.client.force_login(user)

        response = self.client.post(
            detail_url,
            dict(
                self._get_approval_form(item, []),
                **self._get_heroform(item.id),
                **{'group_id': PROMOTED_GROUP_CHOICES.LINE},  # change group
            ),
            follow=True,
        )
        item.reload()

        assert response.status_code == 200
        assert item.group_id == PROMOTED_GROUP_CHOICES.LINE
