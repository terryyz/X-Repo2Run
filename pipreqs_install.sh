#!/bin/bash

# File containing all requirements
requirements_file="pipreqs_requirements.txt"

# File to record successfully installed packages
success_file="successfully_installed.txt"

# File to record failed packages
failed_file="failed_installed.txt"

# Clear the success and failed files if they exist
> "$success_file"
> "$failed_file"

# Function to install a package and log the result
install_package() {
    package=$1
    if pip install --quiet --trusted-host bytedpypi.byted.org "$package" 2>/dev/null; then
        echo "$package" >> "$success_file"
    else
        echo "$package" >> "$failed_file"
    fi
}

# Export the function and file paths so they can be used by xargs
export -f install_package
export success_file
export failed_file

# Use xargs to run installations in parallel
cat "$requirements_file" | xargs -n 1 -P 4 -I {} bash -c 'install_package "$@"' _ {}