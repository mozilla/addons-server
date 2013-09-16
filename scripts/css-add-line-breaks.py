#!/usr/bin/env/python

import os
import re

CSS_DIR = '../media/css'
REGEX = re.compile('({\n(?:\s+[\w-]+: .*?;\n)+)(.*?{)', re.MULTILINE)


def get_css_filenames():
    filenames = []
    for root, dirs, files in os.walk(CSS_DIR):
        for f in files:
            if f.endswith('.styl') or f.endswith('.less'):
                filenames.append(os.path.join(root, f))
    return filenames


def add_linebreak_css(filename):
    f = open(filename, 'r+')
    contents = f.read()
    f.seek(0)
    f.write(REGEX.sub(r'\1\n\2', contents))
    f.truncate()


def run():
    for filename in get_css_filenames():
        add_linebreak_css(filename)


if __name__ == '__main__':
    run()
