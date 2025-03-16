#!/usr/bin/env python3
import subprocess
import sys
import os
import json
import re

def analyze_gradle_dependencies():
    """Analyze Java project dependencies using Gradle."""
    try:
        # Check for build.gradle or build.gradle.kts
        if not os.path.exists('build.gradle') and not os.path.exists('build.gradle.kts'):
            print("Error: No build.gradle or build.gradle.kts found in current directory")
            return 1

        # Run Gradle dependencies task
        result = subprocess.run(['./gradlew', 'dependencies', '--console=plain'],
                              capture_output=True,
                              text=True)
        
        if result.returncode != 0:
            # Try with gradle wrapper generation
            init_result = subprocess.run(['gradle', 'wrapper'],
                                       capture_output=True,
                                       text=True)
            if init_result.returncode == 0:
                result = subprocess.run(['./gradlew', 'dependencies', '--console=plain'],
                                      capture_output=True,
                                      text=True)
            
            if result.returncode != 0:
                print(f"Error running Gradle: {result.stderr}")
                return 1

        # Parse dependency output
        dependencies = {}
        current_configuration = None
        dependency_pattern = re.compile(r'^[+\\]--- (.+):(.+):(.+)$')
        
        for line in result.stdout.splitlines():
            # Check for configuration header
            if line.endswith(':'):
                current_configuration = line.strip(':')
                dependencies[current_configuration] = []
                continue
                
            # Parse dependency line
            if current_configuration:
                match = dependency_pattern.match(line.strip())
                if match:
                    group, artifact, version = match.groups()
                    dependencies[current_configuration].append({
                        'group': group,
                        'artifact': artifact,
                        'version': version
                    })

        # Save dependencies to JSON
        with open('gradle_dependencies.json', 'w') as f:
            json.dump(dependencies, f, indent=2)

        # Print dependencies by configuration
        print("\nDependencies by Configuration:")
        for config, deps in dependencies.items():
            if deps:  # Only show non-empty configurations
                print(f"\n{config}:")
                for dep in deps:
                    print(f"  {dep['group']}:{dep['artifact']}:{dep['version']}")

        # Save raw Gradle output
        with open('gradle_dependencies.txt', 'w') as f:
            f.write(result.stdout)

        print("\nFull dependency information saved to:")
        print("- gradle_dependencies.json (parsed dependencies)")
        print("- gradle_dependencies.txt (raw Gradle output)")
        return 0
            
    except Exception as e:
        print(f"Error analyzing dependencies: {str(e)}")
        return 1

if __name__ == '__main__':
    sys.exit(analyze_gradle_dependencies()) 