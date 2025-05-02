#!/bin/bash
# Example script demonstrating the global mode using the main repo2run command

# Set the directory where the output will be stored
OUTPUT_DIR="global_main_output"

# Clean up any existing output directory if you want to start fresh
rm -rf "$OUTPUT_DIR"

# Run repo2run with global mode using the main command
# This will:
# 1. Extract dependencies from all repositories (ignoring versions)
# 2. Install all dependencies in a single environment
# 3. Run tests for each repository
# 4. Keep only repos that pass all tests or have no tests

echo "Running repo2run main command with global mode..."
repo2run --global --repo-list examples/repos.txt --output-dir "$OUTPUT_DIR" --verbose --overwrite --max-workers 4

# Check the exit code
if [ $? -eq 0 ]; then
  echo "✓ Global mode execution completed successfully"
else
  echo "✗ Global mode execution failed"
  exit 1
fi

# Display the generated files
echo 
echo "Generated files:"
echo "-----------------"
ls -la "$OUTPUT_DIR"

# Display the unified requirements
echo 
echo "Unified requirements (without versions):"
echo "-----------------------------------------"
cat "$OUTPUT_DIR/requirements.txt"

# Display the successful repositories
echo 
echo "Successful repositories (all tests pass or no tests):"
echo "------------------------------------------------------"
cat "$OUTPUT_DIR/successful_repos.json"

echo
echo "Done!" 