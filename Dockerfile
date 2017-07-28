FROM centos:centos7

# Allow scripts to detect we're running in our own container
RUN touch /addons-server-centos7-container

ADD docker/mysql-community.gpg.key /etc/pki/rpm-gpg/RPM-GPG-KEY-mysql
ADD docker/nodesource.gpg.key /etc/pki/rpm-gpg/RPM-GPG-KEY-nodesource
ADD docker/git.gpg.key /etc/pki/rpm-gpg/RPM-GPG-KEY-git

# For mysql-python dependencies
ADD docker/mysql.repo /etc/yum.repos.d/mysql.repo

# This is temporary until https://bugzilla.mozilla.org/show_bug.cgi?id=1226533
ADD docker/nodesource.repo /etc/yum.repos.d/nodesource.repo

# For git dependencies
ADD docker/git.repo /etc/yum.repos.d/git.repo

# Upgrade git
RUN yum install -y \
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
        # Dependencies for mysql-python
        mysql-community-devel \
        mysql-community-client \
        mysql-community-libs \
        epel-release \
        swig \
        gettext \
    && yum clean all

# Install Nodejs (for less, stylus, uglifyjs and others) separately, because
# it's part of epel which we just installed above.
RUN yum install -y nodejs

# Compile required locale
RUN localedef -i en_US -f UTF-8 en_US.UTF-8

# Set the locale. This is mainly so that tests can write non-ascii files to
# disk.
ENV LANG en_US.UTF-8
ENV LC_ALL en_US.UTF-8

RUN yum install -y python-pip
RUN pip install --upgrade six
RUN pip install --upgrade pip setuptools

# Until https://github.com/shazow/urllib3/commit/959d47d926e1331ad571dbfc150c9a3acb7a1eb9 lands
RUN pip install pyOpenSSL ndg-httpsclient pyasn1 certifi urllib3

# ipython / ipdb for easier debugging, supervisor to run services
# Remove ipython version restriction when we move to python 3, see
# https://github.com/mozilla/addons-server/issues/5380
RUN pip install 'ipython<6' ipdb supervisor

COPY . /code
WORKDIR /code

ENV PIP_BUILD=/deps/build/
ENV PIP_CACHE_DIR=/deps/cache/
ENV PIP_SRC=/deps/src/
ENV NPM_CONFIG_PREFIX=/deps/
ENV SWIG_FEATURES="-D__x86_64__"

# Install all python requires
RUN mkdir -p /deps/{build,cache,src}/ && \
    ln -s /code/package.json /deps/package.json && \
    make update_deps && \
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

ENV CLEANCSS_BIN /deps/node_modules/.bin/cleancss
ENV LESS_BIN /deps/node_modules/.bin/lessc
ENV STYLUS_BIN /deps/node_modules/.bin/stylus
ENV UGLIFY_BIN /deps/node_modules/.bin/uglifyjs
ENV ADDONS_LINTER_BIN /deps/node_modules/.bin/addons-linter
