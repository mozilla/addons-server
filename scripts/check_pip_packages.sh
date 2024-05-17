#!/bin/bash

requirements_dir="requirements"
requirements_files=$(ls $requirements_dir)

function fail() { echo $1; exit 1; }

export -f fail

function get_required_packages() {
    echo $(grep -E '^[a-zA-Z0-9_-]+==[0-9.]+' "requirements/$file" | sort | cut -d'=' -f1)
}

function to_sorted_set() {
    echo "$1"$'\n'"$2" | sort | uniq | tr ' ' '\n' | grep -v '^$'
}

# Get all passed arguments as a list of files
files=("$@")
# if no arguments are passed, files=requirements_files
if [ ${#files[@]} -eq 0 ]; then
    files=(${requirements_files[@]})
fi

required_packages=""

# make sure each file exists in requirements directory
for file in ${files[@]}; do
    file_path="$requirements_dir/$file"

    if [ ! -f $file_path ]; then
        fail "File $file_path does not exist"
    fi

    required_packages=$(to_sorted_set "$required_packages" "$(get_required_packages)")
done

function check_package() {
    if ! pip show $1 &> /dev/null; then
        echo "$1 - Not Found"
        exit 1
    else
        echo "$1 - Found"
    fi
}

export -f check_package

echo "Checking for packages required in ${files[@]}"
if ! echo "$required_packages" | xargs -P$(nproc) -I{} bash -c 'check_package "$@"' _ {}; then
    fail "Some packages are missing"
fi
