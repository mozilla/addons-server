#!/usr/bin/env python
# -*- coding: utf-8 -*-
from setuptools import setup, find_packages


setup(
    name='olympia',
    version='0.1.0',
    description='This is https://addons.mozilla.org (AMO)',
    author='The Mozilla Team',
    author_email='amo-developers@mozilla.org',
    url='https://addons.mozilla.org/',
    package_dir={'': 'src'},
    packages=find_packages('src'),
    include_package_data=True,
    test_suite='.',
    zip_safe=False,
    classifiers=[
        'Development Status :: 5 - Production/Stable',
        'Environment :: Web Environment',
        'Intended Audience :: End Users/Desktop',
        'License :: OSI Approved :: Mozilla Public License',
        'Operating System :: POSIX',
        'Programming Language :: Python',
        'Framework :: Django',
        'Topic :: Internet :: WWW/HTTP :: Browsers',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.6',
    ],
)
