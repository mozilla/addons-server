import time
import urllib2

import commonware.log
from pyquery import PyQuery as pq

import cronjobs

from .models import BlogCacheRyf

log = commonware.log.getLogger('z.cron')


@cronjobs.register
def fetch_ryf_blog():
    """Currently used in the discovery pane from the API.  This job queries
    rockyourfirefox.com and pulls the latest entry from the RSS feed. """

    url = "http://rockyourfirefox.com/feed/"
    try:
        p = pq(url=url)
    except urllib2.URLError, e:
        log.error("Couldn't open (%s): %s" % (url, e))
        return

    item = p('item:first')

    # There should only be one row in this table, ever.
    try:
        page = BlogCacheRyf.objects.all()[0]
    except IndexError:
        page = BlogCacheRyf()
    page.title = item('title').text()
    page.excerpt = item('description').text()
    page.permalink = item('link').text()

    rfc_2822_format = "%a, %d %b %Y %H:%M:%S +0000"
    t = time.strptime(item('pubDate').text(), rfc_2822_format)
    page.date_posted = time.strftime("%Y-%m-%d %H:%M:%S", t)

    # Another request because we have to get the image URL from the page. :-/
    try:
        p = pq(url=page.permalink)
    except urllib2.URLError, e:
        log.error("Couldn't open (%s): %s" % (url, e))
        return
    image = p('.main-image img').attr('src')

    offset = image.find('/uploads')

    if not image or offset == -1:
        log.error("Couldn't find a featured image for blog post (%s). "
                  "Fligtar said this would never happen." % page.permalink)

    # Image sources look like this:
    #    http://rockyourfirefox.com/rockyourfirefox_content/
    #                       uploads/2010/04/Nature-SprinG-Persona1-672x367.jpg
    # Hardcoding the length we're stripping doesn't seem great, but this is a
    # pretty specific job and I don't know how we'd do it better.  This turns
    # the above example into:
    #    /uploads/2010/04/Nature-SprinG-Persona1-672x367.jpg
    # which we'll load off of static.amo; bug 561160
    page.image = image[offset:]

    page.save()
