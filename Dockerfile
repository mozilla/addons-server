FROM mozillamarketplace/centos-mysql-mkt:0.2

# Fix multilib issues when installing openssl-devel.
RUN yum install -y --enablerepo=centosplus libselinux-devel

ADD docker-mysql.repo /etc/yum.repos.d/mysql.repo

RUN yum update -y \
    && yum install -y \
        gcc-c++ \
        curl \
        libjpeg-devel \
        cyrus-sasl-devel \
        m2crypto \
        libxml2-devel \
        libxslt-devel \
        nodejs \
        zlib-devel

ADD . /code
WORKDIR /code

RUN mkdir -p /pip/{cache,build}

ADD requirements /pip/requirements

# Remove some compiled deps so we just use the packaged versions already installed.
RUN sed -i 's/m2crypto.*$/# Removed in favour of packaged version/' /pip/requirements/compiled.txt

# This cd into /pip ensures egg-links for git installed deps are created in /pip/src
RUN cd /pip && pip install -b /pip/build --no-deps --download-cache /pip/cache -r /pip/requirements/dev.txt --find-links https://pyrepo.addons.mozilla.org/
