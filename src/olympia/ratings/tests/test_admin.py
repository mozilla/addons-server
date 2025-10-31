from django.urls import reverse

from pyquery import PyQuery as pq

from olympia import core
from olympia.addons.models import Addon
from olympia.amo.tests import TestCase, addon_factory, user_factory
from olympia.ratings.models import Rating
from olympia.users.models import UserProfile


class TestRatingAdmin(TestCase):
    fixtures = ['base/addon_3615', 'base/user_999']

    def setUp(self):
        self.addon = Addon.objects.get(pk=3615)
        self.rating = Rating.objects.create(
            addon=self.addon, body='Bär', rating=5, user=user_factory()
        )
        self.detail_url = reverse('admin:ratings_rating_change', args=(self.rating.pk,))
        self.list_url = reverse('admin:ratings_rating_changelist')
        self.delete_url = reverse('admin:ratings_rating_delete', args=(self.rating.pk,))
        self.user = UserProfile.objects.get(pk=999)

    def test_list(self):
        addon = Addon.objects.get(pk=3615)

        # Create a few more ratings.
        Rating.objects.create(
            addon=addon,
            user=user_factory(),
            rating=4,
            body='Lôrem ipsum dolor sit amet, per at melius fuisset '
            'invidunt, ea facete aperiam his. Et cum iusto detracto, '
            'nam atqui nostrum no, eum altera indoctum ad. Has ut duis '
            'tractatos laboramus, cum sale primis ei. Ius inimicus '
            'intellegebat ea, mollis expetendis usu ei. Cetero aeterno '
            'nostrud eu për.',
        )
        Rating.objects.create(addon=addon, body=None, rating=5, user=user_factory())
        # Create a reply.
        Rating.objects.create(
            addon=addon, user=self.user, body='Réply', reply_to=self.rating
        )

        self.grant_permission(self.user, 'Ratings:Moderate')
        self.client.force_login(self.user)
        response = self.client.get(self.list_url, follow=True)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#result_list tbody tr').length == 4

        # Test truncated text while we're at it...
        content = response.content.decode('utf-8')
        assert (
            'Lôrem ipsum dolor sit amet, per at melius fuisset invidunt, ea '
            'facete aperiam his. Et cum iusto detracto, nam atqui nostrum no,'
            ' eum altera...' in content
        )
        # ... And add-on name display.
        assert str(self.addon.name) in content

        response = self.client.get(self.list_url, {'type': 'rating'}, follow=True)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#result_list tbody tr').length == 3

        response = self.client.get(self.list_url, {'type': 'reply'}, follow=True)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#result_list tbody tr').length == 1

    def test_filter_by_created(self):
        some_time_ago = self.days_ago(97).date()
        even_more_time_ago = self.days_ago(99).date()
        Rating.objects.create(
            addon=self.addon,
            body='Öld',
            rating=5,
            user=user_factory(),
            created=self.days_ago(98),
        )
        Rating.objects.create(
            addon=self.addon,
            body='Evên older',
            rating=5,
            user=user_factory(),
            created=self.days_ago(100),
        )
        data = {
            'created__range__gte': even_more_time_ago.isoformat(),
            'created__range__lte': some_time_ago.isoformat(),
        }
        self.grant_permission(self.user, 'Ratings:Moderate')
        self.client.force_login(self.user)
        response = self.client.get(self.list_url, data, follow=True)
        assert response.status_code == 200
        doc = pq(response.content.decode('utf-8'))
        assert doc('#result_list tbody tr').length == 1
        result_list_text = doc('#result_list tbody tr').text()
        assert 'Bär' not in result_list_text
        assert 'Evên older' not in result_list_text
        assert 'Öld' in result_list_text

        # Created filter should be selected. The rest shouldn't.
        lis = doc('#changelist-filter li.selected')
        # We've got 4 filters, so usually we'd get 4 selected list items
        # (because of the "All" default choice) but since 'created' is actually
        # 2 fields, and we have submitted both, we now have 5 expected items.
        assert len(lis) == 5
        assert lis.text().split() == ['All', 'All', 'All', 'From:', 'To:']
        elm = lis.eq(3).find('#id_created__range__gte')
        assert elm
        assert elm.attr('name') == 'created__range__gte'
        assert elm.attr('value') == even_more_time_ago.isoformat()
        elm = lis.eq(4).find('#id_created__range__lte')
        assert elm
        assert elm.attr('name') == 'created__range__lte'
        assert elm.attr('value') == some_time_ago.isoformat()

    def test_search_tooltip(self):
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Ratings:Moderate')
        self.client.force_login(user)
        response = self.client.get(self.list_url)
        doc = pq(response.content)
        assert doc('#searchbar-wrapper p').eq(0).text() == (
            'By default, search will be performed against body.'
        )
        assert doc('#searchbar-wrapper li').eq(0).text() == (
            'If the query contains only numeric terms, and there are 2 or more terms, '
            'search will be performed against addon instead.'
        )
        assert doc('#searchbar-wrapper li').eq(1).text() == (
            'If the query contains only IP addresses or networks, separated by commas, '
            'search will be performed against IP addresses recorded for ADD_RATING, '
            'EDIT_RATING.'
        )

    def test_search_by_ip(self):
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Ratings:Moderate')
        self.grant_permission(user, 'Ratings:Delete')
        self.client.force_login(user)

        addon = Addon.objects.get(pk=3615)
        second_addon = addon_factory(guid='@second_addon')
        third_addon = addon_factory(guid='@third_addon')
        fourth_addon = addon_factory(guid='@fourth_addon')

        core.set_user(user)
        with core.override_remote_addr_or_metadata(ip_address='4.8.15.16'):
            rating1 = Rating.objects.create(
                addon=addon,
                user=user_factory(),
                rating=1,
                body='Lôrem body 1',
            )
        with core.override_remote_addr_or_metadata(ip_address='4.8.15.16'):
            rating2 = Rating.objects.create(
                addon=addon,
                user=user_factory(),
                rating=2,
                body='Lôrem body 2',
            )
        with core.override_remote_addr_or_metadata(ip_address='125.1.2.3'):
            rating3 = Rating.objects.create(
                addon=second_addon,
                user=user_factory(),
                rating=5,
                body='Lôrem body 3',
            )
        with core.override_remote_addr_or_metadata(ip_address='4.8.15.16'):
            rating3.rating = 3
            rating3.save()
        with core.override_remote_addr_or_metadata(ip_address='125.5.6.7'):
            rating4 = Rating.objects.create(
                addon=third_addon,
                user=user_factory(),
                rating=4,
                body='Lôrem body 4',
            )

        with self.assertNumQueries(9):
            # - 2 savepoints
            # - 2 user and groups
            # - 1 addons from the query (for the addon filter)
            # - 1 count
            #    (show_full_result_count=False so we avoid the duplicate)
            # - 1 main query
            # - 1 addons
            # - 1 translations
            response = self.client.get(self.list_url, data={'q': '4.8.15.16'})
            assert response.status_code == 200
        doc = pq(response.content.decode('utf-8'))
        assert doc('#result_list tbody tr').length == 3
        result_list_text = doc('#result_list tbody tr').text()
        assert rating1.body in result_list_text
        assert rating2.body in result_list_text
        assert rating3.body in result_list_text
        assert rating4.body not in result_list_text
        addon_filter_options_text = (
            doc('#changelist-filter form').eq(1).find('option').text()
        )
        assert addon.guid in addon_filter_options_text
        assert second_addon.guid in addon_filter_options_text
        assert third_addon.guid not in addon_filter_options_text
        assert fourth_addon.guid not in addon_filter_options_text

        response = self.client.get(
            self.list_url, data={'q': '4.8.15.16', 'addon': [addon.pk, second_addon.pk]}
        )
        assert response.status_code == 200
        doc = pq(response.content.decode('utf-8'))
        assert doc('#result_list tbody tr').length == 3
        result_list_text = doc('#result_list tbody tr').text()
        assert rating1.body in result_list_text
        assert rating2.body in result_list_text
        assert rating3.body in result_list_text
        assert rating4.body not in result_list_text
        addon_filter_options_text = (
            doc('#changelist-filter form').eq(1).find('option').text()
        )
        assert addon.guid in addon_filter_options_text
        assert second_addon.guid in addon_filter_options_text
        assert third_addon.guid not in addon_filter_options_text
        assert fourth_addon.guid not in addon_filter_options_text

        # Make sure selected add-ons from the filter are going to be passed if
        # we add more filters on top. Let's inspect the first form (created
        # date filter) and the second link (first is to clear all filters).
        form = doc('#changelist-filter form').eq(0)
        hidden_inputs = form.find('input[type=hidden]')
        assert hidden_inputs[0].attrib == {
            'type': 'hidden',
            'name': 'q',
            'value': '4.8.15.16',
        }
        assert hidden_inputs[1].attrib == {
            'type': 'hidden',
            'name': 'addon',
            'value': str(addon.pk),
        }
        assert hidden_inputs[2].attrib == {
            'type': 'hidden',
            'name': 'addon',
            'value': str(second_addon.pk),
        }
        link = doc('#changelist-filter a').eq(1)
        assert (
            link.attr('href')
            == f'?q=4.8.15.16&addon={addon.pk}&addon={second_addon.pk}'
        )

        # Make sure selected add-ons filters are pre-selected too.
        addon_filter_options_text = (
            doc('#changelist-filter form').eq(1).find('option:selected').text()
        )
        assert addon.guid in addon_filter_options_text
        assert second_addon.guid in addon_filter_options_text

        # Sort by IP address using django admin built-in sort:
        # parameter is `o`, value is -5.3 because we're sorting by IP (the 5th
        # column) desc and then created (3rd column) asc. Note that our user
        # has permission to delete ratings, which adds a special column with
        # a checkbox to delete ratings, and it does count towards the column
        # index values.
        core.set_user(user)
        with core.override_remote_addr_or_metadata(ip_address='125.1.1.2'):
            Rating.objects.create(
                addon=addon_factory(),
                user=user_factory(),
                rating=4,
                body='Lôrem body 5',
            )
        response = self.client.get(self.list_url, data={'o': '-5.3'})
        assert response.status_code == 200
        doc = pq(response.content)
        assert len(doc('#result_list .field-id')) == 6
        assert doc('#result_list .field-known_ip_adresses').text().strip() == ' '.join(
            ['4.8.15.16', '4.8.15.16', '125.5.6.7', '125.1.2.3\n4.8.15.16 125.1.1.2']
        )

    def test_can_delete_on_changelist_while_sorting_by_ip(self):
        with core.override_remote_addr_or_metadata(ip_address='125.1.1.2'):
            rating2 = Rating.objects.create(
                addon=self.addon,
                user=user_factory(),
                rating=5,
                body='Lôrem Ipsûm',
            )
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Ratings:Delete')
        self.grant_permission(user, 'Ratings:Moderate')
        self.client.force_login(user)
        # Find link to sort by IP
        response = self.client.post(self.list_url, {'addon': self.addon.pk})
        doc = pq(response.content)
        query_string = doc('th.column-known_ip_adresses a').attr('href')
        assert query_string.startswith('?')
        data = {
            '_selected_action': str(self.rating.pk),
            'action': 'delete_selected',
            # post=yes emulates the "Yes, I'm sure" on the delete confirmation.
            'post': 'yes',
        }
        # Request delete confirmation page with the ordering query string.
        response = self.client.post(self.list_url + query_string, data)
        assert response.status_code == 302
        assert Rating.objects.count() == 1
        assert not Rating.objects.filter(pk=self.rating.pk).exists()
        assert Rating.objects.filter(pk=rating2.pk).exists()  # Untouched.

    def test_filter_by_created_only_from(self):
        not_long_ago = self.days_ago(2).date()
        Rating.objects.create(
            addon=self.addon,
            body='Öld',
            rating=5,
            user=user_factory(),
            created=self.days_ago(98),
        )
        Rating.objects.create(
            addon=self.addon,
            body='Evên older',
            rating=5,
            user=user_factory(),
            created=self.days_ago(100),
        )
        data = {
            'created__range__gte': not_long_ago.isoformat(),
        }
        self.grant_permission(self.user, 'Ratings:Moderate')
        self.client.force_login(self.user)
        response = self.client.get(self.list_url, data, follow=True)
        assert response.status_code == 200
        doc = pq(response.content.decode('utf-8'))
        assert doc('#result_list tbody tr').length == 1
        result_list_text = doc('#result_list tbody tr').text()
        assert 'Bär' in result_list_text
        assert 'Evên older' not in result_list_text
        assert 'Öld' not in result_list_text

        # Created filter should be selected. The rest shouldn't.
        lis = doc('#changelist-filter li.selected')
        # We should have 4 filters.
        assert len(lis) == 4
        assert lis.text().split() == ['All', 'All', 'All', 'From:']
        elm = lis.eq(3).find('#id_created__range__gte')
        assert elm
        assert elm.attr('name') == 'created__range__gte'
        assert elm.attr('value') == not_long_ago.isoformat()

    def test_filter_by_created_only_to(self):
        some_time_ago = self.days_ago(97).date()
        Rating.objects.create(
            addon=self.addon,
            body='Öld',
            rating=5,
            user=user_factory(),
            created=self.days_ago(98),
        )
        Rating.objects.create(
            addon=self.addon,
            body='Evên older',
            rating=5,
            user=user_factory(),
            created=self.days_ago(100),
        )
        data = {
            'created__range__lte': some_time_ago.isoformat(),
        }
        self.grant_permission(self.user, 'Ratings:Moderate')
        self.client.force_login(self.user)
        response = self.client.get(self.list_url, data, follow=True)
        assert response.status_code == 200
        doc = pq(response.content.decode('utf-8'))
        assert doc('#result_list tbody tr').length == 2
        result_list_text = doc('#result_list tbody tr').text()
        assert 'Bär' not in result_list_text
        assert 'Öld' in result_list_text
        assert 'Evên older' in result_list_text

        # Created filter should be selected. The rest shouldn't.
        lis = doc('#changelist-filter li.selected')
        # We should have 4 filters.
        assert len(lis) == 4
        assert lis.text().split() == ['All', 'All', 'All', 'To:']
        elm = lis.eq(3).find('#id_created__range__lte')
        assert elm
        assert elm.attr('name') == 'created__range__lte'
        assert elm.attr('value') == some_time_ago.isoformat()

    def test_list_queries(self):
        addon = Addon.objects.get(pk=3615)

        # Create a few more ratings.
        Rating.objects.create(
            addon=addon,
            user=user_factory(),
            rating=4,
            body='Lôrem ipsum dolor sit amet, per at melius fuisset '
            'invidunt, ea facete aperiam his. Et cum iusto detracto, '
            'nam atqui nostrum no, eum altera indoctum ad. Has ut duis '
            'tractatos laboramus, cum sale primis ei. Ius inimicus '
            'intellegebat ea, mollis expetendis usu ei. Cetero aeterno '
            'nostrud eu për.',
        )
        Rating.objects.create(addon=addon, body=None, rating=5, user=user_factory())
        # Create a reply.
        Rating.objects.create(
            addon=addon, user=self.user, body='Réply', reply_to=self.rating
        )

        self.grant_permission(self.user, 'Ratings:Moderate')
        self.client.force_login(self.user)
        with self.assertNumQueries(9):
            # - 2 Savepoint/release
            # - 2 user and its groups
            # - 1 COUNT(*)
            #     (show_full_result_count=False so we avoid the duplicate)
            # - 1 ratings themselves
            # - 1 ratings replies
            # - 1 related add-ons
            # - 1 related add-ons translations
            response = self.client.get(self.list_url, follow=True)
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#result_list tbody tr').length == 4

    def test_can_not_access_detail_without_ratings_moderate_permission(self):
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Addons:Edit')
        self.client.force_login(user)
        response = self.client.get(self.detail_url, follow=True)
        assert response.status_code == 403

    def test_can_not_delete_without_ratings_delete_permission(self):
        assert Rating.objects.count() == 1
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Ratings:Moderate')  # Not enough!
        self.client.force_login(user)
        response = self.client.get(self.delete_url, follow=True)
        assert response.status_code == 403
        response = self.client.post(self.delete_url, {'post': 'yes'}, follow=True)
        assert response.status_code == 403

        assert Rating.objects.count() == 1
        assert Rating.unfiltered.count() == 1

    def test_can_delete_with_ratings_delete_permission(self):
        assert Rating.objects.count() == 1
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Ratings:Delete')
        self.grant_permission(user, 'Ratings:Moderate')
        self.client.force_login(user)

        response = self.client.get(self.list_url, follow=True)
        assert response.status_code == 200
        assert b'Delete selected rating' in response.content

        response = self.client.get(self.delete_url, follow=True)
        assert response.status_code == 200
        assert b'Cannot delete rating' not in response.content
        response = self.client.post(self.delete_url, {'post': 'yes'}, follow=True)
        assert response.status_code == 200

        assert Rating.objects.count() == 0
        assert Rating.unfiltered.count() == 1

    def test_can_not_change_detail(self):
        user = user_factory(email='someone@mozilla.com')
        self.grant_permission(user, 'Ratings:Delete')
        self.grant_permission(user, 'Ratings:Moderate')
        self.client.force_login(user)

        response = self.client.get(self.detail_url, follow=True)
        assert response.status_code == 200
        assert b'Save' not in response.content

    def test_detail(self):
        user = UserProfile.objects.get(pk=999)
        self.grant_permission(user, 'Ratings:Delete')
        self.grant_permission(user, 'Ratings:Moderate')
        self.client.force_login(user)

        response = self.client.get(self.detail_url, follow=True)
        assert response.status_code == 200
