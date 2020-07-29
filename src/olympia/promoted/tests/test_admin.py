from olympia.amo.tests import (
    addon_factory, TestCase, user_factory, version_factory)
from olympia.amo.tests.test_helpers import get_uploaded_file
from olympia.amo.urlresolvers import django_reverse, reverse
from olympia.constants.promoted import LINE, RECOMMENDED
from olympia.hero.models import PrimaryHero, PrimaryHeroImage
from olympia.promoted.models import PromotedAddon, PromotedApproval


class TestPromotedAddonAdmin(TestCase):
    def setUp(self):
        self.list_url = reverse(
            'admin:promoted_promotedaddon_changelist')
        self.detail_url_name = 'admin:promoted_promotedaddon_change'

    def _get_approval_form(self, item, approvals):
        count = str(len(approvals))
        out = {
            "addon": str(item.addon_id) if item else '',
            "group_id": str(item.group_id) if item else '0',
            "application_id": str(getattr(item, 'application_id', None) or ''),
            "form-TOTAL_FORMS": str(count),
            "form-INITIAL_FORMS": str(count),
            "form-MIN_NUM_FORMS": '0',
            "form-MAX_NUM_FORMS": '0',
        }
        for index in range(0, len(approvals)):
            out.update(**{
                f"form-{index}-id": str(approvals[index].id),
            })
        return out

    def _get_heroform(self, item_id):
        return {
            "primaryhero-TOTAL_FORMS": "1",
            "primaryhero-INITIAL_FORMS": "0",
            "primaryhero-MIN_NUM_FORMS": "0",
            "primaryhero-MAX_NUM_FORMS": "1",
            "primaryhero-0-image": "",
            "primaryhero-0-gradient_color": "",
            "primaryhero-0-id": "",
            "primaryhero-0-promoted_addon": item_id,
            "primaryhero-__prefix__-image": "",
            "primaryhero-__prefix__-gradient_color": "",
            "primaryhero-__prefix__-id": "",
            "primaryhero-__prefix__-promoted_addon": item_id,
        }

    def test_can_see_in_admin_with_discovery_edit(self):
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Discovery:Edit')
        self.client.login(email=user.email)
        url = reverse('admin:index')
        response = self.client.get(url)
        assert response.status_code == 200

        # Use django's reverse, since that's what the admin will use. Using our
        # own would fail the assertion because of the locale that gets added.
        self.list_url = django_reverse(
            'admin:promoted_promotedaddon_changelist')
        assert self.list_url in response.content.decode('utf-8')

    def test_can_list_with_discovery_edit_permission(self):
        PromotedAddon.objects.create(addon=addon_factory(name='FooBâr'))
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Discovery:Edit')
        self.client.login(email=user.email)
        response = self.client.get(self.list_url, follow=True)
        assert response.status_code == 200
        assert 'FooBâr' in response.content.decode('utf-8')

    def test_can_edit_with_discovery_edit_permission(self):
        addon = addon_factory()
        item = PromotedAddon.objects.create(
            addon=addon, group_id=RECOMMENDED.id)
        ver1 = addon.current_version
        ver1.update(version='1.111')
        ver2 = version_factory(addon=addon, version='1.222')
        ver3 = version_factory(addon=addon, version='1.333')
        item.reload()
        assert item.addon.current_version == ver3
        approvals = [
            PromotedApproval.objects.create(
                version=ver1, group_id=RECOMMENDED.id),
            PromotedApproval.objects.create(
                version=ver2, group_id=RECOMMENDED.id),
            PromotedApproval.objects.create(
                version=ver2, group_id=LINE.id),
            PromotedApproval.objects.create(
                version=ver3, group_id=RECOMMENDED.id),
        ]
        approvals.reverse()  # we order by -version_id so match it.
        item.reload()
        assert item.is_addon_currently_promoted
        detail_url = reverse(self.detail_url_name, args=(item.pk,))
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Discovery:Edit')
        self.client.login(email=user.email)
        response = self.client.get(detail_url, follow=True)
        assert response.status_code == 200
        content = response.content.decode('utf-8')
        assert '1.111' in content
        assert '1.222' in content
        assert '1.333' in content

        response = self.client.post(
            detail_url,
            dict(self._get_approval_form(item, approvals),
                 **self._get_heroform(''), **{
                'group_id': LINE.id,  # change the group
            }), follow=True)
        assert response.status_code == 200
        assert 'errors' not in response.context_data, (
            response.context_data['errors'])
        item.reload()
        assert PromotedAddon.objects.count() == 1
        assert item.group == LINE
        assert PromotedApproval.objects.count() == 4  # same
        # now it's not promoted because the current_version isn't approved for
        # LINE group
        assert not item.is_addon_currently_promoted

        # Try to delete one of the approvals
        response = self.client.post(
            detail_url,
            dict(self._get_approval_form(item, approvals),
                 **self._get_heroform(''), **{
                'form-0-DELETE': 'on',  # delete the latest approval
            }), follow=True)
        assert response.status_code == 200
        assert 'errors' not in response.context_data, (
            response.context_data['errors'])
        assert PromotedAddon.objects.count() == 1
        assert PromotedApproval.objects.count() == 3
        assert PrimaryHero.objects.count() == 0  # check we didn't add

    def test_cannot_add_or_change_approval(self):
        addon = addon_factory()
        item = PromotedAddon.objects.create(
            addon=addon, group_id=RECOMMENDED.id)
        ver1 = addon.current_version
        approval = PromotedApproval.objects.create(
            version=ver1, group_id=RECOMMENDED.id)
        detail_url = reverse(self.detail_url_name, args=(item.pk,))
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Discovery:Edit')
        self.client.login(email=user.email)

        # try to change the approval group
        response = self.client.post(
            detail_url,
            dict(self._get_approval_form(item, [approval]),
                 **self._get_heroform(''), **{
                "form-0-group_id": str(LINE.id),
            }), follow=True)
        approval.reload()
        assert approval.group_id == RECOMMENDED.id
        assert response.status_code == 200
        assert PromotedAddon.objects.count() == 1

        # try to add another approval
        response = self.client.post(
            detail_url,
            dict(self._get_approval_form(item, [approval]),
                 **self._get_heroform(''), **{
                "form-1-id": '',
                "form-1-group_id": str(LINE.id),
                "form-1-version": str(ver1.id),
            }), follow=True)
        assert response.status_code == 200
        assert PromotedAddon.objects.count() == 1
        assert PromotedApproval.objects.count() == 1

    def test_cannot_edit_without_discovery_edit_permission(self):
        addon = addon_factory()
        item = PromotedAddon.objects.create(
            addon=addon, group_id=RECOMMENDED.id)
        ver1 = addon.current_version
        approvals = [
            PromotedApproval.objects.create(
                version=ver1, group_id=RECOMMENDED.id),
        ]
        approvals.reverse()
        addon.reload()
        assert item.is_addon_currently_promoted
        detail_url = reverse(self.detail_url_name, args=(item.pk,))
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.client.login(email=user.email)
        # can't access
        response = self.client.get(detail_url, follow=True)
        assert response.status_code == 403

        # can't edit either
        response = self.client.post(
            detail_url,
            dict(self._get_approval_form(item, approvals), **{
                'group_id': LINE.id,  # change the group
            }), follow=True)
        assert response.status_code == 403

        item.reload()
        assert PromotedAddon.objects.count() == 1
        assert item.group == RECOMMENDED
        assert PromotedApproval.objects.count() == 1

        # Try to delete the approval instead
        response = self.client.post(
            detail_url,
            dict(self._get_approval_form(item, approvals), **{
                'form-0-DELETE': 'on',  # delete the latest approval
            }), follow=True)
        assert response.status_code == 403
        assert PromotedAddon.objects.count() == 1
        assert PromotedApproval.objects.count() == 1

    def test_can_delete_with_discovery_edit_permission(self):
        addon = addon_factory()
        item = PromotedAddon.objects.create(addon=addon)
        PromotedApproval.objects.create(version=addon.current_version)
        delete_url = reverse(
            'admin:promoted_promotedaddon_delete', args=(item.pk,)
        )
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Discovery:Edit')
        self.client.login(email=user.email)
        # Can access delete confirmation page.
        response = self.client.get(delete_url, follow=True)
        assert response.status_code == 200
        assert PromotedAddon.objects.filter(pk=item.pk).exists()

        # And can actually delete.
        response = self.client.post(
            delete_url,
            dict(self._get_approval_form(item, []), post='yes'),
            follow=True)
        assert response.status_code == 200
        assert not PromotedAddon.objects.filter(pk=item.pk).exists()
        # The approval *won't* have been deleted though
        assert PromotedApproval.objects.filter().exists()

    def test_cannot_delete_without_discovery_edit_permission(self):
        addon = addon_factory()
        item = PromotedAddon.objects.create(addon=addon)
        PromotedApproval.objects.create(version=addon.current_version)
        delete_url = reverse(
            'admin:promoted_promotedaddon_delete', args=(item.pk,)
        )
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.client.login(email=user.email)
        # Can't access delete confirmation page.
        response = self.client.get(delete_url, follow=True)
        assert response.status_code == 403
        assert PromotedAddon.objects.filter(pk=item.pk).exists()

        # And can't actually delete either
        response = self.client.post(
            delete_url,
            dict(self._get_approval_form(item, []), post='yes'),
            follow=True)
        assert response.status_code == 403
        assert PromotedAddon.objects.filter(pk=item.pk).exists()

    def test_can_add_with_discovery_edit_permission(self):
        addon = addon_factory()
        add_url = reverse('admin:promoted_promotedaddon_add')
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Discovery:Edit')
        self.client.login(email=user.email)
        response = self.client.get(add_url, follow=True)
        assert response.status_code == 200
        assert PromotedAddon.objects.count() == 0
        response = self.client.post(
            add_url,
            dict(self._get_approval_form(None, []),
                 **self._get_heroform(''), **{
                'addon': str(addon.id),
                'group_id': str(RECOMMENDED.id),
            }),
            follow=True)
        assert response.status_code == 200
        assert 'errors' not in response.context_data
        assert PromotedAddon.objects.count() == 1
        item = PromotedAddon.objects.get()
        assert item.addon == addon
        assert item.group == RECOMMENDED
        assert item.application is None
        assert PromotedApproval.objects.count() == 0  # we didn't create any

    def test_cannot_add_without_discovery_edit_permission(self):
        addon = addon_factory()
        add_url = reverse('admin:promoted_promotedaddon_add')
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.client.login(email=user.email)
        response = self.client.get(add_url, follow=True)
        assert response.status_code == 403
        # try to add anyway
        response = self.client.post(
            add_url,
            dict(self._get_approval_form(None, []), **{
                'addon': str(addon.id),
                'group_id': str(RECOMMENDED.id),
            }),
            follow=True)
        assert response.status_code == 403
        assert PromotedAddon.objects.count() == 0

    def test_can_edit_primary_hero(self):
        addon = addon_factory(name=u'BarFöo')
        item = PromotedAddon.objects.create(addon=addon)
        hero = PrimaryHero.objects.create(
            promoted_addon=item, gradient_color='#592ACB')
        self.detail_url = reverse(
            self.detail_url_name, args=(item.pk,)
        )
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Discovery:Edit')
        self.client.login(email=user.email)
        response = self.client.get(self.detail_url, follow=True)
        assert response.status_code == 200
        content = response.content.decode('utf-8')
        assert 'BarFöo' in content
        assert '#592ACB' in content

        response = self.client.post(
            self.detail_url,
            dict(self._get_heroform(item.pk),
                 **self._get_approval_form(item, []), **{
                'primaryhero-INITIAL_FORMS': '1',
                'primaryhero-0-id': str(hero.pk),
                'primaryhero-0-gradient_color': '#054096',
                'primaryhero-0-description': 'primary descriptíon',
            }), follow=True)
        assert response.status_code == 200
        item.reload()
        hero.reload()
        assert PromotedAddon.objects.count() == 1
        assert PrimaryHero.objects.count() == 1
        assert item.addon == addon
        assert hero.gradient_color == '#054096'
        assert hero.description == 'primary descriptíon'

    def test_can_add_primary_hero(self):
        addon = addon_factory(name=u'BarFöo')
        item = PromotedAddon.objects.create(addon=addon)
        uploaded_photo = get_uploaded_file('transparent.png')
        image = PrimaryHeroImage.objects.create(custom_image=uploaded_photo)
        self.detail_url = reverse(
            self.detail_url_name, args=(item.pk,)
        )
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Discovery:Edit')
        self.client.login(email=user.email)
        response = self.client.get(self.detail_url, follow=True)
        assert response.status_code == 200
        content = response.content.decode('utf-8')
        assert 'BarFöo' in content
        assert 'No image selected' in content
        assert PrimaryHero.objects.count() == 0

        response = self.client.post(
            self.detail_url,
            dict(self._get_heroform(item.pk),
                 **self._get_approval_form(item, []), **{
                'primaryhero-0-gradient_color': '#054096',
                'primaryhero-0-select_image': image.pk,
                'primaryhero-0-description': 'primary descriptíon',
            }), follow=True)
        assert response.status_code == 200
        item.reload()
        assert PromotedAddon.objects.count() == 1
        assert PrimaryHero.objects.count() == 1
        assert item.addon == addon
        hero = PrimaryHero.objects.last()
        hero.select_image == image
        assert hero.select_image.pk == image.pk
        assert hero.gradient_color == '#054096'
        assert hero.promoted_addon == item
        assert hero.description == 'primary descriptíon'

    def test_can_delete_when_primary_hero_too(self):
        addon = addon_factory()
        item = PromotedAddon.objects.create(addon=addon)
        PromotedApproval.objects.create(version=addon.current_version)
        shelf = PrimaryHero.objects.create(promoted_addon=item)
        delete_url = reverse(
            'admin:promoted_promotedaddon_delete', args=(item.pk,)
        )
        user = user_factory()
        self.grant_permission(user, 'Admin:Tools')
        self.grant_permission(user, 'Discovery:Edit')
        self.client.login(email=user.email)
        # Can access delete confirmation page.
        response = self.client.get(delete_url, follow=True)
        assert response.status_code == 200
        assert PromotedAddon.objects.filter(pk=item.pk).exists()
        assert PrimaryHero.objects.filter(pk=shelf.id).exists()

        # But not if the primary hero shelf is the only enabled shelf.
        shelf.update(enabled=True)
        response = self.client.get(delete_url, follow=True)
        assert response.status_code == 403

        # And can't actually delete either
        response = self.client.post(
            delete_url,
            {'post': 'yes'},
            follow=True)
        assert response.status_code == 403
        assert PromotedAddon.objects.filter(pk=item.pk).exists()

        # But if there's another enabled shelf we can now access the page.
        PrimaryHero.objects.create(
            promoted_addon=PromotedAddon.objects.create(addon=addon_factory()),
            enabled=True)
        response = self.client.get(delete_url, follow=True)
        assert response.status_code == 200

        # And can actually delete.
        response = self.client.post(
            delete_url,
            {'post': 'yes'},
            follow=True)
        assert response.status_code == 200
        assert not PromotedAddon.objects.filter(pk=item.pk).exists()
        assert not PrimaryHero.objects.filter(pk=shelf.id).exists()
        # The approval *won't* have been deleted though
        assert PromotedApproval.objects.filter().exists()
