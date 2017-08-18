#!/usr/bin/env python

import os
import uuid
import sys
import requests
import argparse
from multiprocessing.pool import ThreadPool as Pool

# Import olympia before bs4 to apply our safe xml monkey patch
sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'settings')
import django

django.setup()

from olympia import amo
from olympia.amo.tests import addon_factory, user_factory
from olympia.constants.categories import CATEGORIES
from olympia.versions.models import ApplicationsVersions
from olympia.addons.models import Addon, Category
from olympia.users.models import UserProfile

import bs4


ROOT_URL = 'https://addons.mozilla.org/en-US/firefox/'
INDEX_URL = ROOT_URL + '/extensions/'


class KeyboardInterruptError(Exception):
    pass


def get_max_pages(options):
    response = requests.get(INDEX_URL + '?sort=%s' % options.sort)
    soup = bs4.BeautifulSoup(response.text, 'lxml')
    return int(soup.select('nav.paginator p.num a')[1].get_text())


def get_addon_ids(options):
    pages = range(1, get_max_pages(options))

    def _get_ids_from_page(page_number):
        addon_ids = []
        print('fetching page %s' % page_number)
        response = requests.get(
            INDEX_URL,
            params={'sort': options.sort, 'page': page_number})

        soup = bs4.BeautifulSoup(response.text, 'lxml')

        for item in soup.select('div.items div.addon'):
            addon_ids.append(int(
                item.select('div.action div.install')[0].attrs.get('data-addon')
            ))
        return addon_ids

    if options.max:
        pages = pages[:options.max]

    print('fetch pages from 1 to %s' % max(pages))
    pool = Pool(options.workers)

    addon_ids = set()

    results = pool.map_async(_get_ids_from_page, pages)

    for result in results.get(20 * 60 * 60):
        addon_ids.update(set(result))

    pool.close()

    return addon_ids


def fetch_addon_data(options, addon_ids):
    print('fetch addon data')

    def _fetch_addon(id):
        print('fetch add-on %s' % id)
        addon_data = requests.get(ROOT_URL + '/api/v3/addons/addon/{}'.format(id)).json()

        reversed_type_choies = {v: k for k, v in amo.ADDON_TYPE_CHOICES_API.items()}

        if 'current_version' not in addon_data or 'files' not in addon_data['current_version']:
            return

        version = addon_data['current_version']
        file = version['files'][0]
        # TODO:
        # * license
        # * ratings
        # * tags
        # * previous
        # * android compat data

        if Addon.objects.filter(guid=addon_data['guid']).exists():
            print('%s already exists' % addon_data['guid'])
            return

        users = []

        for user in addon_data['authors']:
            try:
                users.append(UserProfile.objects.get(username=user['name']))
            except UserProfile.DoesNotExist:
                email = 'fake-prod-data%s@mozilla.com' % str(uuid.uuid4()).split('-')[0]
                users.append(user_factory(
                    username=user['name'],
                    email=email))

        addon_type = reversed_type_choies[addon_data['type']]

        if 'firefox' in addon_data['categories']:
            category = addon_data['categories']['firefox'][0]
        else:
            category = None

        if category not in CATEGORIES[amo.FIREFOX.id][addon_type]:
            category = None
            print('category %s' % category, 'not found')
        else:
            category = Category.from_static_category(
                CATEGORIES[amo.FIREFOX.id][addon_type][category],
                True)

        default_locale = addon_data['default_locale']
        name = addon_data['name'][default_locale]
        summary = addon_data['summary'][default_locale]

        print('create add-on %s' % name)

        addon = addon_factory(
            users=users,
            average_daily_users=addon_data['average_daily_users'],
            category=category,
            type=addon_type,
            guid=addon_data['guid'],
            slug=addon_data['slug'],
            name=name,
            summary=summary,
            file_kw={
                'hash': file['hash'],
                'status': amo.STATUS_CHOICES_API_LOOKUP[file['status']],
                'platform': amo.PLATFORM_DICT[file['platform']].id,
                'size': file['size'],
                'is_webextension': file['is_webextension'],
            },
            version_kw={
                'min_app_version': version['compatibility']['firefox']['min'],
                'max_app_version': version['compatibility']['firefox']['max'],
            },
            weekly_downloads=addon_data['weekly_downloads'],
            default_locale=default_locale
        )

    results = []
    pool = Pool(options.workers)

    for addon_id in list(addon_ids):
        results.append(pool.apply_async(_fetch_addon, (addon_id,)))

    for result in results:
        try:
            result.get(timeout=60 * 60 * 2)
        except Exception as exc:
            print('could not fetch %s' % result, exc)

    pool.close()


def parse_args():
    parser = argparse.ArgumentParser(description='Download and save all AMO add-ons.')
    parser.add_argument('--sort', metavar='FIELD', choices=['hotness', 'name'],
                        default='name',
                        help='sort by the specified field. Options are views, likes and dislikes.')
    parser.add_argument('--max', metavar='MAX', type=int, help='max amount of pages to fetch.')
    parser.add_argument('--workers', type=int, default=8,
                        help='number of workers to use, 8 by default.')
    return parser.parse_args()


def fetch_addons(options):
    ids = get_addon_ids(options)

    fetch_addon_data(options, ids)

if __name__ == '__main__':
    fetch_addons(parse_args())
