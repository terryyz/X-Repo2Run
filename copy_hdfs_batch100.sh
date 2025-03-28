#!/bin/bash

# HDFS source directory
SOURCE_DIR="hdfs://harunava/home/byte_data_seed_azureb_tteng/user/codeai/unzip_code_repo_batch/tmp_repo_0"

# Local destination directory
LOCAL_DIR="./tmp_repo_0"

# Create local directory if it doesn't exist
mkdir -p "$LOCAL_DIR"

# Create log file to track progress
LOG_FILE="hdfs_copy_batch100.log"
touch "$LOG_FILE"

echo "Getting list of directories from HDFS..."

# Get a complete listing of the HDFS directory, saving the full output
hdfs dfs -ls "$SOURCE_DIR" > hdfs_full_listing.txt

# Extract ONLY the paths from the listing
cat hdfs_full_listing.txt | grep -v "^Found" | awk '{$1=$2=$3=$4=$5=$6=$7=""; print $0}' | sed 's/^[ \t]*//' > hdfs_paths.txt

# Count total items
TOTAL_ITEMS=$(wc -l < hdfs_paths.txt)
echo "Found $TOTAL_ITEMS items to process"

# Process in batches to avoid memory issues
BATCH_SIZE=100  # Increased batch size to 100 folders per batch
CURRENT=0
BATCH=1

while [ $CURRENT -lt $TOTAL_ITEMS ]; do
    echo "Processing batch $BATCH (items $((CURRENT+1)) to $((CURRENT+BATCH_SIZE)) of $TOTAL_ITEMS)..."
    BATCH_COUNT=0
    
    # Process a batch of 100 paths
    while IFS= read -r path && [ $BATCH_COUNT -lt $BATCH_SIZE ]; do
        # Increment counters
        BATCH_COUNT=$((BATCH_COUNT + 1))
        CURRENT=$((CURRENT + 1))
        
        # Extract just the directory name (last component of path)
        DIR_NAME=$(basename "$path" 2>/dev/null || echo "unknown_dir_$CURRENT")
        
        # Skip if already processed
        if grep -q "^$DIR_NAME$" "$LOG_FILE"; then
            echo "[$CURRENT/$TOTAL_ITEMS] Skipping $DIR_NAME (already copied)"
            continue
        fi
        
        echo "[$CURRENT/$TOTAL_ITEMS] Copying: $DIR_NAME from $path"
        
        # Create target directory
        mkdir -p "$LOCAL_DIR/$DIR_NAME"
        
        # Attempt to copy using the full absolute source path
        hdfs dfs -copyToLocal "$SOURCE_DIR/$DIR_NAME" "$LOCAL_DIR/" 2>/tmp/hdfs_err.log
        
        # Check if the copy succeeded
        if [ $? -eq 0 ]; then
            echo "$DIR_NAME" >> "$LOG_FILE"
            echo "Successfully copied $DIR_NAME"
        else
            # Try copying the contents of the directory instead
            hdfs dfs -copyToLocal "$SOURCE_DIR/$DIR_NAME/*" "$LOCAL_DIR/$DIR_NAME/" 2>/tmp/hdfs_err.log
            
            if [ $? -eq 0 ]; then
                echo "$DIR_NAME" >> "$LOG_FILE"
                echo "Successfully copied contents of $DIR_NAME"
            else
                # Try one more approach using just the path directly
                hdfs dfs -copyToLocal "$path" "$LOCAL_DIR/" 2>/tmp/hdfs_err.log
                
                if [ $? -eq 0 ]; then
                    echo "$DIR_NAME" >> "$LOG_FILE"
                    echo "Successfully copied $DIR_NAME using direct path"
                else
                    echo "WARNING: All copy attempts failed for $DIR_NAME - skipping"
                fi
            fi
        fi
        
        # Very brief pause to avoid hammering the filesystem
        sleep 0.5
    done < <(tail -n +$((CURRENT + 1 - BATCH_COUNT)) hdfs_paths.txt | head -n $BATCH_SIZE)
    
    echo "Completed batch $BATCH ($BATCH_COUNT items). Pausing to let system recover..."
    sleep 10  # Longer pause between batches of 100
    BATCH=$((BATCH + 1))
done

echo "Copy process completed. Check $LOG_FILE for details on copied items." 