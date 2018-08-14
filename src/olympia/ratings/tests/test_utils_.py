# -*- coding: utf-8 -*-
from django.test import RequestFactory

import mock
import pytest
from waffle.testutils import override_switch

from olympia.amo.tests import addon_factory, user_factory
from olympia.ratings.models import Rating
from olympia.ratings.utils import maybe_check_with_akismet

@pytest.mark.django_db
@pytest.mark.parametrize(
    'body,pre_save_body,user_id,user_id_resp,waffle_enabled,is_checked',
    [
        (None, None, 123, 123, True, False),  # missing body
        ('', None, 123, 123, True, False),    # empty body
        ('a', 'a', 123, 123, True, False),    # unchanged body
        ('a', None, 123, 123, True, True),    # adding body for the first time
        ('a', 'b', 123, 123, True, True),     # changed body

        ('a', 'b', 123, 321, True, False),     # different user responsible
        ('a', 'b', 123, None, True, False),   # no user responsible
        ('a', 'b', 123, 321, False, False),     # waffle off
    ])
def test_maybe_check_with_akismet(body, pre_save_body, user_id,
                                  user_id_resp, waffle_enabled, is_checked):
    user = user_factory(
        id=user_id, username='u%s' % user_id, email='%s@e' % user_id)
    rating_kw = {
        'addon': addon_factory(),
        'user': user,
        'rating': 4,
        'body': body,
        'ip_address': '1.2.3.4'}

    if user_id_resp:
        rating_kw['user_responsible'] = (
            user if user_id_resp == user_id
            else user_factory(
                id=user_id_resp, username='u%s' % user_id_resp,
                email='%s@e' % user_id_resp))

    rating = Rating.objects.create(**rating_kw)
    request = RequestFactory().get('/')

    with mock.patch('olympia.ratings.utils.check_with_akismet.delay') as cmock:
        with override_switch('akismet-spam-check', active=waffle_enabled):
            result = maybe_check_with_akismet(request, rating, pre_save_body)
            assert result == is_checked
            if is_checked:
                cmock.assert_called()
            else:
                cmock.assert_not_called()
