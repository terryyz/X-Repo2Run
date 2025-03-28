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

# Function to safely handle directory names with special characters
safe_basename() {
    # Extract last part of path without using basename command
    echo "${1##*/}"
}

echo "Getting list of directories from HDFS..."

# Create a temporary file for the directory list with full paths
TEMP_LIST="hdfs_dir_list.txt"

# Get a list of all files/directories in the source HDFS directory
hdfs dfs -ls "$SOURCE_DIR" | grep -v "^Found" | awk '{print $8}' > "$TEMP_LIST"

# Count total items
TOTAL_ITEMS=$(wc -l < "$TEMP_LIST")
echo "Found $TOTAL_ITEMS items to process"

# Track progress
CURRENT=0

# Process each item one by one
while IFS= read -r full_path; do
    # Extract directory name safely
    DIR_NAME=$(safe_basename "$full_path")
    
    # Skip if empty
    if [ -z "$DIR_NAME" ]; then
        echo "Skipping empty directory name"
        continue
    fi
    
    # Check if we've already processed this directory (in case of restart)
    if grep -q "^$DIR_NAME$" "$LOG_FILE"; then
        echo "Skipping $DIR_NAME (already copied)"
        continue
    fi
    
    CURRENT=$((CURRENT + 1))
    echo "[$CURRENT/$TOTAL_ITEMS] Copying: $DIR_NAME"
    
    # Create the target directory
    mkdir -p "$LOCAL_DIR/$DIR_NAME"
    
    # Try direct copy first (safer approach)
    echo "Attempting direct copy..."
    hdfs dfs -copyToLocal "$full_path" "$LOCAL_DIR/" 2>/tmp/hdfs_err.log
    
    # Check if direct copy failed
    if [ $? -ne 0 ]; then
        echo "Direct copy failed, trying alternative approach..."
        
        # Try to copy contents instead
        hdfs dfs -ls "$full_path" &>/dev/null
        if [ $? -eq 0 ]; then
            # Create destination directory first
            mkdir -p "$LOCAL_DIR/$DIR_NAME"
            
            # Try to copy contents 
            hdfs dfs -copyToLocal "$full_path/*" "$LOCAL_DIR/$DIR_NAME/" 2>/tmp/hdfs_err.log
            
            if [ $? -ne 0 ]; then
                echo "Warning: Failed to copy $DIR_NAME. Error: $(cat /tmp/hdfs_err.log)"
                continue
            fi
        else
            echo "Warning: Cannot access $full_path. Skipping."
            continue
        fi
    fi
    
    # Mark as completed
    echo "$DIR_NAME" >> "$LOG_FILE"
    echo "Successfully copied $DIR_NAME"
    
    # Pause briefly to avoid system overload
    sleep 2
    
done < "$TEMP_LIST"

echo "Copy process completed. Check $LOG_FILE for details on copied items."