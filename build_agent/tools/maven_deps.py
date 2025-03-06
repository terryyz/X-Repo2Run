#!/usr/bin/env python3
import subprocess
import sys
import os
import xml.etree.ElementTree as ET
import json

def analyze_maven_dependencies():
    """Analyze Java project dependencies using Maven dependency:tree."""
    try:
        # Check for pom.xml
        if not os.path.exists('pom.xml'):
            print("Error: No pom.xml found in current directory")
            return 1

        # Run Maven dependency:tree
        result = subprocess.run(['mvn', 'dependency:tree', '-DoutputType=dot', '-DoutputFile=dependency.dot'],
                              capture_output=True,
                              text=True)

        if result.returncode != 0:
            print(f"Error running Maven: {result.stderr}")
            return 1

        # Parse pom.xml for direct dependencies
        try:
            tree = ET.parse('pom.xml')
            root = tree.getroot()
            
            # Handle XML namespaces in Maven POM
            ns = {'maven': 'http://maven.apache.org/POM/4.0.0'}
            
            # Extract dependencies
            deps = []
            for dep in root.findall('.//maven:dependencies/maven:dependency', ns):
                group_id = dep.find('maven:groupId', ns).text
                artifact_id = dep.find('maven:artifactId', ns).text
                version = dep.find('maven:version', ns).text if dep.find('maven:version', ns) is not None else 'managed'
                scope = dep.find('maven:scope', ns).text if dep.find('maven:scope', ns) is not None else 'compile'
                
                deps.append({
                    'groupId': group_id,
                    'artifactId': artifact_id,
                    'version': version,
                    'scope': scope
                })

            # Save dependencies to JSON file
            with open('maven_dependencies.json', 'w') as f:
                json.dump({'dependencies': deps}, f, indent=2)

            # Print dependencies in readable format
            print("\nDirect dependencies found:")
            for dep in deps:
                print(f"{dep['groupId']}:{dep['artifactId']}:{dep['version']} ({dep['scope']})")
            
            print("\nFull dependency tree saved to dependency.dot")
            print("Dependencies information saved to maven_dependencies.json")
            return 0

        except ET.ParseError as e:
            print(f"Error parsing pom.xml: {str(e)}")
            return 1
            
    except Exception as e:
        print(f"Error analyzing dependencies: {str(e)}")
        return 1

if __name__ == '__main__':
    sys.exit(analyze_maven_dependencies()) 