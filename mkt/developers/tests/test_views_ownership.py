"""Tests related to the ``mkt.developers.addons.owner`` view."""
from nose.tools import eq_
from pyquery import PyQuery as pq
import waffle

import amo
import amo.tests
from amo.tests import formset
from addons.models import Addon, AddonUser
from mkt.developers.models import ActivityLog
from users.models import UserProfile
from versions.models import License, Version


class TestOwnership(amo.tests.TestCase):
    fixtures = ['base/apps', 'base/users', 'base/addon_3615']

    def setUp(self):
        self.addon = Addon.objects.get(id=3615)
        self.version = self.addon.current_version
        self.url = self.addon.get_dev_url('owner')
        assert self.client.login(username='del@icio.us', password='password')

    def formset(self, *args, **kw):
        defaults = {'builtin': License.OTHER, 'text': 'filler'}
        defaults.update(kw)
        return formset(*args, **defaults)

    def get_version(self):
        return Version.objects.no_cache().get(id=self.version.id)

    def get_addon(self):
        return Addon.objects.no_cache().get(id=self.addon.id)


class TestEditAuthor(TestOwnership):

    def test_addons_context(self):
        r = self.client.get(self.url)
        eq_(r.context['webapp'], False)

    def test_reorder_authors(self):
        """
        Re-ordering authors should not generate role changes in the
        ActivityLog.
        """
        # flip form-0-position
        f = self.client.get(self.url).context['user_form'].initial_forms[0]
        u = dict(user='regular@mozilla.com', listed=True,
                 role=amo.AUTHOR_ROLE_DEV, position=0)
        data = self.formset(f.initial, u, initial_count=1)
        r = self.client.post(self.url, data)
        eq_(r.status_code, 302)
        f = self.client.get(self.url).context['user_form'].initial_forms[0]
        u1 = f.initial
        u1['position'] = 1
        f = self.client.get(self.url).context['user_form'].initial_forms[1]
        u2 = f.initial
        data = self.formset(u1, u2)

        orig = ActivityLog.objects.all().count()
        r = self.client.post(self.url, data)
        self.assertRedirects(r, self.url, 302)
        eq_(ActivityLog.objects.all().count(), orig)

    def test_success_add_user(self):
        q = (AddonUser.objects.no_cache().filter(addon=3615)
             .values_list('user', flat=True))
        eq_(list(q.all()), [55021])

        f = self.client.get(self.url).context['user_form'].initial_forms[0]
        u = dict(user='regular@mozilla.com', listed=True,
                 role=amo.AUTHOR_ROLE_DEV, position=0)
        data = self.formset(f.initial, u, initial_count=1)
        r = self.client.post(self.url, data)
        self.assertRedirects(r, self.url, 302)
        eq_(list(q.all()), [55021, 999])

    def test_success_edit_user(self):
        # Add an author b/c we can't edit anything about the current one.
        f = self.client.get(self.url).context['user_form'].initial_forms[0]
        u = dict(user='regular@mozilla.com', listed=True,
                 role=amo.AUTHOR_ROLE_DEV, position=1)
        data = self.formset(f.initial, u, initial_count=1)
        self.client.post(self.url, data)
        eq_(AddonUser.objects.get(addon=3615, user=999).listed, True)

        # Edit the user we just added.
        user_form = self.client.get(self.url).context['user_form']
        one, two = user_form.initial_forms
        del two.initial['listed']
        empty = dict(user='', listed=True, role=5, position=0)
        data = self.formset(one.initial, two.initial, empty, initial_count=2)
        r = self.client.post(self.url, data)
        self.assertRedirects(r, self.url, 302)
        eq_(AddonUser.objects.no_cache().get(addon=3615, user=999).listed,
            False)

    def test_add_user_twice(self):
        f = self.client.get(self.url).context['user_form'].initial_forms[0]
        u = dict(user='regular@mozilla.com', listed=True,
                 role=amo.AUTHOR_ROLE_DEV, position=1)
        data = self.formset(f.initial, u, u, initial_count=1)
        r = self.client.post(self.url, data)
        eq_(r.status_code, 200)
        eq_(r.context['user_form'].non_form_errors(),
            ['An author can only be listed once.'])

    def test_success_delete_user(self):
        # Add a new user so we have one to delete.
        data = self.formset(dict(user='regular@mozilla.com', listed=True,
                                 role=amo.AUTHOR_ROLE_OWNER, position=1),
                            initial_count=0)
        self.client.post(self.url, data)

        one, two = self.client.get(self.url).context['user_form'].initial_forms
        one.initial['DELETE'] = True
        data = self.formset(one.initial, two.initial, initial_count=2)
        r = self.client.post(self.url, data)
        eq_(r.status_code, 302)
        eq_(999, AddonUser.objects.get(addon=3615).user_id)

    def test_switch_owner(self):
        # See if we can transfer ownership in one POST.
        f = self.client.get(self.url).context['user_form'].initial_forms[0]
        f.initial['user'] = 'regular@mozilla.com'
        data = self.formset(f.initial, initial_count=1)
        r = self.client.post(self.url, data)
        eq_(r.status_code, 302)
        eq_(999, AddonUser.objects.get(addon=3615).user_id)
        eq_(ActivityLog.objects.filter(
            action=amo.LOG.ADD_USER_WITH_ROLE.id).count(), 1)
        eq_(ActivityLog.objects.filter(
            action=amo.LOG.REMOVE_USER_WITH_ROLE.id).count(), 1)

    def test_only_owner_can_edit(self):
        f = self.client.get(self.url).context['user_form'].initial_forms[0]
        u = dict(user='regular@mozilla.com', listed=True,
                 role=amo.AUTHOR_ROLE_DEV, position=0)
        data = self.formset(f.initial, u, initial_count=1)
        self.client.post(self.url, data)

        self.client.login(username='regular@mozilla.com', password='password')
        self.client.post(self.url, data, follow=True)

        # Try deleting the other AddonUser
        one, two = self.client.get(self.url).context['user_form'].initial_forms
        one.initial['DELETE'] = True
        data = self.formset(one.initial, two.initial, initial_count=2)
        r = self.client.post(self.url, data, follow=True)
        eq_(r.status_code, 403)
        eq_(AddonUser.objects.filter(addon=3615).count(), 2)

    def test_must_have_listed(self):
        f = self.client.get(self.url).context['user_form'].initial_forms[0]
        f.initial['listed'] = False
        data = self.formset(f.initial, initial_count=1)
        r = self.client.post(self.url, data)
        eq_(r.context['user_form'].non_form_errors(),
            ['At least one author must be listed.'])

    def test_must_have_owner(self):
        f = self.client.get(self.url).context['user_form'].initial_forms[0]
        f.initial['role'] = amo.AUTHOR_ROLE_DEV
        data = self.formset(f.initial, initial_count=1)
        r = self.client.post(self.url, data)
        eq_(r.context['user_form'].non_form_errors(),
            ['Must have at least one owner.'])

    def test_must_have_owner_delete(self):
        f = self.client.get(self.url).context['user_form'].initial_forms[0]
        f.initial['DELETE'] = True
        data = self.formset(f.initial, initial_count=1)
        r = self.client.post(self.url, data)
        eq_(r.context['user_form'].non_form_errors(),
            ['Must have at least one owner.'])

    def test_author_support_role(self):
        # Tests that the support role shows up when the allow-refund switch
        # is active.
        switch = waffle.models.Switch.objects.create(name='allow-refund',
                                                     active=True)
        res = self.client.get(self.url)
        eq_(res.status_code, 200)
        doc = pq(res.content)
        role_str = doc('#id_form-0-role').text()
        assert 'Support' in role_str, ('Support not in roles. Contained: %s' %
                                       role_str)
        switch.active = False
        switch.save()
        res = self.client.get(self.url)
        eq_(res.status_code, 200)
        doc = pq(res.content)
        assert not 'Support' in doc('#id_form-0-role').text(), (
            "Hey, the Support role shouldn't be here!")


