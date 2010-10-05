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


class DELICIOUS(ServiceBase):
    """see: http://delicious.com/help/savebuttons"""
    shortname = 'delicious'
    label = _(u'Add to Delicious')
    url = (u'http://delicious.com/save?url={url}&title={title}'
            '&notes={description}')


class DIGG(ServiceBase):
    """see: http://digg.com/tools/integrate#3"""
    shortname = 'digg'
    label = _(u'Digg this!')
    url = (u'http://digg.com/submit?url={url}&title={title}&bodytext='
            '{description}&media=news&topic=tech_news')

    @staticmethod
    def count_term(count):
        return ngettext('{0} digg', '{0} diggs', count).format(count)


class FACEBOOK(ServiceBase):
    """see: http://www.facebook.com/share_options.php"""
    shortname = 'facebook'
    label = _(u'Post to Facebook')
    url = u'http://www.facebook.com/share.php?u={url}&t={title}'


class FRIENDFEED(ServiceBase):
    """see: http://friendfeed.com/embed/link"""
    shortname = 'friendfeed'
    label = _(u'Share on FriendFeed')
    url = u'http://friendfeed.com/?url={url}&title={title}'

    @staticmethod
    def count_term(count):
        return ngettext('{0} share', '{0} shares', count).format(count)


class MYSPACE(ServiceBase):
    """see: http://www.myspace.com/posttomyspace"""
    shortname = 'myspace'
    label = _(u'Post to MySpace')
    url = (u'http://www.myspace.com/index.cfm?fuseaction=postto&t={title}'
            '&c={description}&u={url}&l=1')


class TWITTER(ServiceBase):
    shortname = 'twitter'
    label = _(u'Post to Twitter')
    url = u'https://twitter.com/home?status={title}%20{url}'

    @staticmethod
    def count_term(count):
        return ngettext('{0} tweet', '{0} tweets', count).format(count)


SERVICES_LIST = [DIGG, FACEBOOK, DELICIOUS, MYSPACE, FRIENDFEED, TWITTER]
SERVICES = dict((service.shortname, service) for service in SERVICES_LIST)
