#!/bin/bash
alias pip=pip3
alias python=python3

# Set up signal handling to prevent SIGTERM from killing the whole script
trap 'echo "Received SIGTERM. Continuing with script execution..."; SIGTERM_RECEIVED=true' TERM

pip install -I git+https://github.com/terryyz/X-Repo2Run.git@global

START_REPO_ID=10
END_REPO_ID=20
MAX_RETRIES=3      # Maximum number of upload retry attempts
RETRY_DELAY=10     # Seconds to wait between retries
SIGTERM_RECEIVED=false  # Flag to track if SIGTERM was received

# Validate inputs
if ! [[ "$START_REPO_ID" =~ ^[0-9]+$ ]] || ! [[ "$END_REPO_ID" =~ ^[0-9]+$ ]]; then
    echo "Error: Both START_REPO_ID and END_REPO_ID must be numbers"
    exit 1
fi

if [ "$START_REPO_ID" -gt "$END_REPO_ID" ]; then
    echo "Error: START_REPO_ID must be less than or equal to END_REPO_ID"
    exit 1
fi

# Function to create a simple progress bar
show_progress() {
    local current=$1
    local total=$2
    local width=50
    local percentage=$((current * 100 / total))
    local completed=$((width * current / total))
    local remaining=$((width - completed))
    
    printf "\r[%${completed}s%${remaining}s] %d/%d (%d%%)" \
        "$(printf '%0.s#' $(seq 1 $completed))" \
        "$(printf '%0.s-' $(seq 1 $remaining))" \
        "$current" "$total" "$percentage"
}

# Base HDFS source directory
BASE_SOURCE_DIR="hdfs://harunava/home/byte_data_seed_azureb_tteng/user/codeai/unzip_code_repo_batch"

# Base HDFS destination directory for test results
BASE_HDFS_DEST_DIR="hdfs://harunava/home/byte_data_seed_azureb_tteng/user/codeai/extracted_tests"

# New HDFS destination for output directories
NEW_HDFS_DEST_DIR="hdfs://harunava/home/byte_data_seed_azureb_tteng/user/codeai/run_tests/freq50"

# Base local destination directory
BASE_LOCAL_DIR="."

# Create log file to track overall progress
MAIN_LOG_FILE="hdfs_copy_all_repos.log"
touch "$MAIN_LOG_FILE"

echo "Starting process for repositories $START_REPO_ID to $END_REPO_ID..." 

