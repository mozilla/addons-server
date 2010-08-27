import httplib
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
    except (urllib2.URLError, httplib.HTTPException), e:
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
    # An update to the feed has include <content:encoded>, but we'd have to use
    # etree for that and I don't want to redo it right now.
    try:
        p = pq(url=page.permalink)
    except urllib2.URLError, e:
        log.error("Couldn't open (%s): %s" % (url, e))
        return

    # We want the first image in the post
    image = p('.entry-content').find('img:first').attr('src')

    if image:
        offset = image.find('/uploads')

    if not image or offset == -1:
        log.error("Couldn't find a featured image for blog post (%s). "
                  "Fligtar said this would never happen." % page.permalink)
        return

    # Image sources look like this:
    #    http://rockyourfirefox.com/rockyourfirefox_content/
    #                       uploads/2010/04/Nature-SprinG-Persona1-672x367.jpg
    # This turns the above example into:
    #    /uploads/2010/04/Nature-SprinG-Persona1-672x367.jpg
    # which we'll load off of static.amo; bug 561160
    page.image = image[offset:]

    page.save()
