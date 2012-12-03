#!/usr/bin/env python
"""
Script to serve packaged app mini-manifest and zip files to ease development.

Change directory to the root of your packaged app directory and execute this
script. For example:

$ cd ~/myapp
$ python ~/serve_packaged_apps.py

"""
import json
import logging
import optparse
import os
import re
from StringIO import StringIO
from sys import exc_info
from traceback import format_tb
from wsgiref import simple_server
from zipfile import ZipFile, ZIP_DEFLATED


DEFAULT_ADDR = '0.0.0.0'
DEFAULT_PORT = '8888'
ROOT = os.getcwd()
NAME = os.path.basename(ROOT)


log = logging.getLogger(__name__)


def _absolutify(path):
    base_url = os.environ.get('BASE_URL', 'http://%s:%s/' % (DEFAULT_ADDR,
                                                             DEFAULT_PORT))
    return '%s%s/%s' % (base_url, NAME, path.rsplit('/', 1)[0])


def index(environ, start_response):
    context = {
        'manifest': _absolutify('manifest.webapp'),
        'package': _absolutify('package.zip'),
    }
    start_response('200 OK', [('Content-Type', 'text/html')])
    return ['<a href="%(manifest)s">%(manifest)s</a><br>'
            '<a href="%(package)s">%(package)s</a>' % context]


def manifest(environ, start_response):
    data = {
        'name': u'My app',
        'version': 1,
        'size': 1000,  # TODO
        'package_path': _absolutify('package.zip'),
    }
    start_response('200 OK', [('Content-Type', 'application/json')])
    return [json.dumps(data)]


def zip_file(environ, start_response):

    def _add_file(f, name, path):
        with open(path, 'r') as p:
            f.writestr(name, p.read())

    # Walk path, add all files to zip archive.
    sio = StringIO()
    with ZipFile(file=sio, mode='w', compression=ZIP_DEFLATED) as outfile:
        for path, dirs, files in os.walk(ROOT):
            for f in files:
                full_path = os.path.join(path, f)
                zip_path = full_path[len(ROOT) + 1:]  # +1 for the slash.
                _add_file(outfile, zip_path, full_path)

    sio.seek(0)
    start_response('200 OK', [('Content-Type', 'application/zip')])
    return sio.getvalue()


# Routing URLs.
URLS = [
    (r'^$', index),  # Index points to these other URLs.
    (r'manifest.webapp$', manifest),  # The mini-manifest.
    (r'package.zip$', zip_file),  # The zipped package.
]


def application(environ, start_response):
    path = environ.get('PATH_INFO', '').lstrip('/')
    for regex, callback in URLS:
        match = re.search(regex, path)
        if match is not None:
            environ['myapp.url_args'] = match.groups()
            return callback(environ, start_response)
    # If no URLs match, 404.
    start_response('404 NOT FOUND', [('Content-Type', 'text/plain')])
    return ['Not Found']


class ExceptionMiddleware(object):
    """Exception middleware to catch errors and show a useful traceback."""

    def __init__(self, app):
        self.app = app

    def __call__(self, environ, start_response):
        appiter = None
        # Call the application sending the output back unchanged. Catch any
        # exceptions that occur.
        try:
            appiter = self.app(environ, start_response)
            for item in appiter:
                yield item
        # If an exception occours we get the exception information and prepare
        # a traceback we can render.
        except:
            e_type, e_value, tb = exc_info()
            traceback = ['Traceback (most recent call last):']
            traceback += format_tb(tb)
            traceback.append('%s: %s' % (e_type.__name__, e_value))
            # We may or may have not started a response.
            try:
                start_response('500 INTERNAL SERVER ERROR', [('Content-Type',
                                                              'text/plain')])
            except:
                pass
            yield '\n'.join(traceback)

        if hasattr(appiter, 'close'):
            appiter.close()


if __name__ == '__main__':
    p = optparse.OptionParser(usage='%prog\n\n' + __doc__)
    p.add_option('--addr',
                 default=DEFAULT_ADDR,
                 help='Address to serve at. Default: %s' % DEFAULT_ADDR)
    p.add_option('--port',
                 default=DEFAULT_PORT,
                 help='Port to run server on.  Default: %s' % DEFAULT_PORT,
                 type=int)
    (options, args) = p.parse_args()
    logging.basicConfig(level=logging.DEBUG,
                        format='[%(asctime)s] %(message)s')

    base_url = 'http://%s:%s/' % (options.addr, options.port)
    log.info('Serving at %s' % base_url)
    os.environ['BASE_URL'] = base_url

    application = ExceptionMiddleware(application)

    server = simple_server.make_server(options.addr, options.port, application)
    server.serve_forever()
