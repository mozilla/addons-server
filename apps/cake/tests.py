# -*- coding: utf-8 -*-
from django.contrib.auth.models import AnonymousUser, User
from django.db import IntegrityError

from mock import Mock, patch
from nose.tools import eq_
from test_utils import TestCase
from pyquery import PyQuery as pq

import amo
from users.models import UserProfile
from .backends import SessionBackend
from .models import Session
from .helpers import cake_csrf_token, remora_url


class CakeTestCase(TestCase):

    fixtures = ['cake/sessions', 'base/global-stats']

    def test_cookie_cleaner(self):
        "Test that this removes locale-only cookie."
        c = self.client
        c.cookies['locale-only'] = 'XENOPHOBIA 4 EVAR'
        r = c.get('/', follow=True)
        eq_(r.cookies.get('locale-only'), None)

    def test_login(self):
        """
        Given a known remora cookie, can we visit the homepage and appear
        logged in?
        """
        # log in using cookie -
        client = self.client
        client.cookies['AMOv3'] = "17f051c99f083244bf653d5798111216"
        response = client.get('/en-US/firefox/')
        self.assertContains(response, 'Welcome, Scott')

        # test that the data copied over correctly.
        profile = UserProfile.objects.get(pk=1)
        user = profile.user

        self.assertEqual(profile.email, user.username)
        self.assertEqual(profile.email, user.email)
        self.assertEqual(profile.created, user.date_joined)
        self.assertEqual(profile.password, user.password)
        self.assertEqual(profile.id, user.id)

    def test_stale_session(self):
        # what happens if the session we reference is expired
        session = Session.objects.get(pk='27f051c99f083244bf653d5798111216')
        self.assertEqual(False, self.client.login(session=session))
        # check that it's no longer in the db
        f = lambda: Session.objects.get(pk='27f051c99f083244bf653d5798111216')
        self.assertRaises(Session.DoesNotExist, f)

    def test_invalid_session_reference(self):
        self.assertEqual(False, self.client.login(session=Session(pk='abcd')))

    def test_invalid_session_data(self):
        # what happens if the session we reference refers to a missing user
        session = Session.objects.get(pk='37f051c99f083244bf653d5798111216')
        self.assertEqual(False, self.client.login(session=session))
        # check that it's no longer in the db
        f = lambda: Session.objects.get(pk='37f051c99f083244bf653d5798111216')
        self.assertRaises(Session.DoesNotExist, f)

    def test_broken_session_data(self):
        """Bug 553397"""
        backend = SessionBackend()
        session = Session.objects.get(pk='17f051c99f083244bf653d5798111216')
        session.data = session.data.replace('"', 'breakme', 5)
        self.assertEqual(None, backend.authenticate(session=session))

    def test_utf8_session_data(self):
        """Bug 566377."""
        backend = SessionBackend()
        session = Session.objects.get(pk='47f051c99f083244bf653d5798111216')
        user = backend.authenticate(session=session)
        assert user != None, "We should get a user."

    def test_backend_get_user(self):
        s = SessionBackend()
        self.assertEqual(None, s.get_user(12))

    def test_middleware_invalid_session(self):
        client = self.client
        client.cookies['AMOv3'] = "badcookie"
        response = client.get('/en-US/firefox/')
        assert isinstance(response.context['user'], AnonymousUser)

    def test_logout(self):
        # login with a cookie and verify we are logged in
        client = self.client
        client.cookies['AMOv3'] = "17f051c99f083244bf653d5798111216"
        response = client.get('/en-US/firefox/')
        self.assertContains(response, 'Welcome, Scott')
        # logout and verify we are logged out and our AMOv3 cookie is gone
        response = client.get('/en-US/firefox/users/logout')
        response = client.get('/en-US/firefox/')

        assert isinstance(response.context['user'], AnonymousUser)
        self.assertEqual(client.cookies.get('AMOv3').value, '')

    @patch('django.db.models.fields.related.'
           'ReverseSingleRelatedObjectDescriptor.__get__')
    def test_backend_profile_exceptions(self, p_mock):
        # We have a legitimate profile, but for some reason the user_id is
        # phony.
        s = SessionBackend()
        backend = SessionBackend()
        session = Session.objects.get(pk='17f051c99f083244bf653d5798111216')

        p_mock.side_effect = User.DoesNotExist()
        eq_(None, s.authenticate(session))

        p_mock.side_effect = IntegrityError()
        eq_(None, s.authenticate(session))

        p_mock.side_effect = Exception()
        eq_(None, s.authenticate(session))


class TestHelpers(TestCase):

    fixtures = ['cake/sessions']

    def test_csrf_token(self):
        mysessionid = "17f051c99f083244bf653d5798111216"

        s = SessionBackend()
        session = Session.objects.get(pk=mysessionid)
        user = s.authenticate(session=session)

        request = Mock()
        request.user = user
        request.COOKIES = {'AMOv3': mysessionid}
        ctx = {'request': request}

        doc = pq(cake_csrf_token(ctx))
        self.assert_(doc.html())
        self.assert_(doc('input').attr('value'))

    def test_csrf_token_nosession(self):
        """No session cookie, no Cake CSRF token."""
        mysessionid = "17f051c99f083244bf653d5798111216"

        s = SessionBackend()
        session = Session.objects.get(pk=mysessionid)
        user = s.authenticate(session=session)

        request = Mock()
        request.user = user
        request.COOKIES = {}
        ctx = {'request': request}

        token = cake_csrf_token(ctx)
        assert not token

    def test_remora_url(self):
        """Build remora URLs."""
        ctx = {
            'LANG': 'en-us',
            'APP': amo.FIREFOX}
        url = remora_url(ctx, '/addon/1234')
        eq_(url, '/en-US/firefox/addon/1234')

        url = remora_url(ctx, '/addon/1234', 'pt-BR', 'thunderbird')
        eq_(url, '/pt-BR/thunderbird/addon/1234')

        url = remora_url(ctx, '/devhub/something', app='', prefix='remora')
        eq_(url, '/remora/en-US/devhub/something')

        # UTF-8 strings
        url = remora_url(ctx, u'/tags/Hallo und tschüß')
        eq_(url, '/en-US/firefox/tags/Hallo%20und%20tsch%C3%BC%C3%9F')

        # Trailing slashes are kept if present.
        eq_(remora_url(ctx, '/foo'), '/en-US/firefox/foo')
        eq_(remora_url(ctx, '/foo/'), '/en-US/firefox/foo/')
