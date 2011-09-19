# Red Hat, CentOS, and Fedora think Apache is the only web server
# ever, so we have to use a different package on CentOS than Ubuntu.
class apache {
    case $operatingsystem {
        centos: {
            package { "httpd-devel":
                ensure => present,
                before => File['/etc/httpd/conf.d/zamboni.conf'];
            }

            file { "/etc/httpd/conf.d/zamboni.conf":
                source => "$PROJ_DIR/vagrant/files/etc/httpd/conf.d/zamboni.conf",
                owner => "root", group => "root", mode => 0644,
                require => [
                    Package['httpd-devel']
                ];
            }

            service { "httpd":
                ensure => running,
                enable => true,
                require => [
                    Package['httpd-devel'],
                    File['/etc/httpd/conf.d/zamboni.conf']
                ];
            }

        }
        ubuntu: {
            package { "apache2-threaded-dev":
                ensure => present,
                before => File['/etc/apache2/sites-enabled/zamboni.conf']; 
            }

            file { "/etc/apache2/sites-enabled/zamboni.conf":
                source => "$PROJ_DIR/vagrant/files/etc/httpd/conf.d/zamboni.conf",
                owner => "root", group => "root", mode => 0644,
                require => [
                    Package['apache2-threaded-dev']
                ];
            }

            # DISABLED, using dev server instead.
            service { "apache2":
                ensure => stopped,
                enable => false,
                require => [
                    Package['apache2-threaded-dev'],
                    File['/etc/apache2/sites-enabled/zamboni.conf']
                ];
            }
        }
    }
}
