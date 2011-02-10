from datetime import date
import urllib2

from django.conf import settings
from django.utils.http import urlencode

from celery.decorators import task


def make_source_url(request):
    """Responsys expects the URL in the format example.com/foo."""
    return request.get_host() + request.get_full_path()


@task
def subscribe(campaign, address, format='html', source_url='',
              lang='', country=''):
    """
    Subscribe a user to a list in responsys. There should be two
    fields within the Responsys system named by the "campaign"
    parameter: <campaign>_FLG and <campaign>_DATE.
    """

    data = {
        'LANG_LOCALE': lang,
        'COUNTRY_': country,
        'SOURCE_URL': source_url,
        'EMAIL_ADDRESS_': address,
        'EMAIL_FORMAT_': 'H' if format == 'html' else 'T',
        }

    data['%s_FLG' % campaign] = 'Y'
    data['%s_DATE' % campaign] = date.today().strftime('%Y-%m-%d')
    data['_ri_'] = settings.RESPONSYS_ID

    try:
        res = urllib2.urlopen('http://awesomeness.mozilla.org/pub/rf',
                              data=urlencode(data))
        return res.code == 200
    except urllib2.URLError:
        return False
