import pytest

from pages.desktop.home import Home


@pytest.mark.nondestructive
def test_there_are_ten_most_popular_extensions(base_url, selenium):
    """Ten most popular add-ons are listed"""
    page = Home(selenium, base_url).open()
    assert len(page.most_popular.extensions) == 10


@pytest.mark.nondestructive
def test_most_popular_extensions_are_sorted_by_users(base_url, selenium):
    """Most popular add-ons are sorted by popularity"""
    page = Home(selenium, base_url).open()
    extensions = page.most_popular.extensions
    sorted_by_users = sorted(extensions, key=lambda e: e.users, reverse=True)
    assert sorted_by_users == extensions
