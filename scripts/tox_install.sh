#!/bin/sh
set -efx

pyrepo=https://pyrepo.addons.mozilla.org/
wheelhouse=https://pyrepo.addons.mozilla.org/wheelhouse/
wheeldir="$HOME/wheels"

links="--find-links $wheelhouse --find-links $pyrepo"

pip_() {
  cmd=$1; shift
  pip $cmd --cache-dir="$HOME/.cache/pip" --no-index $findlinks "$@"
}

pip_install() {
  pip_ install --no-deps --exists-action=w "$@"
}

if [ -n "$RUNNING_IN_CI" ]
then
  findlinks="--find-links $wheeldir"

  # First try an install using just our cached wheels. If that fails,
  # download and/or build the ones we're missing.
  if pip_install "$@"
  then
    exit 0
  else
    # Install failed. Try downloading anything we don't have cached.
    if ! pip_install --download="$wheeldir" $links "$@"
    then
      # OK. Failed to get everything we need from upstream.
      # Resort to building git packages.
      git_links=$(awk '/^# git\+https:/ { print $2 }' requirements/git.txt)
      pip_ wheel --wheel-dir="$wheeldir" $git_links

      # And try building the other wheels again, since we probably bailed
      # after failing to find a git dep.
      pip_install --download="$wheeldir" "$links" "$@"
    fi
  fi
else
  findlinks="$links"
fi

pip_install "$@"
