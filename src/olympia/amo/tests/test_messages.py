# -*- coding: utf-8 -*-
import pytest

import django.contrib.messages as django_messages

from django.contrib.messages.storage import default_storage
from django.http import HttpRequest
from django.template import loader
from django.utils.translation import ugettext

from olympia.amo.messages import _make_message, info


pytestmark = pytest.mark.django_db


def test_xss():

    title = "<script>alert(1)</script>"
    message = "<script>alert(2)</script>"

    r = _make_message(title)
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in r
    r = _make_message(None, message)
    assert "&lt;script&gt;alert(2)&lt;/script&gt;" in r

    r = _make_message(title, title_safe=True)
    assert "<script>alert(1)</script>" in r
    r = _make_message(None, message, message_safe=True)
    assert "<script>alert(2)</script>" in r

    # Make sure safe flags are independent
    r = _make_message(title, message_safe=True)
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in r
    r = _make_message(None, message, title_safe=True)
    assert "&lt;script&gt;alert(2)&lt;/script&gt;" in r


def test_no_dupes():
    """Test that duplicate messages aren't saved."""
    request = HttpRequest()
    setattr(request, '_messages', default_storage(request))

    info(request, 'Title', 'Body')
    info(request, 'Title', 'Body')
    info(request, 'Another Title', 'Another Body')

    storage = django_messages.get_messages(request)
    assert len(storage) == 2, 'Too few or too many messages recorded.'


def test_l10n_dups():
    """Test that L10n values are preserved."""
    request = HttpRequest()
    setattr(request, '_messages', default_storage(request))

    info(request, ugettext('Title'), ugettext('Body'))
    info(request, ugettext('Title'), ugettext('Body'))
    info(request, ugettext('Another Title'), ugettext('Another Body'))

    storage = django_messages.get_messages(request)
    assert len(storage) == 2, 'Too few or too many messages recorded.'


def test_unicode_dups():
    """Test that unicode values are preserved."""
    request = HttpRequest()
    setattr(request, '_messages', default_storage(request))

    info(request, u'Titlé', u'Body')
    info(request, u'Titlé', u'Body')
    info(request, u'Another Titlé', u'Another Body')

    storage = django_messages.get_messages(request)
    assert len(storage) == 2, 'Too few or too many messages recorded.'


def test_html_rendered_properly():
    """Html markup is properly displayed in final template."""
    request = HttpRequest()
    setattr(request, '_messages', default_storage(request))

    # This will call _file_message, which in turn calls _make_message, which in
    # turn renders the message_content.html template, which adds html markup.
    # We want to make sure this markup reaches the final rendering unescaped.
    info(request, 'Title', 'Body')

    messages = django_messages.get_messages(request)

    template = loader.get_template('messages.html')
    html = template.render({'messages': messages})
    assert "<h2>" in html  # The html from _make_message is not escaped.
