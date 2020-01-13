# -*- coding: utf-8 -*-
import time

import pytest
from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.keys import Keys

from pages.desktop.home import Home
from pages.desktop.search import Search


@pytest.mark.nondestructive
def test_search_loads_and_navigates_to_correct_page(base_url, selenium):
    page = Home(selenium, base_url).open()
    addon_name = page.featured_extensions.list[0].name
    search = page.search.search_for(addon_name)
    search_name = search.result_list.extensions[0].name
    assert addon_name in search_name
    assert search_name in search.result_list.extensions[0].name


@pytest.mark.nondestructive
def test_search_loads_correct_results(base_url, selenium):
    page = Home(selenium, base_url).open()
    addon_name = page.featured_extensions.list[0].name
    items = page.search.search_for(addon_name)
    assert addon_name in items.result_list.extensions[0].name


@pytest.mark.nondestructive
def test_legacy_extensions_do_not_load(base_url, selenium):
    page = Home(selenium, base_url).open()
    term = 'Video Download Manager'
    items = page.search.search_for(term)
    for item in items.result_list.extensions:
        assert term not in item.name


@pytest.mark.xfail(strict=False)
@pytest.mark.parametrize('category, sort_attr', [
    ['Most Users', 'users'],
    ['Top Rated', 'rating']])
def test_sorting_by(base_url, selenium, category, sort_attr):
    """Test searching for an addon and sorting."""
    Home(selenium, base_url).open()
    addon_name = 'Ui-Addon'
    selenium.get('{}/search/?&q={}&sort={}'.format(
        base_url, addon_name, sort_attr)
    )
    search_page = Search(selenium, base_url)
    results = [getattr(i, sort_attr)
               for i in search_page.result_list.extensions]
    assert sorted(results, reverse=True) == results


@pytest.mark.nondestructive
def test_incompative_extensions_show_as_incompatible(base_url, selenium):
    page = Home(selenium, base_url).open()
    term = 'Ui-Addon-Android'
    results = page.search.search_for(term)
    for item in results.result_list.extensions:
        if term == item.name:
            detail_page = item.click()
            assert detail_page.is_compatible is False


@pytest.mark.nondestructive
def test_search_suggestion_term_is_higher(base_url, selenium):
    page = Home(selenium, base_url).open()
    term = 'Ui-Addon-Install'
    suggestions = page.search.search_for(term, execute=False)
    assert suggestions[0].name == term


@pytest.mark.nondestructive
def test_special_chars_dont_break_suggestions(base_url, selenium):
    page = Home(selenium, base_url).open()
    term = 'Ui-Addon'
    special_chars_term = f'{term}%ç√®å'
    suggestions = page.search.search_for(special_chars_term, execute=False)
    results = [item.name for item in suggestions]
    assert term in results


@pytest.mark.nondestructive
def test_capitalization_has_same_suggestions(base_url, selenium):
    page = Home(selenium, base_url).open()
    term = 'Ui-Addon-Install'
    suggestions = page.search.search_for(term.capitalize(), execute=False)
    # Sleep to let autocomplete update.
    time.sleep(2)
    assert term == suggestions[0].name


@pytest.mark.nondestructive
def test_esc_key_closes_suggestion_list(base_url, selenium):
    page = Home(selenium, base_url).open()
    term = 'Ui-Addon-Install'
    page.search.search_for(term, execute=False)
    action = ActionChains(selenium)
    # Send ESC key to browser
    action.send_keys(Keys.ESCAPE).perform()
    with pytest.raises(NoSuchElementException):
        selenium.find_element_by_css_selector(
            'AutoSearchInput-suggestions-list')


@pytest.mark.nondestructive
def test_long_terms_dont_break_suggestions(base_url, selenium):
    page = Home(selenium, base_url).open()
    term = 'Ui-Addon'
    additional_term = ' 123456789'
    page.search.search_for(term, execute=False)
    suggestions = page.search.search_for(additional_term, execute=False)
    # Sleep to let autocomplete update.
    time.sleep(2)
    assert term in suggestions[0].name


@pytest.mark.nondestructive
def test_blank_search_loads_results_page(base_url, selenium):
    page = Home(selenium, base_url).open()
    results = page.search.search_for('', execute=True)
    assert 'Ui-Addon' in results.result_list.extensions[0].name
