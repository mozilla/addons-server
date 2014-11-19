#!/usr/bin/env python

from distutils.core import setup

setup(name='Olympia',
      version='0.1dev',
      description='This is https://addons.mozilla.org (AMO)',
      author='The Mozilla Team',
      author_email='amo-developers@mozilla.org',
      url='https://addons.mozilla.org/',
      packages=['apps', 'lib'],
      classifiers=[
          'Development Status :: 5 - Production/Stable',
          'Environment :: Web Environment',
          'Intended Audience :: End Users/Desktop',
          'License :: OSI Approved :: Mozilla Public License',
          'Operating System :: POSIX',
          'Programming Language :: Python',
          'Topic :: Internet :: WWW/HTTP :: Browsers',
      ])
