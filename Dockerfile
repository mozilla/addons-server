FROM mozillamarketplace/centos-mysql-mkt:0.2

# Fix multilib issues when installing openssl-devel.
RUN yum install -y --enablerepo=centosplus libselinux-devel && yum clean all

ADD docker-mysql.repo /etc/yum.repos.d/mysql.repo

RUN yum update -y \
    && yum install -y \
        gcc-c++ \
        curl \
        libjpeg-devel \
        cyrus-sasl-devel \
        libxml2-devel \
        libxslt-devel \
        nodejs \
        zlib-devel \
        mysql-community-libs-compat-5.6.14-3.el6.x86_64 \
    && yum clean all

# The version in the above image is ancient, and does not support the
# --no-binary flag used in our requirements files.
# We also need to install wheels.
RUN pip install -U pip wheel

COPY requirements /pip/requirements/
RUN cd /pip && \
    pip install --build ./build --cache-dir ./cache \
        --find-links https://pyrepo.addons.mozilla.org/wheelhouse/ \
        --find-links https://pyrepo.addons.mozilla.org/ \
        --no-index --no-deps \
        -r requirements/docker.txt && \
    rm -r build cache

RUN mkdir /code
WORKDIR /code
