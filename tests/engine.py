from hitchserve import ServiceBundle
from os import path, system, chdir
from subprocess import call, check_output, PIPE, STDOUT
import hitchelasticsearch
import hitchpostgres
import hitchselenium
import hitchmemcache
import hitchpython
import hitchrabbit
import hitchmysql
import hitchredis
import hitchtest
import hitchsmtp
import hitchcron
import IPython
import shutil
import sys

# Get directory above this file
PROJECT_DIRECTORY = path.abspath(path.join(path.dirname(__file__), '..'))

class OlympiaDjangoService(hitchpython.DjangoService):
    def setup(self):
        chdir(PROJECT_DIRECTORY)
        self.manage("reset_db", "--noinput").run()
        self.manage("syncdb", "--noinput").run()
        self.manage("loaddata", "initial.json").run()
        self.manage("import_prod_versions").run()
        self.schematic("--fake", "migrations/")
        #self.manage("createsuperuser").run()
        self.manage("loaddata", "zadmin/users").run()

    def schematic(self, *args):
        schematic_args = [path.join(path.dirname(self.python), "schematic"), ] + list(args)
        return self.subcommand(*schematic_args)


class ExecutionEngine(hitchtest.ExecutionEngine):
    """Engine for orchestating and interacting with olympia."""
    def set_up(self):
        """Ensure virtualenv present, then run all services."""

        # There appears to be an unfixed bug in pyenv right now causing segfaults
        # so we can't use dynamically built versions of python. We must
        # assume the developer has python 2.7 installed on their system path.
        #python_package = hitchpython.PythonPackage(
            #python_version="2.7.10",
            #directory=path.join(PROJECT_DIRECTORY, ".env")
            #)
        #)
        #python_package.build()
        #python_package.verify()

        if "2.7" not in check_output(["python", "-V"], stderr=STDOUT).decode('utf8'):
            raise RuntimeError("Your system python is not 2.7.x")

        python_package_pip = path.join(PROJECT_DIRECTORY, ".env", "bin", "pip")
        python_package_python = path.join(PROJECT_DIRECTORY, ".env", "bin", "python")

        if not path.exists(path.join(PROJECT_DIRECTORY, ".env")):
            chdir(PROJECT_DIRECTORY)
            call(["virtualenv", ".env", "--no-site-packages"])
            call([python_package_pip, "install", "--upgrade", "pip"])

        rabbit_package = hitchrabbit.RabbitPackage("3.5.4")
        rabbit_package.build()


        if self.settings.get('pipinstall', True):
            call([
            python_package_pip, "install", "--no-deps", "--exists-action=w", "-r",
            path.join(PROJECT_DIRECTORY, "requirements/dev.txt"),
            "--find-links", "https://pyrepo.addons.mozilla.org/wheelhouse/",
            "--find-links", "https://pyrepo.addons.mozilla.org/",
            "--no-index",
            ])

        self.elastic_package = hitchelasticsearch.ElasticPackage("1.7.1")
        self.elastic_package.build()

        mysql_package = hitchmysql.MySQLPackage("5.6.26")
        mysql_package.build()
        mysql_package.verify()

        memcache_package = hitchmemcache.MemcachePackage("1.4.24")
        memcache_package.build()
        memcache_package.verify()

        #redis_package = hitchredis.RedisPackage(
            #version=self.settings.get("redis_version")
        #)
        #redis_package.build()
        #redis_package.verify()

        shutil.copyfile(
            path.join(PROJECT_DIRECTORY, "docs/settings/local_settings.dev.py"),
            path.join(PROJECT_DIRECTORY, "local_settings.py")
        )

        with open(path.join(PROJECT_DIRECTORY, "local_settings.py"), "a") as django_settings:
            django_settings.write("""DATABASES = {
                'default': {
                    'ENGINE': 'django.db.backends.mysql',
                    'NAME': 'olympia',
                    'USER': 'olympia',
                    'PASSWORD': 'password',
                    'HOST': '127.0.0.1',
                    'PORT': '3306',
                }
            }\n""")
            django_settings.write("\nLESS_PREPROCESS = False\n")
            django_settings.write(
                """EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'\n"""
                """EMAIL_HOST = 'localhost'\n"""
                """EMAIL_PORT = 10025\n"""
                """EMAIL_HOST_USER = ''\n"""
                """EMAIL_HOST_PASSWORD = ''\n"""
                """EMAIL_USE_TLS = False\n"""
                """SEND_REAL_EMAIL = True\n"""
            )

        self.services = ServiceBundle(
            project_directory=PROJECT_DIRECTORY,
            startup_timeout=90,
            shutdown_timeout=5.0,
        )

        self.services['Memcache'] = hitchmemcache.MemcacheService(memcache_package)

        mysql_user = hitchmysql.MySQLUser("olympia", "password")

        self.services['MySQL'] = hitchmysql.MySQLService(
            mysql_package,
            users=[mysql_user],
            databases=[hitchmysql.MySQLDatabase("olympia", mysql_user), ],
        )

        self.services['Elastic'] = hitchelasticsearch.ElasticService(self.elastic_package)

        self.services['Rabbit'] = hitchrabbit.RabbitService(rabbit_package)

        self.services['Django'] = OlympiaDjangoService(
            python=python_package_python,
            port=8000,
            settings="local_settings",
            version="1.6.11",
            migrations=False,
            syncdb=False,
            sites=False,
            needs=[self.services['MySQL'], self.services['Memcache'], ],
        )

        self.services['HitchSMTP'] = hitchsmtp.HitchSMTPService()

        #self.services['Redis'] = hitchredis.RedisService(
            #redis_package=redis_package,
            #port=16379,
        #)

        #self.services['Celery'] = hitchpython.CeleryService(
            #python=python_package_python,
            #version="3.1.18",
            #app="olympia", loglevel="INFO",
            #needs=[
                #self.services['Rabbit'], self.services['MySQL'],
            #]
        #)

        self.services['Firefox'] = hitchselenium.SeleniumService(
            xvfb=self.settings.get("xvfb", False) or self.settings.get("quiet", False),
            no_libfaketime=True,
        )

        self.services.startup(interactive=False)

        if 'addons' in self.preconditions:
            self.services['Django'].manage("generate_addons", str(self.preconditions['addons'])).run()

        # Configure selenium driver
        self.driver = self.services['Firefox'].driver
        self.driver.set_window_size(800, 600)
        self.driver.implicitly_wait(2.0)
        self.driver.accept_next_alert = True

    def pause(self, message=None):
        """Stop. IPython time."""
        if hasattr(self, 'services'):
            self.services.start_interactive_mode()
        self.ipython(message)
        if hasattr(self, 'services'):
            self.services.stop_interactive_mode()

    def load_website(self):
        """Navigate to website in Firefox."""
        self.driver.get(self.services['Django'].url())

    def go(self, url):
        self.driver.get("{}{}".format(self.services['Django'].url(), url))

    def click(self, item=None, which=None):
        """Click on HTML id."""
        if which is None:
            self.driver.find_element_by_id(item).click()
        else:
            self.driver.find_elements_by_class_name(item)[int(which) - 1].click()

    def doesnt_exist(self, item=None, after=5):
        import selenium.webdriver.support.expected_conditions as EC
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.common.by import By
        from selenium.common.exceptions import TimeoutException

        element_found = True
        try:
            WebDriverWait(self.driver, after).until(
                EC.presence_of_element_located((By.ID, item)))
        except TimeoutException:
            element_found = False

        if element_found:
            raise RuntimeError("Element {} was supposed not to be found but it was.".format(item))

    def fill_form(self, **kwargs):
        """Fill in a form with id=value."""
        for element, text in kwargs.items():
            self.driver.find_element_by_id(element).send_keys(text)

    def click_submit(self):
        """Click on a submit button if it exists."""
        self.driver.find_element_by_css_selector("button[type=\"submit\"]").click()

    def confirm_emails_sent(self, number):
        """Count number of emails sent by app."""
        assert len(self.services['HitchSMTP'].logs.json()) == int(number)

    def click_on_link_in_last_email(self, which=1):
        self.driver.get(self.services['HitchSMTP'].logs.json()[-1]['links'][which - 1])

    def wait_for_email(self, containing=None):
        """Wait for, and return email."""
        self.services['HitchSMTP'].logs.out.tail.until_json(
            lambda email: containing in email['payload'] or containing in email['subject'],
            timeout=25,
            lines_back=1,
        )

    def time_travel(self, days=""):
        """Get in the Delorean, Marty!"""
        self.services.time_travel(days=int(days))

    def on_failure(self):
        """Stop and IPython."""
        if not self.settings['quiet']:
            if call(["which", "kaching"], stdout=PIPE) == 0:
                call(["kaching", "fail"])  # sudo pip install kaching for sad sound
            if self.settings.get("pause_on_failure", False):
                self.pause(message=self.stacktrace.to_template())

    def on_success(self):
        """Ka-ching!"""
        if not self.settings['quiet'] and call(["which", "kaching"], stdout=PIPE) == 0:
            call(["kaching", "pass"])  # sudo pip install kaching for happy sound
        if self.settings.get("pause_on_success", False):
            self.pause(message="SUCCESS")

    def tear_down(self):
        """Commit genocide on the services required to run your test."""
        if hasattr(self, 'services'):
            self.services.shutdown()
