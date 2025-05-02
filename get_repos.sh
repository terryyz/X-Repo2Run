#!/bin/bash

# Check if the input file is provided
if [ $# -lt 1 ]; then
    echo "Usage: $0 <input_file> [local_output_dir]"
    echo "Example: $0 repos.json ./downloads"
    exit 1
fi

INPUT_FILE=$1
LOCAL_DIR=${2:-"./downloaded_repos"}
HDFS_BASE_PATH="hdfs://harunava/home/byte_data_seed_azureb_tteng/user/codeai/unzip_code_repo_batch"
FAILED_LIST="${LOCAL_DIR}/failed_repos.txt"

# Create the local directory if it doesn't exist
mkdir -p "$LOCAL_DIR"

# Create temporary files
PATHS_FILE="$(mktemp)"
> "$FAILED_LIST"  # Create or clear the failed repos file

echo "Extracting repository paths from $INPUT_FILE..."

# Properly extract repository paths from the input file
# This assumes each line has a format like: "repository": "tmp_repo_XX/name-master"
grep -o '"repository": *"[^"]*"' "$INPUT_FILE" | awk -F'"' '{print $4}' | while read -r REPO_PATH; do
    # Only use the relative path part (e.g., tmp_repo_XX/name-master)
    # Strip any existing path prefixes if present
    CLEAN_REPO_PATH=$(echo "$REPO_PATH" | sed -E 's|^.*/tmp_repo_|tmp_repo_|g')
    
    # Build the full HDFS path
    FULL_HDFS_PATH="${HDFS_BASE_PATH}/${CLEAN_REPO_PATH}"
    echo "$FULL_HDFS_PATH" >> "$PATHS_FILE"
    echo "Found repository: $CLEAN_REPO_PATH"
done

# Count the number of repositories found
REPO_COUNT=$(wc -l < "$PATHS_FILE")
echo "Found $REPO_COUNT repositories to download."

# Copy repositories from HDFS to local directory
echo "Copying repositories from HDFS to local directory: $LOCAL_DIR"

SUCCESS_COUNT=0
FAILED_COUNT=0

cat "$PATHS_FILE" | while read -r HDFS_PATH; do
    # Extract repository name and directory
    REPO_NAME=$(basename "$HDFS_PATH")
    REPO_DIR=$(basename "$(dirname "$HDFS_PATH")")
    TARGET_DIR="${LOCAL_DIR}/${REPO_DIR}/${REPO_NAME}"
    
    mkdir -p "${LOCAL_DIR}/${REPO_DIR}"
    
    echo "Copying $HDFS_PATH to ${LOCAL_DIR}/${REPO_DIR}/"
    hdfs dfs -copyToLocal "$HDFS_PATH" "${LOCAL_DIR}/${REPO_DIR}/" > /dev/null 2>&1
    
    # Check if the copy was successful
    if [ $? -eq 0 ]; then
        echo "Successfully copied $REPO_NAME"
        ((SUCCESS_COUNT++))
    else
        echo "Failed to copy $REPO_NAME - Permission denied or not found"
        echo "$HDFS_PATH" >> "$FAILED_LIST"
        ((FAILED_COUNT++))
    fi
done

# Clean up the temporary file
rm "$PATHS_FILE"

echo "===== Download Summary ====="
echo "Total repositories: $REPO_COUNT"
echo "Successfully copied: $SUCCESS_COUNT"
echo "Failed to copy: $FAILED_COUNT"
echo "Failed repositories are listed in: $FAILED_LIST"
echo "Done copying repositories to $LOCAL_DIR" 

# Provide helper command to retry failed repositories
if [ $FAILED_COUNT -gt 0 ]; then
    echo ""
    echo "To retry downloading failed repositories with elevated permissions, try:"
    echo "cat $FAILED_LIST | while read repo; do echo \"Processing \$repo\"; hdfs dfs -copyToLocal \"\$repo\" \"${LOCAL_DIR}/\$(basename \"\$(dirname \"\$repo\")\")}/\"; done"
fi 