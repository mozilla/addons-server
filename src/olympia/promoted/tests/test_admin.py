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
from olympia.amo.tests.test_helpers import get_uploaded_file
from olympia.constants.promoted import PROMOTED_GROUP_CHOICES
from olympia.hero.models import PrimaryHero, PrimaryHeroImage
from olympia.promoted.models import (
    PromotedAddonVersion,
    PromotedApproval,
    PromotedGroup,
)


class TestDiscoveryPromotedGroupAdmin(TestCase):
    def setUp(self):
        self.list_url_name = 'admin:discovery_discoverypromotedgroup_changelist'

    def test_can_see_in_admin_with_discovery_edit(self):
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Discovery:Edit')
        self.client.force_login(user)
        url = reverse('admin:index')
        response = self.client.get(url)
        assert response.status_code == 200

        # Use django's reverse, since that's what the admin will use. Using our
        # own would fail the assertion because of the locale that gets added.
        self.list_url = django_reverse(self.list_url_name)
        assert self.list_url in response.content.decode('utf-8')

    def test_cannot_see_in_admin_without_discovery_edit(self):
        user = user_factory(email='someone@mozilla.com')
        self.client.force_login(user)
        url = reverse('admin:index')
        response = self.client.get(url)
        assert response.status_code == 200

        self.list_url = django_reverse(self.list_url_name)
        assert self.list_url not in response.content.decode('utf-8')

    def test_can_list_with_discovery_edit(self):
        addon_factory(name='FooBâr')
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Discovery:Edit')
        self.client.force_login(user)
        response = self.client.get(reverse(self.list_url_name), follow=True)
        assert response.status_code == 200

    def test_cannot_list_without_discovery_edit(self):
        addon_factory(name='FooBâr')
        user = user_factory(email='someone@mozilla.com')
        self.client.force_login(user)
        response = self.client.get(reverse(self.list_url_name), follow=True)
        assert response.status_code == 403


