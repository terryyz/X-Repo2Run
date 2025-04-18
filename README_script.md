# Repository Requirements Mapper

This script maps repositories from a path-based format to their corresponding requirements, extracting a unified and deduplicated list of package requirements without version information.

## Usage

```bash
python map_repos_to_requirements.py <input_jsonl> <requirements_jsonl> <output_txt>
```

### Arguments

- `input_jsonl`: Path to the input JSONL file containing repository paths in the format:
  ```json
  {"repository": "downloaded_repos/tmp_repo_31/ah-django-unchained-master", ...}
  ```
  
- `requirements_jsonl`: Path to the requirements JSONL file containing repository requirements in the format:
  ```json
  {"repo_name": "andela/ah-django-unchained", "requirements": "Django==5.1.5\ndjango_restframework==3.15.2\n..."}
  ```
  
- `output_txt`: Path to the output text file where the unified and deduplicated requirements will be written.

## Example

```bash
python map_repos_to_requirements.py repos.jsonl repo_names_dedup_20250203_requirements.jsonl requirements_unified.txt
```

## How It Works

1. The script reads the input JSONL file with repository paths.
2. For each repository, it extracts the base repository name and removes suffixes like "-master" or "-main".
3. It searches for a matching repository in the requirements JSONL file.
4. When a match is found, it extracts the requirements without version information.
5. All requirements are deduplicated and sorted alphabetically.
6. The unified list is written to the output text file, one requirement per line.

## Output

The script generates a simple text file with one requirement per line, for example:

```
django
django_braces
django_extensions
djangorestframework
flask
numpy
pandas
requests
...
```

All requirements are deduplicated, sorted alphabetically, and have version information removed. 