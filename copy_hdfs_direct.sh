#!/bin/bash

# HDFS source directory
SOURCE_DIR="hdfs://harunava/home/byte_data_seed_azureb_tteng/user/codeai/unzip_code_repo_batch/tmp_repo_0"

# Local destination directory
LOCAL_DIR="./tmp_repo_0"

# Create local directory if it doesn't exist
mkdir -p "$LOCAL_DIR"

# Log file for progress
LOG_FILE="hdfs_copy_direct.log"
touch "$LOG_FILE"

# Error log
ERROR_LOG="hdfs_copy_errors.log"
touch "$ERROR_LOG"

echo "Getting directories from HDFS..."
hdfs dfs -ls "$SOURCE_DIR" > hdfs_listing.txt

# Extract repo names from the listing
cat hdfs_listing.txt | grep -v "^Found" | tr -s ' ' | cut -d' ' -f8 | while read -r full_path; do
    # Extract just the repo name
    REPO_NAME=$(basename "$full_path" 2>/dev/null)
    
    # Skip if empty
    if [ -z "$REPO_NAME" ]; then
        echo "Skipping empty repo name"
        continue
    fi
    
    # Skip if already processed
    if grep -q "^$REPO_NAME$" "$LOG_FILE"; then
        echo "Skipping $REPO_NAME (already copied)"
        continue
    fi
    
    echo "=== Copying $REPO_NAME ==="
    
    # Create the repo directory
    mkdir -p "$LOCAL_DIR/$REPO_NAME"
    
    # Try the direct approach
    echo "Attempting direct copy..."
    hdfs dfs -copyToLocal "$SOURCE_DIR/$REPO_NAME" "$LOCAL_DIR/"
    
    # Check if successful
    if [ $? -eq 0 ]; then
        echo "$REPO_NAME" >> "$LOG_FILE"
        echo "Successfully copied $REPO_NAME"
        # Sleep a bit to avoid memory overload
        sleep 2
        continue
    fi
    
    # If failed, try listing contents first
    echo "Direct copy failed, checking if directory exists..."
    if hdfs dfs -ls "$SOURCE_DIR/$REPO_NAME" &>/dev/null; then
        echo "Directory exists, trying to copy contents..."
        
        # Try to copy contents instead
        hdfs dfs -copyToLocal "$SOURCE_DIR/$REPO_NAME/*" "$LOCAL_DIR/$REPO_NAME/"
        
        if [ $? -eq 0 ]; then
            echo "$REPO_NAME" >> "$LOG_FILE"
            echo "Successfully copied $REPO_NAME contents"
        else
            echo "Failed to copy $REPO_NAME contents too" | tee -a "$ERROR_LOG"
            echo "Trying one more approach..."
            
            # Try with full path
            hdfs dfs -copyToLocal "$full_path" "$LOCAL_DIR/"
            
            if [ $? -eq 0 ]; then
                echo "$REPO_NAME" >> "$LOG_FILE"
                echo "Successfully copied using full path"
            else
                echo "All attempts failed for $REPO_NAME" | tee -a "$ERROR_LOG"
            fi
        fi
    else
        echo "Directory $REPO_NAME does not exist or cannot be accessed" | tee -a "$ERROR_LOG"
    fi
    
    # Pause between repositories to avoid memory issues
    echo "Pausing before next repository..."
    sleep 3
done

echo "Copy process completed. Check $LOG_FILE for successful copies and $ERROR_LOG for errors." 