#!/bin/bash

# HDFS source directory
SOURCE_DIR="hdfs://harunava/home/byte_data_seed_azureb_tteng/user/codeai/unzip_code_repo_batch/tmp_repo_0"

# Local destination directory
LOCAL_DIR="./tmp_repo_0"

# Create local directory if it doesn't exist
mkdir -p "$LOCAL_DIR"

# Get a list of all subdirectories in the source HDFS directory
echo "Getting list of subdirectories from HDFS..."
hdfs dfs -ls "$SOURCE_DIR" | grep -v "^Found" | awk '{print $NF}' > subdirs.txt

# Set batch size (number of subdirectories to copy in each batch)
BATCH_SIZE=5

# Process subdirectories in batches
echo "Starting batch copy process..."
TOTAL_DIRS=$(wc -l < subdirs.txt)
CURRENT=0

while read -r subdir; do
    CURRENT=$((CURRENT + 1))
    DIR_NAME=$(basename "$subdir")
    echo "[$CURRENT/$TOTAL_DIRS] Copying $DIR_NAME"
    
    # Create corresponding local directory
    mkdir -p "$LOCAL_DIR/$DIR_NAME"
    
    # Copy this subdirectory to local
    hdfs dfs -copyToLocal "$subdir"/* "$LOCAL_DIR/$DIR_NAME/" || echo "Warning: Error copying $DIR_NAME"
    
    # Sleep briefly to avoid overwhelming the system
    sleep 1
    
    # Every BATCH_SIZE directories, pause to let system recover
    if (( CURRENT % BATCH_SIZE == 0 )); then
        echo "Completed batch of $BATCH_SIZE. Pausing to let system recover..."
        sleep 5
    fi
    
done < subdirs.txt

echo "Copy completed. Please verify all data was transferred correctly." 