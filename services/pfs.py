import re
import sys
from collections import defaultdict
from email.Utils import formatdate
from string import Template
from time import time
from urlparse import parse_qsl

import jinja2

import olympia.core.logger

from utils import log_configure

# This has to be imported after the settings so statsd knows where to log to.
from django_statsd.clients import statsd

JAVA_PLUGIN_SUMO_URL = (
    'https://support.mozilla.org/'
    'kb/use-java-plugin-to-view-interactive-content')


# Go configure the log.
log_configure()

error_log = olympia.core.logger.getLogger('z.pfs')

xml_template = """\
<?xml version="1.0"?>
<RDF:RDF xmlns:RDF="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:pfs="http://www.mozilla.org/2004/pfs-rdf#">

  <RDF:Description about="urn:mozilla:plugin-results:$mimetype">
    <pfs:plugins><RDF:Seq>
        <RDF:li resource="urn:mozilla:plugin"/>
    </RDF:Seq></pfs:plugins>
  </RDF:Description>

  <RDF:Description about="urn:mozilla:plugin">
    <pfs:updates><RDF:Seq>
        <RDF:li resource="urn:mozilla:plugin:updates"/>
    </RDF:Seq></pfs:updates>
  </RDF:Description>

  <RDF:Description about="urn:mozilla:plugin:updates">
    <pfs:name>$name</pfs:name>
    <pfs:requestedMimetype>$mimetype</pfs:requestedMimetype>
    <pfs:manualInstallationURL>$manualInstallationURL</pfs:manualInstallationURL>
  </RDF:Description>

</RDF:RDF>
"""

quicktime_re = re.compile(
    r'^image/(pict|png|tiff|x-(macpaint|pict|png|quicktime|sgi|targa|tiff))$')
java_re = re.compile(r'^application/x-java-.*$')


def get_output(data):
    g = defaultdict(str, [(k, jinja2.escape(v)) for k, v in data.iteritems()])

    required = ['mimetype', 'appID', 'appVersion', 'clientOS', 'chromeLocale']

    # Some defaults we override depending on what we find below.
    plugin = dict(mimetype='-1', name='-1',
                  manualInstallationURL='')

    # Special case for mimetype if they are provided.
    plugin['mimetype'] = g['mimetype'] or '-1'

    output = Template(xml_template)

    for s in required:
        if s not in data:
            # A sort of 404, matching what was returned in the original PHP.
            return output.substitute(plugin)

    # Figure out what plugins we've got, and what plugins we know where
    # to get.

    # Begin our huge and embarrassing if-else statement.
    if g['mimetype'] in ['application/x-shockwave-flash',
                         'application/futuresplash']:
        # Tell the user where they can go to get the installer.

        plugin.update(
            name='Adobe Flash Player',
            manualInstallationURL='https://get.adobe.com/flashplayer/')

    elif g['mimetype'] == 'application/x-director':
        plugin.update(
            name='Adobe Shockwave Player',
            manualInstallationURL='https://get.adobe.com/shockwave/')
    elif quicktime_re.match(g['mimetype']):
        # Well, we don't have a plugin that can handle any of those
        # mimetypes, but the Apple Quicktime plugin can. Point the user to
        # the Quicktime download page.

        plugin.update(
            name='Apple Quicktime',
            InstallerShowsUI='true',
            manualInstallationURL='https://www.apple.com/quicktime/download/')

    elif java_re.match(g['mimetype']):
        # We don't want to link users directly to the Java plugin because
        # we want to warn them about ongoing security problems first. Link
        # to SUMO.
        plugin.update(
            name='Java Runtime Environment',
            manualInstallationURL=JAVA_PLUGIN_SUMO_URL)

    # End ridiculously huge and embarrassing if-else block.
    return output.substitute(plugin)


def format_date(secs):
    return '%s GMT' % formatdate(time() + secs)[:25]


def get_headers(length):
    return [('Content-Type', 'text/xml; charset=utf-8'),
            ('Cache-Control', 'public, max-age=3600'),
            ('Last-Modified', format_date(0)),
            ('Expires', format_date(3600)),
            ('Content-Length', str(length))]


def log_exception(data):
    (typ, value, traceback) = sys.exc_info()
    error_log.error(u'Type: %s, %s. Query: %s' % (typ, value, data))


def application(environ, start_response):
    status = '200 OK'

    with statsd.timer('services.pfs'):
        data = dict(parse_qsl(environ['QUERY_STRING']))
        try:
            output = get_output(data).encode('utf-8')
            start_response(status, get_headers(len(output)))
        except:
            log_exception(data)
            raise
        return [output]