# Loop through the specified range of repositories
for REPO_ID in $(seq $START_REPO_ID $END_REPO_ID); do
    # Reset the SIGTERM flag for each repository
    SIGTERM_RECEIVED=false
    
    # First, try to copy existing test results if they exist
    echo "Checking for existing test results in ${BASE_HDFS_DEST_DIR}/output_${REPO_ID}..."
    if hdfs dfs -test -d "${BASE_HDFS_DEST_DIR}/output_${REPO_ID}"; then
        echo "Found existing test results, copying to local directory..."
        mkdir -p "output_${REPO_ID}"
        hdfs dfs -copyToLocal "${BASE_HDFS_DEST_DIR}/output_${REPO_ID}/*" "output_${REPO_ID}/" 2>/dev/null || true
    fi

    # HDFS source directory for this repo
    SOURCE_DIR="${BASE_SOURCE_DIR}/tmp_repo_${REPO_ID}"
    
    # Local destination directory for this repo
    LOCAL_DIR="${BASE_LOCAL_DIR}/tmp_repo_${REPO_ID}"
    
    # Create local directory if it doesn't exist
    mkdir -p "$LOCAL_DIR"
    
    # Create log file to track progress for this repo
    LOG_FILE="hdfs_copy_repo${REPO_ID}.log"
    touch "$LOG_FILE"
    
    echo "Processing repository tmp_repo_${REPO_ID}..." 
    
    # Get a complete listing of the HDFS directory, saving the full output
    echo "Getting file list from HDFS for tmp_repo_${REPO_ID}..."
    hdfs dfs -ls "$SOURCE_DIR" > "hdfs_full_listing_${REPO_ID}.txt" 
    
    # Extract ONLY the paths from the listing
    cat "hdfs_full_listing_${REPO_ID}.txt" | grep -v "^Found" | awk '{$1=$2=$3=$4=$5=$6=$7=""; print $0}' | sed 's/^[ \t]*//' > "hdfs_paths_${REPO_ID}.txt"
    
    # Count total items
    TOTAL_ITEMS=$(wc -l < "hdfs_paths_${REPO_ID}.txt")
    echo "Found $TOTAL_ITEMS items to process in tmp_repo_${REPO_ID}" 
    
    # Process in batches to avoid memory issues
    BATCH_SIZE=100  # Increased batch size to 100 folders per batch
    CURRENT=0
    BATCH=1
    
    while [ $CURRENT -lt $TOTAL_ITEMS ]; do
        # Process a batch of 100 paths
        BATCH_COUNT=0
        
        while IFS= read -r path && [ $BATCH_COUNT -lt $BATCH_SIZE ]; do
            # Increment counters
            BATCH_COUNT=$((BATCH_COUNT + 1))
            CURRENT=$((CURRENT + 1))
            
            # Extract just the directory name (last component of path)
            DIR_NAME=$(basename "$path"  || echo "unknown_dir_$CURRENT")
            
            # Skip if already processed
            if grep -q "^$DIR_NAME$" "$LOG_FILE"; then
                show_progress $CURRENT $TOTAL_ITEMS
                continue
            fi
            
            # Show progress
            show_progress $CURRENT $TOTAL_ITEMS
            
            # Create target directory
            mkdir -p "$LOCAL_DIR/$DIR_NAME" 
            
            # Attempt to copy using the full absolute source path (redirect all output to keep progress bar clean)
            hdfs dfs -copyToLocal "$SOURCE_DIR/$DIR_NAME" "$LOCAL_DIR/" 2>/tmp/hdfs_err.log >/dev/null
            
            # Check if the copy succeeded
            if [ $? -eq 0 ]; then
                echo "$DIR_NAME" >> "$LOG_FILE"
            else
                # Try copying the contents of the directory instead
                hdfs dfs -copyToLocal "$SOURCE_DIR/$DIR_NAME/*" "$LOCAL_DIR/$DIR_NAME/" 2>/tmp/hdfs_err.log >/dev/null
                
                if [ $? -eq 0 ]; then
                    echo "$DIR_NAME" >> "$LOG_FILE"
                else
                    # Try one more approach using just the path directly
                    hdfs dfs -copyToLocal "$path" "$LOCAL_DIR/" 2>/tmp/hdfs_err.log >/dev/null
                    
                    if [ $? -eq 0 ]; then
                        echo "$DIR_NAME" >> "$LOG_FILE"
                    else
                        # Log errors to the main log file but don't display them
                        echo "WARNING: All copy attempts failed for $DIR_NAME in tmp_repo_${REPO_ID}" >> "$MAIN_LOG_FILE"
                        cat /tmp/hdfs_err.log >> "$MAIN_LOG_FILE"
                    fi
                fi
            fi
            
            # Very brief pause to avoid hammering the filesystem
            sleep 0.2
        done < <(tail -n +$((CURRENT + 1 - BATCH_COUNT)) "hdfs_paths_${REPO_ID}.txt" | head -n $BATCH_SIZE)
        
        BATCH=$((BATCH + 1))
    done
    
    # Print a new line after the progress bar
    echo ""
    
    # Create output directory if it doesn't exist
    mkdir -p "output_${REPO_ID}"
    
    # Run repo2run with new parameters in a subshell to isolate potential SIGTERM
    echo "Running repo2run for tmp_repo_${REPO_ID} with run-tests option..." 
    (
        # Set a trap that just logs but doesn't terminate this subshell
        trap 'echo "Caught signal 15 in repo2run subprocess. Test execution may have been terminated."; exit 1' TERM
        
        # Run the command
        repo2run --output-dir "output_${REPO_ID}" --run-tests --timeout 900
    )
    
    # Check if subshell exited due to signal
    if [ $? -ne 0 ]; then
        echo "WARNING: repo2run may have terminated abnormally for tmp_repo_${REPO_ID}"
        echo "This is often expected behavior for test timeouts. Continuing with script..." | tee -a "$MAIN_LOG_FILE"
    fi
    
    # Upload entire output directory to HDFS
    echo "Uploading entire output directory to HDFS for tmp_repo_${REPO_ID}..." 
    # Create the destination directory in HDFS if it doesn't exist
    hdfs dfs -mkdir -p "${NEW_HDFS_DEST_DIR}" 
    
    # Upload with retries
    upload_success=false
    attempt=1

    while [ $attempt -le $MAX_RETRIES ] && [ "$upload_success" = false ]; do
        echo "Attempt $attempt of $MAX_RETRIES: Uploading output_${REPO_ID} to HDFS..." 
        
        if hdfs dfs -put -f "output_${REPO_ID}" "${NEW_HDFS_DEST_DIR}/" ; then
            echo "Successfully uploaded output_${REPO_ID} to HDFS on attempt $attempt" 
            upload_success=true
        else
            echo "WARNING: Failed to upload output_${REPO_ID} to HDFS on attempt $attempt" 
            if [ $attempt -lt $MAX_RETRIES ]; then
                echo "Waiting ${RETRY_DELAY} seconds before retry..." 
                sleep $RETRY_DELAY
            fi
            attempt=$((attempt + 1))
        fi
    done

    if [ "$upload_success" = false ]; then
        echo "ERROR: Failed to upload output_${REPO_ID} to HDFS after $MAX_RETRIES attempts" 
    fi
    
    echo "Cleaning up: removing ${LOCAL_DIR}..." 
    rm -rf "${LOCAL_DIR}"
    
    echo "Completed processing for tmp_repo_${REPO_ID}" 
    echo "-----------------------------------------" 
done

echo "All repositories processed. Check $MAIN_LOG_FILE for details."

# Reset the trap to default behavior when script exits
trap - TERM