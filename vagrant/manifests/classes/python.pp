# Install python and compiled modules for project
class python {
    package {
        ["python2.6-dev", "python2.6", "libapache2-mod-wsgi", "python-pip",
         "libxml2-dev", "libxslt1-dev", "libssl-dev", "swig", "git-core"]:
            ensure => installed;
    }

    # Bah. Ubuntu moves at the speed of molasses.
    # Need the fix for exit statuses: https://github.com/pypa/pip/issues/106
    exec { "upgrade_pip":
        command => "sudo easy_install -U pip",
        require => Package['python-pip']
    }

    exec { "pip-install-compiled":
        command => "sudo pip install -v --build=/tmp/pip-build -r $PROJ_DIR/requirements/compiled.txt",
        # Disable timeout. Pip has its own sensible timeouts.
        timeout => 0,
        logoutput => true,
        require => [
            Exec["upgrade_pip"],
            Package["python2.6", "libxml2-dev", "libxslt1-dev", "libssl-dev", "swig"]
        ]
    }
}
