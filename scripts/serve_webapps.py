#!/usr/bin/env python
"""Serves .webapp/.json manifest files from the working directory."""
import logging
import optparse
import os
from wsgiref import simple_server


log = logging.getLogger(__name__)
document_root = os.getcwd()


def fileapp(environ, start_response):
    path_info = environ['PATH_INFO']
    if path_info.startswith('/'):
        path_info = path_info[1:]  # make relative
    full_path = os.path.join(document_root, path_info)
    content_type = 'text/html'
    if full_path == '':
        full_path = '.'  # must be working dir
    if path_info == "" or path_info.endswith('/') or os.path.isdir(full_path):
        # directory listing:
        out = ['<html><head></head><body><ul>']
        for filename in os.listdir(full_path):
            if filename.startswith('.'):
                continue
            if os.path.isdir(os.path.join(full_path, filename)):
                filename = filename + '/'
            out.append('<li><a href="%s">%s</a></li>' % (filename, filename))
        out.append("</ul></body></html>")
        body = "".join(out)
    else:
        f = open(full_path, 'r')
        if full_path.endswith('.webapp') or full_path.endswith('.json'):
            content_type = 'application/x-web-app-manifest+json'
        body = f.read()  # optimized for small files :)

    start_response('200 OK', [('Content-Type', content_type),
                              ('Content-Length', str(len(body)))])
    return [body]


def main():
    p = optparse.OptionParser(usage="%prog\n\n" + __doc__)
    p.add_option("--port", help="Port to run server on.  Default: %default",
                 default=8090, type=int)
    (options, args) = p.parse_args()
    logging.basicConfig(level=logging.DEBUG,
                        format='[%(asctime)s] %(message)s')
    log.info("starting webserver at http://localhost:%s/", options.port)
    httpd = simple_server.WSGIServer(('', options.port),
                                     simple_server.WSGIRequestHandler)
    httpd.set_app(fileapp)
    httpd.serve_forever()


if __name__ == '__main__':
    main()