class TestEditWebappAuthors(amo.tests.TestCase):
    fixtures = ['base/apps', 'base/users', 'webapps/337141-steamcube']

    def setUp(self):
        self.client.login(username='admin@mozilla.com', password='password')
        self.webapp = Addon.objects.get(id=337141)
        self.url = self.webapp.get_dev_url('owner')

    def test_apps_context(self):
        r = self.client.get(self.url)
        eq_(r.context['webapp'], True)
        assert 'license_form' not in r.context, 'Unexpected license form'
        assert 'policy_form' not in r.context, 'Unexpected policy form'
        doc = pq(r.content)
        eq_(doc('#edit-addon-nav ul').eq(0).find('a').eq(1).attr('href'),
            self.url)

    def test_success_add_owner(self):
        u = UserProfile.objects.get(id=999)
        u = dict(user=u.email, listed=True, role=amo.AUTHOR_ROLE_OWNER,
                 position=0)
        r = self.client.post(self.url, formset(u, initial_count=0))
        self.assertRedirects(r, self.url, 302)
        owners = (AddonUser.objects.filter(addon=self.webapp.id)
                  .values_list('user', flat=True))
        eq_(list(owners), [31337, 999])


class TestDeveloperRoleAccess(amo.tests.TestCase):
    fixtures = ['base/users', 'webapps/337141-steamcube']

    def setUp(self):
        self.client.login(username='regular@mozilla.com', password='password')
        self.webapp = Addon.objects.get(pk=337141)
        self.webapp.update(premium_type=amo.ADDON_PREMIUM)

        user = UserProfile.objects.get(email='regular@mozilla.com')
        AddonUser.objects.create(addon=self.webapp, user=user,
                                 role=amo.AUTHOR_ROLE_DEV)

    def _check_it(self, url):
        res = self.client.get(url, follow=True)
        eq_(res.status_code, 200)
        # Weak sauce. But pq('body.no-edit') or
        # pq('body').hasClass('no-edit') doesn't work.
        assert 'no-edit' in res.content, ("%s is editable by a developer but "
                                          "shouldn't be" % url)
        res = self.client.post(url)
        eq_(res.status_code, 403)

    def test_urls(self):
        urls = ['owner', 'payments', 'paypal_setup']
        for url in urls:
            self._check_it(self.webapp.get_dev_url(url))

        waffle.models.Switch.objects.create(name='in-app-payments',
                                            active=True)
        self.webapp.update(premium_type=amo.ADDON_PREMIUM_INAPP)
        self._check_it(self.webapp.get_dev_url('in_app_config'))

    def test_disable(self):
        res = self.client.get(self.webapp.get_dev_url('versions'))
        doc = pq(res.content)
        eq_(doc('#delete-addon').length, 0)
        eq_(doc('#disable-addon').length, 1)

    def test_enable(self):
        self.webapp.update(disabled_by_user=True)
        res = self.client.get(self.webapp.get_dev_url('versions'))
        doc = pq(res.content)
        eq_(doc('#delete-addon').length, 0)
        eq_(doc('#enable-addon').length, 1)
