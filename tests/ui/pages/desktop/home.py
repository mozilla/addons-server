from pypom import Region
from selenium.webdriver.common.by import By

from base import Base


class Home(Base):

    @property
    def most_popular(self):
        return self.MostPopular(self)

    class MostPopular(Region):
        """Most popular extensions region"""

        _root_locator = (By.ID, 'popular-extensions')
        _extension_locator = (By.CSS_SELECTOR, '.toplist li')

        @property
        def extensions(self):
            return [self.Extension(self.page, el) for el in self.find_elements(
                *self._extension_locator)]

        class Extension(Region):

            _name_locator = (By.CLASS_NAME, 'name')
            _users_locator = (By.TAG_NAME, 'small')

            def __repr__(self):
                return '{0.name} ({0.users:,} users)'.format(self)

            @property
            def name(self):
                """Extension name"""
                return self.find_element(*self._name_locator).text

            @property
            def users(self):
                """Number of users that have downloaded the extension"""
                users_str = self.find_element(*self._users_locator).text
                return int(users_str.split()[0].replace(',', ''))
