"""
Email sharing of add-ons and collections with various services.
"""
from tower import ugettext_lazy as _, ungettext as ngettext


# string replacements in URLs are: url, title, description
class ServiceBase(object):
    """Base class for sharing services."""

    @staticmethod
    def count_term(count):
        """Render this service's share count with the right term."""
        return ngettext('{0} post', '{0} posts', count).format(count)


class FACEBOOK(ServiceBase):
    """see: http://www.facebook.com/share_options.php"""
    shortname = 'facebook'
    label = _(u'Post to Facebook')
    url = u'http://www.facebook.com/share.php?u={url}&t={title}'


class TWITTER(ServiceBase):
    shortname = 'twitter'
    label = _(u'Tweet on Twitter')
    url = u'https://twitter.com/home?status={title}%20{url}'

    @staticmethod
    def count_term(count):
        return ngettext('{0} tweet', '{0} tweets', count).format(count)


class GOOGLEPLUS(ServiceBase):
    shortname = 'gplus'
    label = _(u'Share on g+')
    url = u'https://plus.google.com/share?url={url}'


class REDDIT(ServiceBase):
    shortname = 'Reddit'
    label = _(u'Post to Reddit')
    url = u'http://www.reddit.com/submit?url={url}&title = {title}'


class TUMBLR(ServiceBase):
    shortname = 'Tumblr'
    label = _(u'Post to Tumblr')
    url = u'http://www.tumblr.com/share/link?url={url}&name = {title}'


# These classes are place holders for localizers to add more locale-specific
# sharing services that are more appropriate for thier audience.
# For more information: https://wiki.mozilla.org/AMO:Localizers
class LOCALSERVICE1(ServiceBase):
    # L10n: Only change if you have reason! wiki.mozilla.org/AMO:Localizers
    shortname = _('localservice1')
    # L10n: Only change if you have reason! wiki.mozilla.org/AMO:Localizers
    label = _(u'Post to localservice1')
    # L10n: Only change if you have reason! wiki.mozilla.org/AMO:Localizers
    url = _(u'http://localservice1/?url={url}&title={title}')

    @staticmethod
    def count_term(count):
        # L10n: Only change if you have reason! wiki.mozilla.org/AMO:Localizers
        return ngettext('{0} post on localservice1',
                        '{0} posts on localservice1', count).format(count)


class LOCALSERVICE2(ServiceBase):
    # L10n: Only change if you have reason! wiki.mozilla.org/AMO:Localizers
    shortname = _('localservice2')
    # L10n: Only change if you have reason! wiki.mozilla.org/AMO:Localizers
    label = _(u'Post to localservice2')
    # L10n: Only change if you have reason! wiki.mozilla.org/AMO:Localizers
    url = _(u'http://localservice2/?url={url}&title={title}')

    @staticmethod
    def count_term(count):
        # L10n: Only change if you have reason! wiki.mozilla.org/AMO:Localizers
        return ngettext('{0} post on localservice2',
                        '{0} posts on localservice2', count).format(count)


class LOCALSERVICE3(ServiceBase):
    # L10n: Only change if you have reason! wiki.mozilla.org/AMO:Localizers
    shortname = _('localservice3')
    # L10n: Only change if you have reason! wiki.mozilla.org/AMO:Localizers
    label = _(u'Post to localservice3')
    # L10n: Only change if you have reason! wiki.mozilla.org/AMO:Localizers
    url = _(u'http://localservice3/?url={url}&title={title}')

    @staticmethod
    def count_term(count):
        # L10n: Only change if you have reason! wiki.mozilla.org/AMO:Localizers
        return ngettext('{0} post on localservice3',
                        '{0} posts on localservice3', count).format(count)


SERVICES_LIST = [FACEBOOK, TWITTER, GOOGLEPLUS, REDDIT, TUMBLR]
LOCAL_SERVICES_LIST = [LOCALSERVICE1, LOCALSERVICE2, LOCALSERVICE3]


def get_service(shortname):
    for service in SERVICES_LIST + LOCAL_SERVICES_LIST:
        if unicode(service.shortname) == shortname:
            return service


def get_services():
    services = SERVICES_LIST[:]
    services.extend([s for s in LOCAL_SERVICES_LIST
                     if not unicode(s.shortname).startswith(u'localservice')])
    return services
