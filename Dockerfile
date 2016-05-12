FROM centos:centos7

# Set the locale. This is mainly so that tests can write non-ascii files to
# disk.
ENV LANG en_US.UTF-8
ENV LC_ALL en_US.UTF-8

ADD docker/mysql-community.gpg.key /etc/pki/rpm-gpg/RPM-GPG-KEY-mysql
ADD docker/nodesource.gpg.key /etc/pki/rpm-gpg/RPM-GPG-KEY-nodesource

# For mysql-python dependencies
ADD docker/mysql.repo /etc/yum.repos.d/mysql.repo

# This is temporary until https://bugzilla.mozilla.org/show_bug.cgi?id=1226533
ADD docker/nodesource.repo /etc/yum.repos.d/nodesource.repo

RUN yum update -y \
    && yum install -y \
        # Supervisor is being used to start and keep our services running
        supervisor \
        # General (dev-) dependencies
        bash-completion \
        gcc-c++ \
        curl \
        make \
        libjpeg-devel \
        cyrus-sasl-devel \
        libxml2-devel \
        libxslt-devel \
        zlib-devel \
        libffi-devel \
        openssl-devel \
        python-devel \
        # Git, because we're using git-checkout dependencies
        git \
        # Nodejs for less, stylus, uglifyjs and others
        nodejs \
        # Dependencies for mysql-python
        mysql-community-devel \
        mysql-community-client \
        mysql-community-libs \
        epel-release \
    && yum clean all

RUN yum install -y python-pip

# Until https://github.com/shazow/urllib3/commit/959d47d926e1331ad571dbfc150c9a3acb7a1eb9 lands
RUN pip install pyOpenSSL ndg-httpsclient pyasn1 certifi urllib3

# ipython / ipdb for easier debugging, supervisor to run services
RUN pip install ipython ipdb supervisor

COPY . /code
WORKDIR /code

# Install all python requires
RUN mkdir -p /deps/{build,cache}/ && \
    pip install --upgrade pip && \
    export PIP_BUILD=/deps/build/ && \
    export PIP_CACHE_DIR=/deps/cache/ && \
    export NPM_CONFIG_PREFIX=/deps/node_modules && \
    make install_python_dependencies && \
    npm install -g && \
    rm -r /deps/build/ /deps/cache/

# Preserve bash history across image updates.
# This works best when you link your local source code
# as a volume.
ENV HISTFILE /code/docker/artifacts/bash_history

# Configure bash history.
ENV HISTSIZE 50000
ENV HISTIGNORE ls:exit:"cd .."

# This prevents dupes but only in memory for the current session.
ENV HISTCONTROL erasedups

ENV CLEANCSS_BIN /deps/node_modules/clean-css/bin/cleancss
ENV LESS_BIN /deps/node_modules/less/bin/lessc
ENV STYLUS_BIN /deps/node_modules/stylus/bin/stylus
ENV UGLIFY_BIN /deps/node_modules/uglify-js/bin/uglifyjs
ENV ADDONS_LINTER_BIN /deps/node_modules/addons-linter/bin/addons-linter
