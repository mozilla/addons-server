import pytest

from pages.desktop.categories import Categories
from pages.desktop.extensions import Extensions
from pages.desktop.home import Home


@pytest.fixture(scope='function',
                params=[(1080, 1920), (414, 738)],
                ids=['Resolution: 1080x1920', 'Resolution: 414x738'])
def selenium(selenium, request):
    """Fixture to set custom selenium parameters.

    This fixture will also parametrize all of the tests to run them on both a
    Desktop resolution and a mobile resolution.

    Desktop size: 1920x1080
    Mobile size: 738x414 (iPhone 7+)

    """
    selenium.set_window_size(*request.param)
    return selenium


@pytest.mark.nondestructive
def test_there_are_6_extension_categories(base_url, selenium):
    page = Home(selenium, base_url).open()
    assert len(page.extension_category.list) == 6


@pytest.mark.nondestructive
def test_there_are_6_theme_categories(base_url, selenium):
    page = Home(selenium, base_url).open()
    assert len(page.theme_category.list) == 6


@pytest.mark.nondestructive
def test_extensions_section_load_correctly(base_url, selenium):
    page = Home(selenium, base_url).open()
    ext_page = page.header.click_extensions()
    assert 'Extensions' in ext_page.text


@pytest.mark.nondestructive
def test_explore_section_loads(base_url, selenium):
    page = Extensions(selenium, base_url).open()
    page.header.click_explore()
    assert 'firefox/' in selenium.current_url


@pytest.mark.nondestructive
def test_themes_section_loads(base_url, selenium):
    page = Home(selenium, base_url).open()
    themes_page = page.header.click_themes()
    assert 'Themes' in themes_page.text


@pytest.mark.nondestructive
def test_browse_all_button_loads_correct_page(base_url, selenium):
    page = Home(selenium, base_url).open()
    page.featured_extensions.browse_all
    assert 'type=extension' in selenium.current_url


@pytest.mark.nondestructive
@pytest.mark.xfail(reason=(
    'No static themes since '
    'https://github.com/mozilla/addons-frontend/pull/5501/'))
def test_browse_all_themes_button_loads_correct_page(
        base_url, selenium):
    page = Home(selenium, base_url).open()
    page.popular_themes.browse_all
    assert 'type=statictheme' in selenium.current_url


@pytest.mark.nondestructive
def test_category_loads_extensions(base_url, selenium):
    page = Home(selenium, base_url).open()
    category = page.extension_category.list[0]
    category_name = category.name
    category.click()
    assert category_name in selenium.current_url


@pytest.mark.nondestructive
def test_category_section_loads_correct_category(base_url, selenium):
    page = Categories(selenium, base_url).open()
    item = page.category_list[0]
    name = item.name
    category = item.click()
    assert name in category.header.name
