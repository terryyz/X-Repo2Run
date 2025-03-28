#!/bin/bash

# HDFS source directory
SOURCE_DIR="hdfs://harunava/home/byte_data_seed_azureb_tteng/user/codeai/unzip_code_repo_batch/tmp_repo_0"

# Local destination - needs to convert to full path
LOCAL_DIR="./tmp_repo_0"
FULL_LOCAL_DIR=$(readlink -f "$LOCAL_DIR")

# Create local directory if it doesn't exist
mkdir -p "$LOCAL_DIR"

# Get a list of subdirectories
echo "Getting list of subdirectories from HDFS..."
hdfs dfs -ls "$SOURCE_DIR" | grep -v "^Found" | awk '{print $8}' > subdirs.txt

# Count total directories
TOTAL_DIRS=$(wc -l < subdirs.txt)
echo "Found $TOTAL_DIRS directories to process"

# Create log file to track progress
LOG_FILE="hdfs_distcp_progress.log"
touch "$LOG_FILE"

# Process in small batches (5 directories at a time)
BATCH_SIZE=5
CURRENT=0
BATCH=1

# Function to safely extract directory name
safe_basename() {
    echo "${1##*/}"
}

# Create a temporary file for the current batch
BATCH_FILE="current_batch.txt"

while [ $CURRENT -lt $TOTAL_DIRS ]; do
    # Clear batch file
    > "$BATCH_FILE"
    
    # Collect next batch of directories
    echo "Processing batch $BATCH..."
    BATCH_COUNT=0
    
    while IFS= read -r dir && [ $BATCH_COUNT -lt $BATCH_SIZE ]; do
        DIR_NAME=$(safe_basename "$dir")
        
        # Skip if already processed
        if grep -q "^$DIR_NAME$" "$LOG_FILE"; then
            echo "Skipping $DIR_NAME (already copied)"
            continue
        fi
        
        # Add to current batch file
        echo "$dir" >> "$BATCH_FILE"
        BATCH_COUNT=$((BATCH_COUNT + 1))
        CURRENT=$((CURRENT + 1))
        
        # Create target directory
        mkdir -p "$LOCAL_DIR/$DIR_NAME"
        
        # Mark as added to batch
        echo "Added $DIR_NAME to current batch"
        
        # Break if we've processed enough directories
        if [ $CURRENT -ge $TOTAL_DIRS ]; then
            break
        fi
    done < <(tail -n +$((CURRENT + 1)) subdirs.txt | head -n $BATCH_SIZE)
    
    # If batch is empty, break
    if [ $BATCH_COUNT -eq 0 ]; then
        echo "No more directories to process"
        break
    fi
    
    # Process each directory individually
    while IFS= read -r dir; do
        DIR_NAME=$(safe_basename "$dir")
        echo "Copying $DIR_NAME..."
        
        # Try direct copy first
        hdfs dfs -copyToLocal "$dir" "$LOCAL_DIR/" 2>/tmp/hdfs_err.log
        
        if [ $? -eq 0 ]; then
            echo "$DIR_NAME" >> "$LOG_FILE"
            echo "Successfully copied $DIR_NAME"
        else
            echo "Direct copy failed for $DIR_NAME, trying contents copy..."
            mkdir -p "$LOCAL_DIR/$DIR_NAME"
            hdfs dfs -copyToLocal "$dir/*" "$LOCAL_DIR/$DIR_NAME/" 2>/tmp/hdfs_err.log
            
            if [ $? -eq 0 ]; then
                echo "$DIR_NAME" >> "$LOG_FILE"
                echo "Successfully copied contents of $DIR_NAME"
            else
                echo "Warning: Failed to copy $DIR_NAME"
            fi
        fi
    done < "$BATCH_FILE"
    
    echo "Completed batch $BATCH. Pausing to let system recover..."
    sleep 5
    BATCH=$((BATCH + 1))
done

echo "Copy process completed. Check $LOG_FILE for details on copied items." 