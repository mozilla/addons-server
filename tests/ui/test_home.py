import pytest

from pages.desktop.home import Home


@pytest.mark.nondestructive
def test_there_are_ten_most_popular_extensions(
        base_url, selenium):
    """Ten most popular add-ons are listed"""
    page = Home(selenium, base_url).open()
    assert len(page.most_popular.extensions) == 10


@pytest.mark.nondestructive
def test_most_popular_extensions_are_sorted_by_users(
        base_url, selenium):
    """Most popular add-ons are sorted by popularity"""
    page = Home(selenium, base_url).open()
    extensions_page = page.most_popular.extensions
    sorted_by_users = sorted(extensions_page,
                             key=lambda e: e.users, reverse=True)
    assert sorted_by_users == extensions_page


@pytest.mark.smoke
@pytest.mark.nondestructive
def test_that_clicking_on_addon_name_loads_details_page(
        base_url, selenium):
    """Details page addon name matches clicked addon"""
    page = Home(selenium, base_url).open()
    name = page.most_popular.extensions[0].name
    extension_page = page.most_popular.extensions[0].click()
    assert name in extension_page.description_header.name


@pytest.mark.smoke
@pytest.mark.nondestructive
def test_that_featured_themes_exist_on_the_home(
        base_url, selenium):
    """Featured themes are displayed"""
    page = Home(selenium, base_url).open()
    assert len(page.featured_themes.themes) == 6


@pytest.mark.nondestructive
def test_that_clicking_see_all_themes_link_works(
        base_url, selenium):
    """Amount of featured themes matches on both pages"""
    page = Home(selenium, base_url).open()
    themes = page.featured_themes.themes
    theme_page = page.featured_themes.see_all()
    assert len(themes) == len(theme_page.featured.themes)


@pytest.mark.nondestructive
def test_that_featured_extensions_exist_on_the_home(
        base_url, selenium):
    """Featured extensions exist on home page"""
    page = Home(selenium, base_url).open()
    assert len(page.featured_extensions.extensions) >= 1


@pytest.mark.nondestructive
def test_that_clicking_see_all_collections_link_works(
        base_url, selenium):
    """Amount of featured themes matches on both pages"""
    page = Home(selenium, base_url).open()
    collections = page.featured_collections.collections
    collections_page = page.featured_collections.see_all()
    assert len(collections_page.collections) >= len(collections)
