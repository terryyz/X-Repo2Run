#!/bin/bash
# Example script demonstrating processing large numbers of repositories in parallel
# This uses:
# 1. Direct local repository processing (no copying)
# 2. Process-based parallelism (true parallel execution)
# 3. Auto-scaling of worker processes based on repository count and CPU cores

# Create a directory for output
OUTPUT_DIR="parallel_processing_output"
mkdir -p "$OUTPUT_DIR"

# Create a file with local directories to process
LOCAL_DIRS_FILE="many_local_dirs.txt"

# Function to add sample directory paths to our list
# This would be replaced with real directories in a real scenario
add_sample_dirs() {
  local count=$1
  echo "# This file contains $count sample directories to process" > "$LOCAL_DIRS_FILE"
  
  # Add some example directories
  for i in $(seq 1 $count); do
    echo "/path/to/repo$i" >> "$LOCAL_DIRS_FILE"
  done
  
  echo "Created list with $count local directories in $LOCAL_DIRS_FILE"
}

# Add a large number of sample directories (e.g., 1000)
# In a real scenario, this would be replaced with actual directories
add_sample_dirs 1000

echo "Processing repositories directly from source with parallel execution..."
echo "This will automatically scale to use multiple CPU cores for parallel processing"

# Run the unified pipeline with the local list and the --max-workers flag
# The code will automatically scale up the worker count based on CPU cores and repository count
python -m repo2run.unified_pipeline --local-list "$LOCAL_DIRS_FILE" --output-dir "$OUTPUT_DIR" --verbose --max-workers 16

# Check the exit code
if [ $? -eq 0 ]; then
  echo "✓ Parallel processing of local repositories completed successfully"
else
  echo "✗ Processing failed"
  exit 1
fi

echo
echo "Generated files:"
echo "-----------------"
ls -la "$OUTPUT_DIR"

echo
echo "Performance improvements:"
echo "------------------------"
echo "1. Direct repository access: Repositories are processed directly from their source locations"
echo "   without unnecessary copying, saving disk space and I/O operations."
echo
echo "2. Process-based parallelism: Using ProcessPoolExecutor instead of ThreadPoolExecutor"
echo "   enables true parallel execution across multiple CPU cores, bypassing Python's GIL."
echo
echo "3. Auto-scaling workers: The number of worker processes automatically scales based on"
echo "   repository count and available CPU cores, maximizing resource utilization."
echo
echo "Done!" 