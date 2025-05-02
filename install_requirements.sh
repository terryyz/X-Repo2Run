#!/bin/bash

# install_requirements.sh
# This script attempts to pip install each package from a requirements file
# If a package fails to install, it skips that package and continues

# Set default values
REQ_FILE="requirements_unified.txt"
OUTPUT_LOG="install_results.log"
PIP_COMMAND="pip"

# Parse command line arguments
while [[ $# -gt 0 ]]; do
  case $1 in
    -f|--file)
      REQ_FILE="$2"
      shift 2
      ;;
    -o|--output)
      OUTPUT_LOG="$2"
      shift 2
      ;;
    -p|--pip)
      PIP_COMMAND="$2"
      shift 2
      ;;
    -h|--help)
      echo "Usage: $0 [options]"
      echo "Options:"
      echo "  -f, --file FILE     Specify requirements file (default: requirements_unified.txt)"
      echo "  -o, --output FILE   Specify output log file (default: install_results.log)"
      echo "  -p, --pip COMMAND   Specify pip command (default: pip, can be pip3, etc.)"
      echo "  -h, --help          Show this help message"
      exit 0
      ;;
    *)
      echo "Unknown option: $1"
      echo "Use --help for usage information"
      exit 1
      ;;
  esac
done

# Check if requirements file exists
if [[ ! -f "$REQ_FILE" ]]; then
  echo "Error: Requirements file '$REQ_FILE' not found!"
  exit 1
fi

# Create or clear the log file
echo "# Installation Results" > "$OUTPUT_LOG"
echo "Started at: $(date)" >> "$OUTPUT_LOG"
echo "-------------------" >> "$OUTPUT_LOG"

# Count total packages and initialize counters
TOTAL_PACKAGES=$(grep -v '^\s*$' "$REQ_FILE" | wc -l)
INSTALLED=0
FAILED=0

echo "Attempting to install $TOTAL_PACKAGES packages from $REQ_FILE..."
echo

# Function to display progress bar
function show_progress {
  local current=$1
  local total=$2
  local width=50
  local percent=$((current * 100 / total))
  local completed=$((width * current / total))
  local remaining=$((width - completed))
  
  # Create the progress bar
  local progress="["
  for ((i=0; i<completed; i++)); do
    progress+="="
  done
  
  if [[ $completed -lt $width ]]; then
    progress+=">"
    for ((i=0; i<remaining-1; i++)); do
      progress+=" "
    done
  fi
  
  progress+="]"
  
  # Print the progress bar
  printf "\r%3d%% %s %d/%d " "$percent" "$progress" "$current" "$total"
}

# Process each line in the requirements file
CURRENT=0
while IFS= read -r package || [[ -n "$package" ]]; do
  # Skip empty lines
  if [[ -z "$package" || "$package" =~ ^[[:space:]]*$ ]]; then
    continue
  fi
  
  # Increment counter for progress bar
  ((CURRENT++))
  
  # Show progress
  show_progress "$CURRENT" "$TOTAL_PACKAGES"
  
  # Try to install the package
  if $PIP_COMMAND install "$package" > /dev/null 2>&1; then
    echo "✅ $package" >> "$OUTPUT_LOG"
    ((INSTALLED++))
  else
    echo "❌ $package" >> "$OUTPUT_LOG"
    ((FAILED++))
  fi
done < "$REQ_FILE"

# Print newline after progress bar
echo -e "\n"

# Print summary
echo "Installation summary:"
echo "--------------------"
echo "Total packages: $TOTAL_PACKAGES"
echo "Successfully installed: $INSTALLED"
echo "Failed to install: $FAILED"
echo
echo "Detailed results saved to $OUTPUT_LOG"

# Add summary to log file
echo >> "$OUTPUT_LOG"
echo "## Summary" >> "$OUTPUT_LOG"
echo "- Total packages: $TOTAL_PACKAGES" >> "$OUTPUT_LOG"
echo "- Successfully installed: $INSTALLED" >> "$OUTPUT_LOG"
echo "- Failed to install: $FAILED" >> "$OUTPUT_LOG"
echo "- Completed at: $(date)" >> "$OUTPUT_LOG"

# Set executable permissions on this script
chmod +x "$0" 