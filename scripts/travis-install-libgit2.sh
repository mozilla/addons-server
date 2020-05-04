#!/usr/bin/env bash
set -o errexit -o nounset

LIBGIT2_VERSION="0.27.4"

if [ -d "libgit2" ]; then
    rm -rf libgit2/
fi

mkdir libgit2

wget https://github.com/libgit2/libgit2/archive/v${LIBGIT2_VERSION}.tar.gz
tar -xf v${LIBGIT2_VERSION}.tar.gz -C ./libgit2 --strip-components=1

cd libgit2
mkdir build && cd build
cmake .. -DCMAKE_INSTALL_PREFIX=../install -DBUILD_CLAR=OFF
cmake --build . --target install
