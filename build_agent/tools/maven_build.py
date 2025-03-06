#!/usr/bin/env python3
import subprocess
import sys
import os
import json
import xml.etree.ElementTree as ET

def build_maven_project():
    """Build a Java project using Maven."""
    try:
        # Check for pom.xml
        if not os.path.exists('pom.xml'):
            print("Error: No pom.xml found in current directory")
            return 1

        # Parse pom.xml to get project info
        try:
            tree = ET.parse('pom.xml')
            root = tree.getroot()
            
            # Extract namespace
            ns = {'mvn': root.tag.split('}')[0].strip('{')} if '}' in root.tag else ''
            
            # Get project details
            project_group = root.find('.//mvn:groupId' if ns else './/groupId', ns)
            project_artifact = root.find('.//mvn:artifactId' if ns else './/artifactId', ns)
            project_version = root.find('.//mvn:version' if ns else './/version', ns)
            
            print("Building Maven Project:")
            print(f"GroupId: {project_group.text if project_group is not None else 'N/A'}")
            print(f"ArtifactId: {project_artifact.text if project_artifact is not None else 'N/A'}")
            print(f"Version: {project_version.text if project_version is not None else 'N/A'}")
            print("\nStarting build...\n")
            
        except ET.ParseError as e:
            print(f"Warning: Could not parse pom.xml: {str(e)}")

        # Run Maven build
        build_cmd = ['mvn', 'clean', 'package', '-B']
        
        # Check if settings.xml exists and use it
        if os.path.exists('settings.xml'):
            build_cmd.extend(['-s', 'settings.xml'])
            
        result = subprocess.run(build_cmd, capture_output=True, text=True)
        
        # Print build output
        if result.stdout:
            print(result.stdout)
        if result.stderr:
            print(result.stderr, file=sys.stderr)
            
        # Check for successful build
        if result.returncode == 0:
            # Look for generated artifacts
            target_dir = 'target'
            if os.path.exists(target_dir):
                artifacts = [f for f in os.listdir(target_dir) if f.endswith('.jar')]
                if artifacts:
                    print("\nBuild Artifacts:")
                    for artifact in artifacts:
                        print(f"- {artifact}")
            print("\nBuild completed successfully!")
        else:
            print("\nBuild failed!")
            
        return result.returncode
            
    except Exception as e:
        print(f"Error building project: {str(e)}")
        return 1

if __name__ == '__main__':
    sys.exit(build_maven_project()) 