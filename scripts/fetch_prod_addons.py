#!/usr/bin/env python

import os
import requests
import argparse
import re
from multiprocessing.pool import ThreadPool as Pool

import requests
import bs4

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'settings')

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
        print('fetching %s' % page_number)
        response = requests.get(
            INDEX_URL,
            data={'sort': options.sort, 'page': page_number})

        soup = bs4.BeautifulSoup(response.text, 'lxml')

        for item in soup.select('div.items div.addon'):
            addon_ids.append(int(
                item.select('div.action div.install')[0].attrs.get('data-addon')
            ))
        return addon_ids

    if options.max:
        pages = pages[:options.max]

    print('fetch pages from 1 to %s' % max(pages), get_max_pages())
    pool = Pool(options.workers)

    addon_ids = []

    results = pool.map_async(_get_ids_from_page, pages)

    for result in results.get(20 * 60 * 60):
        addon_ids.extend(result)

    pool.close()

    return addon_ids


def get_addon_data(options, addon_ids):
    print('fetch addon data')
    def _fetch_addon(id):
        print('fetch %s' % id)
        return requests.get(ROOT_URL + '/api/v3/addons/addon/{}'.format(id)).json()

    pool = Pool(options.workers)

    addons = []

    results = pool.map_async(_fetch_addon, addon_ids)

    for result in results.get(20 * 60 * 60):
        addons.append(result)

    pool.close()

    return addons


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

    addon_data = get_addon_data(options, ids)


if __name__ == '__main__':
    fetch_addons(parse_args())
