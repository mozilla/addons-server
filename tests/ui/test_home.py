import pytest

from pages.desktop.home import Home


@pytest.mark.django_db
@pytest.mark.nondestructive
def test_there_are_ten_most_popular_extensions(
        my_base_url, selenium, initial_data):
    """Ten most popular add-ons are listed"""
    page = Home(selenium, my_base_url).open()
    assert len(page.most_popular.extensions) == 10


@pytest.mark.django_db
@pytest.mark.nondestructive
def test_most_popular_extensions_are_sorted_by_users(
        my_base_url, selenium, initial_data):
    """Most popular add-ons are sorted by popularity"""
    page = Home(selenium, my_base_url).open()
    extensions = page.most_popular.extensions
    sorted_by_users = sorted(extensions, key=lambda e: e.users, reverse=True)
    assert sorted_by_users == extensions
