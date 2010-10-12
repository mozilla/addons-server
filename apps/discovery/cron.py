import httplib
import os
import shutil
import time
import urllib2
from tempfile import NamedTemporaryFile

from django.conf import settings

import commonware.log
from pyquery import PyQuery as pq

import cronjobs

from .models import BlogCacheRyf

log = commonware.log.getLogger('z.cron')

RYF_IMAGE_PATH = os.path.join(settings.NETAPP_STORAGE, 'ryf')


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

    try:
        img = urllib2.urlopen(image)
    except urllib2.HTTPError, e:
        log.error("Error fetching ryf image: %s" % e)
        return

    img_tmp = NamedTemporaryFile(delete=False)
    img_tmp.write(img.read())
    img_tmp.close()

    image_basename = os.path.basename(image)

    if not os.path.exists(RYF_IMAGE_PATH):
        os.makedirs(RYF_IMAGE_PATH)
    shutil.move(img_tmp.name, os.path.join(RYF_IMAGE_PATH, image_basename))

    page.image = image_basename
    page.save()
