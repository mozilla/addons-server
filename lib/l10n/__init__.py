import gettext
import re

from django.conf import settings
from django.utils.importlib import import_module
from django.utils.thread_support import currentThread
from django.utils.translation import (trans_real as django_trans,
                                      ugettext as django_ugettext,
                                      ungettext as django_nugettext)


def ugettext(message, context=None):
    new_message = strip_whitespace(message)
    if context:
        new_message = _add_context(context, new_message)
    ret = django_ugettext(new_message)

    if ret == new_message:
        return message
    return ret


def ungettext(singular, plural, number, context=None):
    new_singular = strip_whitespace(singular)
    new_plural = strip_whitespace(plural)
    if context:
        new_singular = _add_context(context, new_singular)
        new_plural = _add_context(context, new_plural)
    ret = django_nugettext(new_singular, new_plural, number)

    # If the context isn't found, the string is returned as it was sent
    if ret == new_singular:
        return singular
    elif ret == new_plural:
        return plural
    return ret


def _add_context(context, message):
    # \x04 is a magic gettext number.
    return u"%s\x04%s" % (context, message)


def strip_whitespace(message):
    return re.compile(r'\s+', re.UNICODE).sub(' ', message).strip()


def activate(locale):
    """ Override django's utils.translation.activate().  Django forces files
    to be named django.mo (http://code.djangoproject.com/ticket/6376).  Since
    that's dumb and we want to be able to load different files depending on
    what part of the site the user is in, we'll make our own function here.
    """
    # XXX TODO: When it comes time to load .mo files on the fly and merge
    # them, this is the place to do it.  We'll also need to implement our own
    # caching since the _translations stuff is built on a per locale basis,
    # not per locale + some key
    import jingo

    # Django caches the translation objects here
    t = django_trans._translations.get(locale, None)
    if t is not None:
        return t

    # Django's activate() simply calls translation() and adds it to a global.
    # We'll do the same here, first calling django's translation() so it can
    # do everything it needs to do, and then calling gettext directly to
    # load the rest.
    t = django_trans.translation(locale)
    try:
        """When trying to load css, js, and images through the Django server
        gettext() throws an exception saying it can't find the .mo files.  I
        suspect this has something to do with Django trying not to load
        extra stuff for requests that won't need it.  I do know that I don't
        want to try to debug it.  This is what Django does in their function
        also.
        """
        #If you've got extra .mo files to load, this is the place.
        path = import_module(settings.SETTINGS_MODULE).path
        bonus = gettext.translation('messages', path('locale'), [locale],
                                    django_trans.DjangoTranslation)
        t.merge(bonus)
    except IOError:
        pass

    django_trans._active[currentThread()] = t

    jingo.env.install_gettext_translations(t)


def deactivate_all():
    """ Override django's utils.translation.deactivate_all().  Django continues
    to cache a catalog even if you call their deactivate_all().
    """
    django_trans.deactivate_all()
    django_trans._translations = {}
