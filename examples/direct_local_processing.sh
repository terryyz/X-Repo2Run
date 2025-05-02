#!/bin/bash
# Example script demonstrating direct local repository processing
# This avoids unnecessary copying of repositories to output directory

# Create a directory for output
OUTPUT_DIR="direct_local_output"
mkdir -p "$OUTPUT_DIR"

# Create a file with local directories to process
LOCAL_DIRS_FILE="local_dirs.txt"

# Add some example directories to the file
# Replace these with actual directories on your system
echo "/path/to/repo1" > "$LOCAL_DIRS_FILE"
echo "/path/to/repo2" >> "$LOCAL_DIRS_FILE"
echo "# Comment line (will be ignored)" >> "$LOCAL_DIRS_FILE"
echo "/path/to/repo3" >> "$LOCAL_DIRS_FILE"

echo "Created list of local directories in $LOCAL_DIRS_FILE"
echo "Processing repositories directly from source without copying..."

# Run the unified pipeline with the local list
# This will process the repositories directly from their locations
# without copying them to the output directory
python -m repo2run.unified_pipeline --local-list "$LOCAL_DIRS_FILE" --output-dir "$OUTPUT_DIR" --verbose --max-workers 8 

# Check the exit code
if [ $? -eq 0 ]; then
  echo "✓ Direct processing of local repositories completed successfully"
else
  echo "✗ Processing failed"
  exit 1
fi

echo
echo "Generated files:"
echo "-----------------"
ls -la "$OUTPUT_DIR"

echo
echo "Note: The repositories were processed directly without copying to the output directory,"
echo "which can save significant disk space and processing time for large repositories."
echo
echo "Done!" 