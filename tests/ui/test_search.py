import pytest

from pages.desktop.home import Home


@pytest.mark.smoke
@pytest.mark.nondestructive
def test_that_searching_for_addon_returns_addon_as_first_result(
        base_url, es_test, selenium):
    """Test searching for an addon returns the addon."""
    page = Home(selenium, base_url).open()
    name = page.most_popular.extensions[0].name
    search_page = page.search_for(name)
    assert name in search_page.results[0].name
    assert name in selenium.title


@pytest.mark.native
@pytest.mark.nondestructive
@pytest.mark.parametrize('category, sort_attr', [
    ['Most Users', 'users'],
    ['Top Rated', 'rating']])
def test_sorting_by(
        base_url, selenium, es_test, category, sort_attr):
    """Test searching for an addon and sorting."""
    page = Home(selenium, base_url).open()
    name = page.most_popular.extensions[0].name
    search_page = page.search_for(name)
    search_page.sort_by(category, sort_attr)
    results = [getattr(i, sort_attr) for i in search_page.results]
    assert sorted(results, reverse=True) == results
