#!/bin/bash
# Example script demonstrating the split pipeline workflow for repo2run

# Set variables
REPO_LIST="examples/repos.txt"
OUTPUT_DIR="output/split_example"
VERBOSE="--verbose"
MAX_WORKERS="--max-workers 4"

# Create output directory if it doesn't exist
mkdir -p $OUTPUT_DIR

echo "=========================================================="
echo "Repo2Run Split Pipeline Example"
echo "=========================================================="

# Step 1: Extract dependencies
echo ""
echo "=========================================================="
echo "STEP 1: Extract Dependencies"
echo "=========================================================="
python -m repo2run --global --repo-list $REPO_LIST --output-dir $OUTPUT_DIR --extract-dep $VERBOSE $MAX_WORKERS

# Check if previous step succeeded
if [ $? -ne 0 ]; then
    echo "Error: Dependency extraction failed. Exiting."
    exit 1
fi

# Step 2: Configure virtual environment
echo ""
echo "=========================================================="
echo "STEP 2: Configure Virtual Environment"
echo "=========================================================="
python -m repo2run --global --repo-list $REPO_LIST --output-dir $OUTPUT_DIR --config-venv $VERBOSE $MAX_WORKERS

# Check if previous step succeeded
if [ $? -ne 0 ]; then
    echo "Error: Virtual environment configuration failed. Exiting."
    exit 1
fi

# Step 3: Run tests
echo ""
echo "=========================================================="
echo "STEP 3: Run Tests"
echo "=========================================================="
python -m repo2run --global --repo-list $REPO_LIST --output-dir $OUTPUT_DIR --run-test $VERBOSE $MAX_WORKERS

# Check if previous step succeeded
if [ $? -ne 0 ]; then
    echo "Error: Test execution failed. Exiting."
    exit 1
fi

echo ""
echo "=========================================================="
echo "Split Pipeline Execution Completed Successfully!"
echo "Results available in: $OUTPUT_DIR"
echo "==========================================================" 