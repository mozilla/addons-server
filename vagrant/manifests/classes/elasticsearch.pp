
# Based loosely on https://gist.github.com/1190526
# This can probably be simplified when there is a deb package for ES.

class elasticsearch {

    ## NOTE: moved to init.pp so that we don't get a huge pile of updates to
    ## previously installed packages

    # exec { "add_java_repo":
    #     # For sun java:
    #     command => 'sudo add-apt-repository "deb http://archive.canonical.com/ lucid partner"',
    #     require => Package["python-software-properties"]
    # }
    # 
    # exec { "init_java_repo":
    #     command => "sudo apt-get update",
    #     require => Exec['add_java_repo']
    # }

    exec { "accept_jre_license":
        command => "echo 'sun-java6-jre shared/accepted-sun-dlj-v1-1 boolean true' | sudo debconf-set-selections",
        require => Exec["init_java_repo"]
    }

    exec { "accept_java_license":
        command => "echo 'sun-java6-bin shared/accepted-sun-dlj-v1-1 boolean true' | sudo debconf-set-selections",
        require => Exec["init_java_repo"]
    }

    exec { "accept_java_plugin_license":
        command => "echo 'sun-java6-plugin shared/accepted-sun-dlj-v1-1 boolean true' | sudo debconf-set-selections",
        require => Exec["init_java_repo"]
    }

    package {
        ["sun-java6-jre", "sun-java6-bin", "sun-java6-plugin", "curl"]:
            ensure => installed,
            require => [
                Exec["accept_jre_license"],
                Exec["accept_java_plugin_license"],
                Exec["accept_java_license"]
            ];
    }

    exec { "get_source":
        cwd => "/tmp",
        command => 'wget https://github.com/downloads/elasticsearch/elasticsearch/elasticsearch-0.17.6.tar.gz -O elasticsearch.tar.gz',
        unless => 'test -d /usr/local/share/elasticsearch'
    }

    exec { "untar":
        cwd => "/tmp",
        command => 'tar -xzf elasticsearch.tar.gz',
        require => Exec["get_source"],
        unless => 'test -d /usr/local/share/elasticsearch'
    }

    exec { "move_source":
        cwd => "/tmp",
        command => 'sudo mv elasticsearch-* /usr/local/share/elasticsearch',
        require => Exec["untar"],
        unless => 'test -d /usr/local/share/elasticsearch'
    }

    exec { "get_service":
        cwd => "/tmp",
        command => 'curl -L http://github.com/elasticsearch/elasticsearch-servicewrapper/tarball/master | tar -xz',
        require => [Package["curl"], Exec["move_source"]],
        unless => 'test -d /usr/local/share/elasticsearch/bin/service'
    }

    exec { "move_service":
        cwd => "/tmp",
        command => 'sudo mv *servicewrapper*/service /usr/local/share/elasticsearch/bin/',
        require => [Exec["get_service"], Exec["move_source"]],
        unless => 'test -d /usr/local/share/elasticsearch/bin/service'
    }

    exec { "install_service":
        # Makes /etc/init.d/elasticsearch
        command => 'sudo /usr/local/share/elasticsearch/bin/service/elasticsearch install',
        # Install if service is not already running.
        unless => 'test `cat /usr/local/share/elasticsearch/bin/service/elasticsearch.java.status` = STARTED',
        require => [
            Exec["move_service"],
            Package["sun-java6-jre", "sun-java6-bin", "sun-java6-plugin", "curl"]
        ]
    }

    service { "elasticsearch":
        enable => true,
        ensure => "running",
        require => Exec["install_service"]
    }
}
