#!/bin/bash

# HDFS source directory
SOURCE_DIR="hdfs://harunava/home/byte_data_seed_azureb_tteng/user/codeai/unzip_code_repo_batch/tmp_repo_0"

# Local destination directory
LOCAL_DIR="./tmp_repo_0"

# Create local directory if it doesn't exist
mkdir -p "$LOCAL_DIR"

# Create log file to track progress
LOG_FILE="hdfs_copy_progress.log"
touch "$LOG_FILE"

# Get a list of all top-level directories in the source HDFS directory
echo "Getting list of top-level directories from HDFS..."
hdfs dfs -ls "$SOURCE_DIR" | grep -v "^Found" | awk '{print $NF}' > all_dirs.txt

# Count total number of directories
TOTAL_DIRS=$(wc -l < all_dirs.txt)
echo "Found $TOTAL_DIRS directories to copy"

# Track progress
CURRENT=0

# Copy one directory at a time
while read -r dir; do
    # Extract just the directory name
    DIR_NAME=$(basename "$dir")
    
    # Check if we've already processed this directory (in case of restart)
    if grep -q "$DIR_NAME" "$LOG_FILE"; then
        echo "Skipping $DIR_NAME (already copied)"
        continue
    fi
    
    CURRENT=$((CURRENT + 1))
    echo "[$CURRENT/$TOTAL_DIRS] Copying directory: $DIR_NAME"
    
    # Create the target directory if it doesn't exist
    mkdir -p "$LOCAL_DIR/$DIR_NAME"
    
    # Copy the directory
    hdfs dfs -copyToLocal "$dir"/* "$LOCAL_DIR/$DIR_NAME/" 
    
    if [ $? -eq 0 ]; then
        # Log successful copy
        echo "$DIR_NAME" >> "$LOG_FILE"
        echo "Successfully copied $DIR_NAME"
    else
        echo "Error copying $DIR_NAME, will retry next time"
    fi
    
    # Pause briefly between directories to avoid system overload
    sleep 3
    
done < all_dirs.txt

echo "Copy process completed. Check $LOG_FILE for details on copied directories." 