#!/bin/bash
set -e  # Exit immediately if a command exits with a non-zero status

# Process each jsonl file in the output directory
for file in output/*.jsonl; do
    # Extract the repo ID from the filename (format: output/tmp_repo_ID_unittest_freq50.jsonl)
    filename=$(basename "$file")
    repo_id=$(echo "$filename" | sed -E 's/tmp_(.+)_unittest_freq50\.jsonl/\1/')
    
    echo "Processing repository ID: $repo_id"
    
    # Check if the processed file already exists
    if [ -f "processed_test_tmp_${repo_id}.jsonl" ]; then
        echo "Skipping repository ID: $repo_id - processed file already exists"
        continue
    fi
    
    # Run the processing pipeline
    python hdfs_repo_copy.py "$file"
    python add_test_groups.py "$file" "processed_test_tmp_${repo_id}.jsonl"
    python filter_analyze_tests.py -s "processed_test_tmp_${repo_id}.jsonl" "filtered_test_tmp_${repo_id}.jsonl"
    
    # Clean up
    rm -rf "tmp_${repo_id}"
    
    echo "Completed processing for repository ID: $repo_id"
done

echo "All repositories processed successfully" 