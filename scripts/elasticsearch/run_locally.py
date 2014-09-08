#!/usr/bin/env python
import os

if __name__ == '__main__':
    cf = os.path.join(os.path.dirname(__file__), 'elasticsearch.yml')
    cf = os.path.abspath(cf)
    os.system('elasticsearch -f -D es.config=%s' % cf)
