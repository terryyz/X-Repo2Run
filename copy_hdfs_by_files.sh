#!/bin/bash

# HDFS source directory
SOURCE_DIR="hdfs://harunava/home/byte_data_seed_azureb_tteng/user/codeai/unzip_code_repo_batch/tmp_repo_0"

# Local destination directory
LOCAL_DIR="./tmp_repo_0"

# Create local directory if it doesn't exist
mkdir -p "$LOCAL_DIR"

# Function to copy files from HDFS path to local
copy_files() {
    local hdfs_path="$1"
    local local_path="$2"
    
    # Get list of files (not directories) in the current path
    hdfs dfs -ls "$hdfs_path" | grep -v "^Found" | awk '$1 ~ /^-/ {print $NF}' > files.txt
    
    # Copy files in batches
    local file_count=$(wc -l < files.txt)
    if [ "$file_count" -gt 0 ]; then
        echo "Found $file_count files in $hdfs_path"
        local count=0
        
        while read -r file; do
            local filename=$(basename "$file")
            echo "Copying file: $filename to $local_path"
            hdfs dfs -copyToLocal "$file" "$local_path/" || echo "Warning: Error copying $filename"
            
            count=$((count + 1))
            # Every 20 files, pause to let system recover
            if (( count % 20 == 0 )); then
                echo "Copied $count/$file_count files. Pausing..."
                sleep 2
            fi
        done < files.txt
    fi
    
    # Get list of directories in the current path
    hdfs dfs -ls "$hdfs_path" | grep -v "^Found" | awk '$1 ~ /^d/ {print $NF}' > dirs.txt
    
    # Process each directory
    while read -r dir; do
        local dirname=$(basename "$dir")
        local new_local_path="$local_path/$dirname"
        
        echo "Processing directory: $dirname"
        mkdir -p "$new_local_path"
        
        # Recursively process the subdirectory
        copy_files "$dir" "$new_local_path"
    done < dirs.txt
}

echo "Starting batch copy process..."
copy_files "$SOURCE_DIR" "$LOCAL_DIR"

echo "Copy completed. Please verify all data was transferred correctly." 