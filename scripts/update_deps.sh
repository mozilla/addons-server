PYTHON_COMMAND=python3
PIP_COMMAND="$PYTHON_COMMAND -m pip"

info() { echo -e "\033[33mINFO: $1\033[0m\n"; }
error() { echo -e "\033[31mERROR: $1\033[0m" && exit 1; }

# Cleanup python build directory
rm -rf /deps/build/*

$PIP_COMMAND install --progress-bar=off --no-deps --exists-action=w -r "requirements/pip.txt"

info "Installing prod dependencies"
$PIP_COMMAND install --progress-bar=off --no-deps --exists-action=w -r "requirements/prod.txt"

# Install dev dependencies unless --prod is passed
if [[ ! "$@" == *"--prod"* ]]; then
  info "Installing dev dependencies"
  $PIP_COMMAND install --progress-bar=off --no-deps --exists-action=w -r "requirements/dev.txt"
fi

# Install python olympia module
$PIP_COMMAND install --no-use-pep517 -e .

## TODO add npm installation here.

