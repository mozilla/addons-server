import pytest

from pages.desktop.extensions import Extensions
from pages.desktop.home import Home


@pytest.mark.nondestructive
def test_extensions_section_load_correctly(base_url, selenium):
    page = Home(selenium, base_url).open()
    ext_page = page.header.click_extensions()
    assert 'Extensions' in ext_page.title


@pytest.mark.nondestructive
def test_explore_section_loads(base_url, selenium):
    page = Home(selenium, base_url).open()
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


@pytest.mark.desktop_only
@pytest.mark.nondestructive
def test_category_section_loads_correct_category(base_url, selenium):
    page = Extensions(selenium, base_url).open()
    item = page.categories.category_list[0]
    name = item.name
    category = item.click()
    assert name in category.header.name


@pytest.mark.nondestructive
def test_title_routes_to_home(base_url, selenium):
    page = Home(selenium, base_url).open()
    home = page.header.click_title()
    assert home.hero_banner.is_displayed()


@pytest.mark.parametrize(
    'i, page_url',
    enumerate(['language-tools', 'search-tools', 'android']))
@pytest.mark.nondestructive
def test_more_dropdown_navigates_correctly(base_url, selenium, i, page_url):
    page = Home(selenium, base_url).open()
    page.header.more_menu(item=i)
    assert page_url in selenium.current_url


@pytest.mark.desktop_only
@pytest.mark.parametrize(
    'i, links',
    enumerate([
        'about',
        'blog.mozilla.org',
        'extensionworkshop',
        'developers',
        'AMO/Policy',
        'discourse',
        '#Contact_us',
        'review_guide',
        'status',
    ])
)
@pytest.mark.nondestructive
def test_add_ons_footer_links(base_url, selenium, i, links):
    page = Home(selenium, base_url).open()
    page.footer.addon_links[i].click()
    assert links in selenium.current_url


@pytest.mark.desktop_only
@pytest.mark.parametrize(
    'i, links',
    enumerate([
        'firefox/new',
        'firefox/mobile',
        'firefox/mobile',
        'firefox/mobile',
        'firefox',
        'firefox/channel/desktop',
    ])
)
@pytest.mark.nondestructive
def test_firefox_footer_links(base_url, selenium, i, links):
    page = Home(selenium, base_url).open()
    page.footer.firefox_links[i].click()
    assert links in selenium.current_url