class TestDiscoveryAddonAdmin(TestCase):
    def setUp(self):
        self.list_url = reverse('admin:discovery_discoveryaddon_changelist')
        self.detail_url_name = 'admin:discovery_discoveryaddon_change'

    def _get_approval_form(self, approvals):
        count = str(len(approvals))
        out = {
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

    def _get_promotedgrouppromotionform(
        self, promotion=None, promoted_group=None, application_id=None
    ):
        return {
            'promotedaddonpromotion-0-id': str(promotion.pk) if promotion else '',
            'promotedaddonpromotion-TOTAL_FORMS': '1',
            'promotedaddonpromotion-INITIAL_FORMS': '1' if promotion else '0',
            'promotedaddonpromotion-0-promoted_group': str(promoted_group.id)
            if promoted_group
            else '',
            'promotedaddonpromotion-0-application_id': str(application_id)
            if application_id
            else '',
        }

    def _get_heroform(self, item_id):
        return {
            'primaryhero-TOTAL_FORMS': '1',
            'primaryhero-INITIAL_FORMS': '0',
            'primaryhero-MIN_NUM_FORMS': '0',
            'primaryhero-MAX_NUM_FORMS': '1',
            'primaryhero-0-image': '',
            'primaryhero-0-gradient_color': '',
            'primaryhero-0-id': '',
            'primaryhero-0-promoted_addon': item_id,
            'primaryhero-__prefix__-image': '',
            'primaryhero-__prefix__-gradient_color': '',
            'primaryhero-__prefix__-id': '',
            'primaryhero-__prefix__-promoted_addon': item_id,
        }

    def test_can_see_in_admin_with_discovery_edit(self):
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Discovery:Edit')
        self.client.force_login(user)
        url = reverse('admin:index')
        response = self.client.get(url)
        assert response.status_code == 200

        # Use django's reverse, since that's what the admin will use. Using our
        # own would fail the assertion because of the locale that gets added.
        self.list_url = django_reverse('admin:discovery_discoveryaddon_changelist')
        assert self.list_url in response.content.decode('utf-8')

    def test_can_list_with_discovery_edit_permission(self):
        addon_factory(name='FooBâr')
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Discovery:Edit')
        self.client.force_login(user)

        with self.assertNumQueries(8):
            # 1. select current user
            # 2. savepoint (because we're in tests)
            # 3. select groups
            # 4. pagination count
            #    (show_full_result_count=False so we avoid the duplicate)
            # 5. select list of promoted addons, ordered
            # 6. prefetch add-ons
            # 7. select translations for add-ons from 7.
            # 8. check if addon has promoted groups
            response = self.client.get(self.list_url, follow=True)

        assert response.status_code == 200
        assert 'FooBâr' in response.content.decode('utf-8')

        # double check it scales.
        addon_factory(name='FooBâr')
        # throw in a promoted addon that doesn't have a current_version
        addon_factory(name='FooBâr', version_kw={'channel': amo.CHANNEL_UNLISTED})
        with self.assertNumQueries(10):
            self.client.get(self.list_url, follow=True)

    def test_can_edit_with_discovery_edit_permission(self):
        addon = addon_factory()
        promotion = PromotedAddonPromotion.objects.create(
            addon=addon,
            promoted_group=PromotedGroup.objects.get(
                group_id=PROMOTED_GROUP_CHOICES.RECOMMENDED
            ),
            application_id=amo.FIREFOX.id,
        )
        ver1 = addon.current_version
        ver1.update(version='1.111')
        ver2 = version_factory(addon=addon, version='1.222')
        ver3 = version_factory(addon=addon, version='1.333')
        addon.reload()
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
        assert addon.approved_applications
        detail_url = reverse(self.detail_url_name, args=(addon.pk,))
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
                self._get_approval_form(approvals),
                **self._get_promotedgrouppromotionform(
                    promotion=promotion,
                    promoted_group=PromotedGroup.objects.get(
                        group_id=PROMOTED_GROUP_CHOICES.LINE
                    ),
                    application_id=amo.FIREFOX.id,
                ),
                **self._get_heroform(''),
            ),
            follow=True,
        )
        assert response.status_code == 200

        promotion.reload()
        assert 'errors' not in response.context_data, response.context_data['errors']
        assert PromotedAddonPromotion.objects.count() == 1
        assert promotion.promoted_group.group_id == PROMOTED_GROUP_CHOICES.LINE
        assert PromotedAddonVersion.objects.count() == 4  # same
        # now it's not promoted because the current_version isn't approved for
        # LINE group
        assert not addon.approved_applications_for(PROMOTED_GROUP_CHOICES.LINE)

        # Try to delete one of the approvals
        response = self.client.post(
            detail_url,
            dict(
                self._get_approval_form(approvals),
                **self._get_heroform(''),
                **self._get_promotedgrouppromotionform(),
                **{
                    'form-0-DELETE': 'on',  # delete the latest approval
                },
            ),
            follow=True,
        )
        assert response.status_code == 200
        assert 'errors' not in response.context_data, response.context_data['errors']
        assert PromotedAddonPromotion.objects.count() == 1
        assert PromotedAddonVersion.objects.count() == 3
        assert PrimaryHero.objects.count() == 0  # check we didn't add

    def test_cannot_add_or_change_approval(self):
        addon = addon_factory()
        promotion = PromotedAddonPromotion.objects.create(
            addon=addon,
            promoted_group=PromotedGroup.objects.get(
                group_id=PROMOTED_GROUP_CHOICES.RECOMMENDED
            ),
            application_id=amo.FIREFOX.id,
        )
        ver1 = addon.current_version
        approval = PromotedApproval.objects.create(
            version=ver1,
            group_id=PROMOTED_GROUP_CHOICES.RECOMMENDED,
            application_id=amo.FIREFOX.id,
        )
        detail_url = reverse(self.detail_url_name, args=(addon.pk,))
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Discovery:Edit')
        self.client.force_login(user)

        # try to change the approval group
        response = self.client.post(
            detail_url,
            dict(
                self._get_approval_form([approval]),
                **self._get_heroform(''),
                **self._get_promotedgrouppromotionform(
                    promotion=promotion,
                    promoted_group=PromotedGroup.objects.get(
                        group_id=PROMOTED_GROUP_CHOICES.LINE
                    ),
                    application_id=amo.FIREFOX.id,
                ),
            ),
            follow=True,
        )
        approval.reload()
        assert approval.group_id == PROMOTED_GROUP_CHOICES.RECOMMENDED
        assert response.status_code == 200
        assert PromotedAddonPromotion.objects.count() == 1

        # try to add another approval
        response = self.client.post(
            detail_url,
            dict(
                self._get_approval_form([approval]),
                **self._get_heroform(''),
                **{
                    'form-1-id': '',
                    'form-1-promoted_group': PromotedGroup.objects.get(
                        group_id=PROMOTED_GROUP_CHOICES.LINE
                    ),
                    'form-1-version': str(ver1.id),
                },
            ),
            follow=True,
        )
        assert response.status_code == 200
        assert PromotedAddonPromotion.objects.count() == 1
        assert PromotedApproval.objects.count() == 1

    def test_cannot_edit_without_discovery_edit_permission(self):
        addon = addon_factory()
        promotion = PromotedAddonPromotion.objects.create(
            addon=addon,
            promoted_group=PromotedGroup.objects.get(
                group_id=PROMOTED_GROUP_CHOICES.RECOMMENDED
            ),
            application_id=amo.FIREFOX.id,
        )
        ver1 = addon.current_version
        approvals = [
            PromotedApproval.objects.create(
                version=ver1,
                group_id=PROMOTED_GROUP_CHOICES.RECOMMENDED,
                application_id=amo.FIREFOX.id,
            ),
        ]
        approvals.reverse()
        addon.reload()
        assert addon.approved_applications
        detail_url = reverse(self.detail_url_name, args=(addon.pk,))
        user = user_factory(email='someone@mozilla.com')
        self.client.force_login(user)
        # can't access
        response = self.client.get(detail_url, follow=True)
        assert response.status_code == 403

        # can't edit either
        response = self.client.post(
            detail_url,
            dict(
                self._get_approval_form(approvals),
                **self._get_promotedgrouppromotionform(
                    promotion=promotion,
                    promoted_group=PromotedGroup.objects.get(
                        group_id=PROMOTED_GROUP_CHOICES.LINE
                    ),
                    application_id=amo.FIREFOX.id,
                ),
            ),
            follow=True,
        )
        assert response.status_code == 403

        promotion.reload()
        assert PromotedAddonPromotion.objects.count() == 1
        assert promotion.promoted_group.group_id == PROMOTED_GROUP_CHOICES.RECOMMENDED
        assert PromotedApproval.objects.count() == 1

        # Try to delete the approval instead
        response = self.client.post(
            detail_url,
            dict(
                self._get_approval_form(approvals),
                **{
                    'form-0-DELETE': 'on',  # delete the latest approval
                },
            ),
            follow=True,
        )
        assert response.status_code == 403
        assert PromotedAddonPromotion.objects.count() == 1
        assert PromotedApproval.objects.count() == 1

    def test_can_delete_with_discovery_edit_permission(self):
        addon = addon_factory()
        promotion = PromotedAddonPromotion.objects.create(
            addon=addon,
            promoted_group=PromotedGroup.objects.get(
                group_id=PROMOTED_GROUP_CHOICES.RECOMMENDED
            ),
            application_id=amo.FIREFOX.id,
        )
        PromotedAddonVersion.objects.create(
            version=addon.current_version,
            promoted_group=PromotedGroup.objects.get(
                group_id=PROMOTED_GROUP_CHOICES.RECOMMENDED
            ),
            application_id=amo.FIREFOX.id,
        )
        detail_url = reverse(self.detail_url_name, args=(addon.pk,))
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Discovery:Edit')
        self.client.force_login(user)

        # And can delete.
        response = self.client.post(
            detail_url,
            dict(
                self._get_approval_form([]),
                **self._get_heroform(''),
                **self._get_promotedgrouppromotionform(promotion=promotion),
                **{
                    'promotedaddonpromotion-0-DELETE': 'on',
                },
            ),
            follow=True,
        )
        assert response.status_code == 200
        assert not PromotedAddonPromotion.objects.filter(pk=promotion.pk).exists()
        # The approval *won't* have been deleted though
        assert PromotedAddonVersion.objects.filter().exists()

    def test_cannot_delete_without_discovery_edit_permission(self):
        addon = addon_factory()
        promotion = PromotedAddonPromotion.objects.create(
            addon=addon,
            promoted_group=PromotedGroup.objects.get(
                group_id=PROMOTED_GROUP_CHOICES.RECOMMENDED
            ),
            application_id=amo.FIREFOX.id,
        )
        detail_url = reverse(self.detail_url_name, args=(addon.pk,))
        user = user_factory(email='someone@mozilla.com')
        self.client.force_login(user)

        # Can't delete.
        response = self.client.post(
            detail_url,
            dict(
                self._get_approval_form([]),
                **self._get_heroform(''),
                **self._get_promotedgrouppromotionform(promotion=promotion),
                **{
                    'promotedaddonpromotion-0-DELETE': 'on',
                },
            ),
            follow=True,
        )
        assert response.status_code == 403
        assert PromotedAddonPromotion.objects.filter(pk=promotion.pk).exists()

    def test_can_add_with_discovery_edit_permission(self):
        addon = addon_factory()
        detail_url = reverse(self.detail_url_name, args=(addon.pk,))
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Discovery:Edit')
        self.client.force_login(user)
        # create an approval that doesn't have a matching PromotedAddon yet
        group = PromotedGroup.objects.get(group_id=PROMOTED_GROUP_CHOICES.RECOMMENDED)
        response = self.client.get(detail_url, follow=True)
        assert response.status_code == 200
        assert PromotedAddonPromotion.objects.count() == 0
        response = self.client.post(
            detail_url,
            dict(
                self._get_approval_form([]),
                **self._get_heroform(''),
                **self._get_promotedgrouppromotionform(
                    promoted_group=group, application_id=amo.FIREFOX.id
                ),
            ),
            follow=True,
        )
        assert response.status_code == 200
        assert 'errors' not in response.context_data
        assert PromotedAddonPromotion.objects.count() == 1
        item = PromotedAddonPromotion.objects.get()
        assert item.addon == addon
        assert item.promoted_group.group_id == PROMOTED_GROUP_CHOICES.RECOMMENDED
        assert item.application_id == amo.FIREFOX.id
        assert item.application == amo.FIREFOX
        assert (
            PromotedAddonVersion.objects.count() == 0
        )  # we didn't create any approvals
        assert not addon.promoted_groups()

    def test_can_add_when_existing_approval(self):
        addon = addon_factory(name='unattached')
        detail_url = reverse(self.detail_url_name, args=(addon.pk,))
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Discovery:Edit')
        self.client.force_login(user)
        # create an approval that doesn't have a matching PromotedAddon yet
        group = PromotedGroup.objects.get(group_id=PROMOTED_GROUP_CHOICES.LINE)
        PromotedAddonVersion.objects.create(
            version=addon.current_version,
            promoted_group=group,
            application_id=amo.FIREFOX.id,
        )
        response = self.client.get(detail_url, follow=True)
        assert response.status_code == 200
        assert b'unattached' in response.content
        assert PromotedAddonPromotion.objects.count() == 0
        response = self.client.post(
            detail_url,
            dict(
                self._get_approval_form([]),
                **self._get_heroform(''),
                **self._get_promotedgrouppromotionform(
                    promoted_group=group, application_id=amo.FIREFOX.id
                ),
            ),
            follow=True,
        )
        assert response.status_code == 200
        assert 'errors' not in response.context_data
        assert PromotedAddonVersion.objects.count() == 1  # still one
        assert PromotedAddonPromotion.objects.count() == 1
        assert (
            PROMOTED_GROUP_CHOICES.LINE in addon.promoted_groups().group_id
        )  # now approved

    def test_cannot_add_without_discovery_edit_permission(self):
        addon = addon_factory()
        detail_url = reverse(self.detail_url_name, args=(addon.pk,))
        user = user_factory(email='someone@mozilla.com')
        self.client.force_login(user)
        response = self.client.get(detail_url, follow=True)
        assert response.status_code == 403
        # try to add anyway
        response = self.client.post(
            detail_url,
            dict(
                self._get_approval_form([]),
            ),
            follow=True,
        )
        assert response.status_code == 403
        assert PromotedAddonPromotion.objects.count() == 0

    def test_can_edit_primary_hero(self):
        addon = addon_factory(name='BarFöo')
        hero = PrimaryHero.objects.create(addon=addon, gradient_color='#592ACB')
        self.detail_url = reverse(self.detail_url_name, args=(addon.pk,))
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Discovery:Edit')
        self.client.force_login(user)
        response = self.client.get(self.detail_url, follow=True)
        assert response.status_code == 200
        content = response.content.decode('utf-8')
        assert 'BarFöo' in content
        assert '#592ACB' in content

        response = self.client.post(
            self.detail_url,
            dict(
                self._get_heroform(addon.pk),
                **self._get_approval_form([]),
                **self._get_promotedgrouppromotionform(),
                **{
                    'primaryhero-INITIAL_FORMS': '1',
                    'primaryhero-0-id': str(hero.pk),
                    'primaryhero-0-gradient_color': '#054096',
                    'primaryhero-0-description': 'primary descriptíon',
                },
            ),
            follow=True,
        )
        assert response.status_code == 200
        addon.reload()
        hero.reload()
        assert PrimaryHero.objects.count() == 1
        assert hero.gradient_color == '#054096'
        assert hero.description == 'primary descriptíon'

    def test_can_add_primary_hero(self):
        addon = addon_factory(name='BarFöo')
        uploaded_photo = get_uploaded_file('transparent.png')
        image = PrimaryHeroImage.objects.create(custom_image=uploaded_photo)
        self.detail_url = reverse(self.detail_url_name, args=(addon.pk,))
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Discovery:Edit')
        self.client.force_login(user)
        response = self.client.get(self.detail_url, follow=True)
        assert response.status_code == 200
        content = response.content.decode('utf-8')
        assert 'BarFöo' in content
        assert 'No image selected' in content
        assert PrimaryHero.objects.count() == 0

        response = self.client.post(
            self.detail_url,
            dict(
                self._get_heroform(addon.pk),
                **self._get_approval_form([]),
                **self._get_promotedgrouppromotionform(),
                **{
                    'primaryhero-0-gradient_color': '#054096',
                    'primaryhero-0-select_image': image.pk,
                    'primaryhero-0-description': 'primary descriptíon',
                },
            ),
            follow=True,
        )
        assert response.status_code == 200
        addon.reload()
        assert PrimaryHero.objects.count() == 1
        hero = PrimaryHero.objects.last()
        assert hero.select_image == image
        assert hero.select_image.pk == image.pk
        assert hero.gradient_color == '#054096'
        assert hero.description == 'primary descriptíon'
