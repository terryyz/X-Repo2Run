#!/bin/bash

# HDFS source directory
SOURCE_DIR="hdfs://harunava/home/byte_data_seed_azureb_tteng/user/codeai/unzip_code_repo_batch/tmp_repo_0"

# Local destination directory
LOCAL_DIR="./tmp_repo_0"

# Create local directory if it doesn't exist
mkdir -p "$LOCAL_DIR"

# Create log file to track progress
LOG_FILE="hdfs_copy_fixed_progress.log"
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
BATCH_SIZE=3  # Small batch size to minimize memory usage
CURRENT=0
BATCH=1

while [ $CURRENT -lt $TOTAL_ITEMS ]; do
    echo "Processing batch $BATCH..."
    BATCH_COUNT=0
    
    # Process a small batch of paths
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
        echo "Attempting direct full-path copy..."
        hdfs dfs -copyToLocal "$SOURCE_DIR/$DIR_NAME" "$LOCAL_DIR/" 2>/tmp/hdfs_err.log
        
        # Check if the copy succeeded
        if [ $? -eq 0 ]; then
            echo "$DIR_NAME" >> "$LOG_FILE"
            echo "Successfully copied $DIR_NAME"
        else
            echo "Direct copy failed with error: $(cat /tmp/hdfs_err.log)"
            echo "Trying alternative approach - copying contents..."
            
            # Try copying the contents of the directory instead
            hdfs dfs -copyToLocal "$SOURCE_DIR/$DIR_NAME/*" "$LOCAL_DIR/$DIR_NAME/" 2>/tmp/hdfs_err.log
            
            if [ $? -eq 0 ]; then
                echo "$DIR_NAME" >> "$LOG_FILE"
                echo "Successfully copied contents of $DIR_NAME"
            else
                echo "Content copy also failed with error: $(cat /tmp/hdfs_err.log)"
                echo "Trying simpler approach with just the path..."
                
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
        
        # Pause briefly to avoid overwhelming the system
        sleep 1
    done < <(tail -n +$((CURRENT + 1 - BATCH_COUNT)) hdfs_paths.txt | head -n $BATCH_SIZE)
    
    echo "Completed batch $BATCH. Pausing to let system recover..."
    sleep 5  # Longer pause between batches
    BATCH=$((BATCH + 1))
done

echo "Copy process completed. Check $LOG_FILE for details on copied items." 