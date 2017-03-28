# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import os

import pytest

from selenium.webdriver.common.action_chains import ActionChains


from pages.desktop.home import Home


class HeaderMenu:

    def __init__(self, name, items):
        self.name = name
        self.items = items

    @property
    def name(self):
        return self.name

    @property
    def items(self):
        return self.items


class TestHome:

    expected_header_menus = [
        HeaderMenu('Extensions', [
            "Featured", "Most Popular", "Top Rated", "Alerts & Updates", "Appearance", "Bookmarks",
            "Download Management", "Feeds, News & Blogging", "Games & Entertainment",
            "Language Support", "Photos, Music & Videos", "Privacy & Security", "Search Tools", "Shopping",
            "Social & Communication", "Tabs", "Web Development", "Other"]),
        HeaderMenu('Themes', [
            "Most Popular", "Top Rated", "Newest", "Abstract", "Causes", "Fashion", "Film and TV",
            "Firefox", "Foxkeh", "Holiday", "Music", "Nature", "Other", "Scenery", "Seasonal",
            "Solid", "Sports", "Websites"]),
        HeaderMenu('Collections', [
            "Featured", "Most Followers", "Newest", "Collections I've Made",
            "Collections I'm Following", "My Favorite Add-ons"]),
        HeaderMenu('MORE\xe2\x80\xa6', [
            "Add-ons for Mobile", "Dictionaries & Language Packs", "Search Tools", "Developer Hub"])]

    @pytest.mark.nondestructive
    def test_that_checks_the_most_popular_section_exists(self, my_base_url, selenium, initial_data):
        page = Home(selenium, my_base_url).open()
        heading = page.most_popular.most_popular_list_heading
        assert ('Most Popular' in heading or 'MOST POPULAR' in heading)
        assert 10 == len(page.most_popular.extensions)

    @pytest.mark.skip(reason='Promobox not working with Live Server.')
    @pytest.mark.nondestructive
    def test_that_checks_the_promo_box_exists(self, my_base_url, selenium, initial_data):
        page = Home(my_base_url, selenium)
        assert page.promo_box_present

    @pytest.mark.smoke
    @pytest.mark.nondestructive
    def test_that_clicking_on_addon_name_loads_details_page(self, my_base_url, selenium, ui_addon):
        page = Home(selenium, my_base_url).open()
        details_page = page.click_on_first_addon()
        assert details_page.is_the_current_page

    @pytest.mark.smoke
    @pytest.mark.nondestructive
    def test_that_featured_themes_exist_on_the_home(self, my_base_url, selenium, generate_themes):
        page = Home(selenium, my_base_url).open()
        assert u'Featured Themes See all \xbb', 'Featured Themes region title doesn\'t match' == page.featured_themes_title
        assert page.featured_themes_count >= 6

    @pytest.mark.nondestructive
    def test_that_clicking_see_all_themes_link_works(self, my_base_url, selenium, generate_themes):
        page = Home(selenium, my_base_url).open()
        theme_page = page.click_featured_themes_see_all_link()
        assert theme_page.is_the_current_page

    @pytest.mark.native
    @pytest.mark.nondestructive
    def test_that_extensions_link_loads_extensions_page(self, my_base_url, selenium, ui_addon):
        page = Home(selenium, my_base_url).open()
        page.header.site_navigation_menu("Extensions").click()
        assert page.is_the_current_page

    @pytest.mark.smoke
    @pytest.mark.nondestructive
    def test_most_popular_extensions_are_sorted_by_users(
            self, my_base_url, selenium, initial_data):
        """Most popular add-ons are sorted by popularity"""
        page = Home(selenium, my_base_url).open()
        extensions = page.most_popular.extensions
        sorted_by_users = sorted(extensions, key=lambda e: e.users, reverse=True)
        assert sorted_by_users == extensions

    @pytest.mark.smoke
    @pytest.mark.nondestructive
    def test_that_featured_collections_exist_on_the_home(self, my_base_url, selenium, generate_collections):
        page = Home(selenium, my_base_url).open()
        assert u'Featured Collections See all \xbb' == page.featured_collections_title, 'Featured Collection region title doesn\'t match'
        assert page.featured_collections_count > 0

    @pytest.mark.nondestructive
    def test_that_featured_extensions_exist_on_the_home(self, my_base_url, selenium, ui_addon):
        page = Home(selenium, my_base_url).open()
        assert 'Featured Extensions' == page.featured_extensions_title, 'Featured Extensions region title doesn\'t match'
        assert u'See all \xbb' == page.featured_extensions_see_all, 'Featured Extensions region see all link is not correct'
        assert page.featured_extensions_count >= 1

    @pytest.mark.nondestructive
    def test_that_clicking_see_all_collections_link_works(self, my_base_url, selenium, generate_collections):
        page = Home(selenium, my_base_url).open()
        featured_collection_page = page.click_featured_collections_see_all_link()
        assert featured_collection_page.is_the_current_page

    @pytest.mark.native
    @pytest.mark.nondestructive
    @pytest.mark.skipif(os.environ.get('RUNNING_IN_CI') == 'True',
                        reason='Selenium Action Chains currently not working well within a CI environment')
    def test_that_items_menu_fly_out_while_hovering(self, my_base_url, selenium, initial_data, generate_themes):

        # I've adapted the test to check open/closed for all menu items
        page = Home(selenium, my_base_url).open()

        for menu in self.expected_header_menus:
            menu_item = page.header.site_navigation_menu(menu.name.lower())
            menu_item.hover()
            assert menu_item.is_menu_dropdown_visible

    @pytest.mark.smoke
    @pytest.mark.nondestructive
    def test_that_clicking_top_rated_shows_addons_sorted_by_rating(self, my_base_url, selenium, initial_data):
        page = Home(selenium, my_base_url).open()
        extensions_page = page.click_to_explore('top_rated')
        assert 'Top Rated' == extensions_page.sorter.sorted_by
        assert 'sort=rating' in selenium.current_url

    @pytest.mark.nondestructive
    def test_that_clicking_most_popular_shows_addons_sorted_by_users(self, my_base_url, selenium, initial_data):
        page = Home(selenium, my_base_url).open()
        extensions_page = page.click_to_explore('popular')
        assert 'Most Users' == extensions_page.sorter.sorted_by
        assert 'sort=users' in selenium.current_url

    @pytest.mark.nondestructive
    def test_that_clicking_featured_shows_addons_sorted_by_featured(self, my_base_url, selenium, initial_data):
        page = Home(selenium, my_base_url).open()
        extensions_page = page.click_to_explore('featured')
        assert 'Featured' == extensions_page.sorter.sorted_by
        assert 'sort=featured' in selenium.current_url

    @pytest.mark.nondestructive
    def test_header_site_navigation_menus_are_correct(self, my_base_url, selenium, initial_data):
        page = Home(selenium, my_base_url).open()

        # compile lists of the expected and actual top level navigation items
        expected_navigation_menu = [menu.name.lower() for menu in self.expected_header_menus]
        actual_navigation_menus = [actual_menu.name.encode('utf-8').lower() for actual_menu in page.header.site_navigation_menus]

        assert expected_navigation_menu == actual_navigation_menus

    @pytest.mark.action_chains
    @pytest.mark.nondestructive
    @pytest.mark.skipif(os.environ.get('RUNNING_IN_CI') == 'True',
                        reason='Selenium Action Chains currently not working well within a CI environment')
    def test_the_name_of_each_site_navigation_menu_in_the_header(self, my_base_url, selenium, gen_addons, initial_data, ui_addon, generate_themes):
        page = Home(selenium, my_base_url).open()

        # loop through each expected menu and collect a list of the items in the menu
        # and then assert that they exist in the actual menu on the page
        for menu in self.expected_header_menus:
            expected_menu_items = menu.items
            actual_menu_items = [menu_items.name.encode('utf-8'.lower()) for menu_items in page.header.site_navigation_menu(menu.name.lower()).items]

            assert expected_menu_items == actual_menu_items

    @pytest.mark.nondestructive
    def test_top_three_items_in_each_site_navigation_menu_are_featured(self, my_base_url, selenium, initial_data, generate_themes):
        page = Home(selenium, my_base_url).open()

        # loop through each actual top level menu
        for actual_menu in page.header.site_navigation_menus:
            # 'more' navigation_menu has no featured items so we have a different assertion
            if actual_menu.name.encode('utf-8').lower() == 'more\xe2\x80\xa6':
                # loop through each of the items in the top level menu and check is_featured property
                for item in actual_menu.items:
                    assert not item.is_featured
            else:
                # first 3 are featured, the others are not
                for item in actual_menu.items[:3]:
                    assert item.is_featured
                for item in actual_menu.items[3:]:
                    assert not item.is_featured

    @pytest.mark.nondestructive
    def test_up_and_coming_extensions(self, my_base_url, selenium, initial_data):
        page = Home(selenium, my_base_url).open()
        assert page.up_and_coming.title.startswith('Up & Coming Extensions')
        assert 6 == len(page.up_and_coming.addons)

    @pytest.mark.native
    @pytest.mark.nondestructive
    @pytest.mark.skipif(os.environ.get('RUNNING_IN_CI') == 'True',
                        reason='Selenium Action Chains currently not working well within a CI environment')
    def test_addons_author_link(self, my_base_url, selenium, ui_addon):

        page = Home(selenium, my_base_url).open()
        selenium.maximize_window()
        first_addon = page.featured_extensions[0]
        ActionChains(selenium).reset_actions()

        first_author = first_addon.author_name
        user_page = first_addon.click_first_author()

        assert first_author[0] == user_page.username
        assert 'user' in user_page.get_url_current_page()

    def test_that_checks_explore_side_navigation(self, my_base_url, selenium, ui_addon):
        page = Home(selenium, my_base_url).open()
        assert 'explore' == page.explore_side_navigation_header_text.lower()
        assert 'featured' == page.explore_featured_link_text.lower()
        assert 'most popular' == page.explore_popular_link_text.lower()
        assert 'top rated' == page.explore_top_rated_link_text.lower()

    @pytest.mark.nondestructive
    def test_that_clicking_see_all_extensions_link_works(self, my_base_url, selenium, ui_addon):
        page = Home(selenium, my_base_url).open()
        featured_extension_page = page.click_featured_extensions_see_all_link()
        assert featured_extension_page.is_the_current_page

    @pytest.mark.nondestructive
    def test_that_checks_all_categories_side_navigation(self, my_base_url, selenium, initial_data, gen_addons, generate_themes):
        page = Home(selenium, my_base_url).open()
        category_region = page.get_category()
        assert 'CATEGORIES' == category_region.categories_side_navigation_header_text.upper()
        assert 'Alerts & Updates' == category_region.categories_alert_updates_header_text
        assert 'Appearance' == category_region.categories_appearance_header_text
        assert 'Bookmarks' == category_region.categories_bookmark_header_text
        assert 'Download Management' == category_region.categories_download_management_header_text
        assert 'Feeds, News & Blogging' == category_region.categories_feed_news_blog_header_text
        assert 'Games & Entertainment' == category_region.categories_games_entertainment_header_text
        assert 'Language Support' == category_region.categories_language_support_header_text
        assert 'Photos, Music & Videos' == category_region.categories_photo_music_video_header_text
        assert 'Privacy & Security' == category_region.categories_privacy_security_header_text
        assert 'Shopping' == category_region.categories_shopping_header_text
        assert 'Social & Communication' == category_region.categories_social_communication_header_text
        assert 'Tabs' == category_region.categories_tabs_header_text
        assert 'Web Development' == category_region.categories_web_development_header_text
        assert 'Other' == category_region.categories_other_header_text

    @pytest.mark.nondestructive
    def test_that_checks_other_applications_menu(self, my_base_url, selenium, initial_data):
        page = Home(selenium, my_base_url).open()

        # Thunderbird
        assert page.header.is_other_application_visible('Thunderbird')
        page.header.click_other_application('Thunderbird')
        current_page_url = page.get_url_current_page()
        assert current_page_url.endswith('/thunderbird/')
        assert 'Thunderbird Add-ons' in page.amo_logo_title

        # Android
        assert page.header.is_other_application_visible('Android')
        page.header.click_other_application('Android')
        current_page_url = page.get_url_current_page()
        assert current_page_url.endswith('/android/')
        assert 'Android Add-ons' in page.amo_logo_title

        # Seamonkey
        assert page.header.is_other_application_visible('Seamonkey')
        page.header.click_other_application('Seamonkey')
        current_page_url = page.get_url_current_page()
        assert current_page_url.endswith('/seamonkey/')
        assert 'SeaMonkey Add-ons' in page.amo_logo_title
