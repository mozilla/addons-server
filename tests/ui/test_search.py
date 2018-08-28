# -*- coding: utf-8 -*-
import pytest

from pages.desktop.home import Home
from pages.desktop.search import Search


@pytest.mark.nondestructive
def test_search_loads_and_navigates_to_correct_page(base_url, selenium):
    page = Home(selenium, base_url).open()
    addon_name = page.featured_extensions.list[0].name
    search = page.header.search_for(addon_name)
    search_name = search.result_list.extensions[0].name
    assert addon_name in search_name
    assert search_name in search.result_list.extensions[0].name


@pytest.mark.nondestructive
def test_search_loads_correct_results(base_url, selenium):
    page = Home(selenium, base_url).open()
    addon_name = page.featured_extensions.list[0].name
    items = page.search_for(addon_name)
    assert addon_name in items.result_list.extensions[0].name


@pytest.mark.nondestructive
def test_legacy_extensions_do_not_load(base_url, selenium):
    page = Home(selenium, base_url).open()
    term = 'Video Download Manager'
    items = page.search_for(term)
    for item in items.result_list.extensions:
        assert term not in item.name


@pytest.mark.parametrize('category, sort_attr', [
    ['Most Users', 'users'],
    ['Top Rated', 'rating']])
def test_sorting_by(base_url, selenium, category, sort_attr):
    """Test searching for an addon and sorting."""
    Home(selenium, base_url).open()
    addon_name = 'Ui-addon'
    selenium.get('{}/search/?&q={}&sort={}'.format(
        base_url, addon_name, sort_attr)
    )
    search_page = Search(selenium, base_url)
    results = [getattr(i, sort_attr)
               for i in search_page.result_list.extensions]
    assert sorted(results, reverse=True) == results
