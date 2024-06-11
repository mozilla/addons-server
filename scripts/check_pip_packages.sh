#!/bin/bash

set -ue

requirements_dir="requirements"
requirements_files=$(ls $requirements_dir)

function fail() {
    echo "Error:"
    echo $1;
    exit 1;
}

function pip_show_package() {
    local output=$(pip show $1)
    local name=$(echo "$output" | grep '^Name: ' | cut -d' ' -f2)
    local version=$(echo "$output" | grep '^Version: ' | cut -d' ' -f2)
    echo "$name==$version"
}

function get_package_name() {
    echo $(echo $1 | cut -d'=' -f1 || fail "Name not found for $1")
}

function get_package_version() {
    echo $(echo $1 | cut -d'=' -f3 || fail "Version not found for $1")
}

function get_required_packages() {
    echo $(grep -E '^[a-zA-Z0-9_-]+==[0-9.]+' "requirements/$file" | sort |sed 's/ \\$//')
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

echo "Checking for packages required in ${files[@]}"

installed_packages=$(pip freeze --all --exclude-editable | sort -u)

function check_package() {
    local expected_package=$1
    expected_name=$(get_package_name $expected_package)
    echo "$expected_name"

    actual_package=$(
        echo "$installed_packages" | grep "^$expected_name==" || pip_show_package $expected_name
    )

    actual_name=$(get_package_name $actual_package)

    if [ "$expected_name" != "$actual_name" ]; then
        fail "Package missing. Expected ${expected_name}. Received ${actual_name}"
    fi

    expected_version=$(get_package_version $expected_package)
    actual_version=$(get_package_version $actual_package)

    if [ "$expected_version" != "$actual_version" ]; then
        fail "Package $expected_package has version $actual_version, expected $expected_version"
    fi
}

for expected_package in $required_packages; do
    check_package $expected_package
done

echo "All packages are installed correctly"
