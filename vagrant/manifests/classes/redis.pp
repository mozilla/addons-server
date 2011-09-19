class redis {
    package { "redis-server":
        ensure => installed;
    }

    service { "redis-server":
        ensure => running,
        enable => true,
        hasrestart => true,
        require => [
            Package['redis-server']
        ]
    }
}
