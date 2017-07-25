import pytest

from pages.desktop.home import Home


@pytest.mark.smoke
@pytest.mark.nondestructive
def test_that_searching_for_addon_returns_addon_as_first_result(
        my_base_url, es_test, selenium, addon):
    """Test searching for an addon returns the addon."""
    page = Home(selenium, my_base_url).open()
    name = str(
        getattr(addon, 'name', page.featured_extensions.extensions[0].name))
    search_page = page.search_for(name)
    assert name in search_page.results[0].name
    assert name in selenium.title


@pytest.mark.native
@pytest.mark.nondestructive
@pytest.mark.parametrize('category, sort_attr', [
    ['Most Users', 'users'],
    ['Top Rated', 'rating']])
def test_sorting_by(
        transactional_db, es_test, my_base_url, selenium, addon,
        minimal_addon, category, sort_attr):
    """Test searching for an addon and sorting."""
    page = Home(selenium, my_base_url).open()
    name = str(
        getattr(addon, 'name', page.featured_extensions.extensions[0].name))
    search_page = page.search_for(name)
    search_page.sort_by(category, sort_attr)
    results = [getattr(i, sort_attr) for i in search_page.results]
    assert sorted(results, reverse=True) == results
