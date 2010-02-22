import gettext
import re

from django.utils.thread_support import currentThread
from django.utils.translation import trans_real as django_trans
from django.utils.translation import ugettext as django_ugettext
from django.utils.translation import ungettext as django_nugettext

from settings import path


def ugettext(message, context=None):
    message = strip_whitespace(message)
    if context:
        message = _add_context(context, message)
    return django_ugettext(message)


def ungettext(singular, plural, number, context=None):
    singular = strip_whitespace(singular)
    plural = strip_whitespace(plural)
    if context:
        singular = _add_context(context, singular)
        plural = _add_context(context, plural)
    return django_nugettext(singular, plural, number)


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
        #XXX Only load Dev CP / Admin stuff when it's useful
        bonus = gettext.translation('messages', path('locale'), [locale],
                                    django_trans.DjangoTranslation)
        t.merge(bonus)
    except IOError:
        pass

    django_trans._active[currentThread()] = t

    jingo.env.install_gettext_translations(t)
