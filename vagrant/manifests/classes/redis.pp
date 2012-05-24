class redis {

    exec { "sudo add-apt-repository ppa:cmsj/redis-stable":
        alias => "add-redis-repo"
    }

    exec { "sudo apt-get update":
        alias => "apt-update",
        requires => Exec["add-redis-repo"]
    }

    exec { "sudo apt-get install redis-server":
        alias => "install-redis",
        requires => Exec["apt-update"]
    }

    service { "redis-server":
        ensure => running,
        enable => true,
        hasrestart => true,
        require => Exec["install-redis"]
    }
}
