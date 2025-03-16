#!/usr/bin/env python3
import subprocess
import sys
import os
import json
import multiprocessing

def build_cmake_project():
    """Build a C/C++ project using CMake."""
    try:
        # Check for CMakeLists.txt
        if not os.path.exists('CMakeLists.txt'):
            print("Error: No CMakeLists.txt found in current directory")
            return 1

        # Create build directory
        build_dir = 'build'
        os.makedirs(build_dir, exist_ok=True)

        # Configure CMake
        print("Configuring CMake project...")
        config_cmd = ['cmake', '-S', '.', '-B', build_dir]
        
        # Check for build type
        build_type = os.environ.get('CMAKE_BUILD_TYPE', 'Release')
        config_cmd.extend(['-DCMAKE_BUILD_TYPE=' + build_type])
        
        # Check for toolchain file
        if os.path.exists('toolchain.cmake'):
            config_cmd.extend(['-DCMAKE_TOOLCHAIN_FILE=toolchain.cmake'])
        
        config_result = subprocess.run(config_cmd, capture_output=True, text=True)
        
        if config_result.stdout:
            print(config_result.stdout)
        if config_result.stderr:
            print(config_result.stderr, file=sys.stderr)
            
        if config_result.returncode != 0:
            print("CMake configuration failed!")
            return config_result.returncode

        # Build project
        print("\nBuilding project...")
        cpu_count = multiprocessing.cpu_count()
        build_cmd = [
            'cmake', 
            '--build', build_dir,
            '--parallel', str(cpu_count),
            '--config', build_type
        ]
        
        build_result = subprocess.run(build_cmd, capture_output=True, text=True)
        
        if build_result.stdout:
            print(build_result.stdout)
        if build_result.stderr:
            print(build_result.stderr, file=sys.stderr)
            
        if build_result.returncode == 0:
            # Find built targets
            print("\nBuilt targets:")
            for root, _, files in os.walk(build_dir):
                for file in files:
                    if file.endswith('.exe') or (not file.endswith('.') and 
                        os.access(os.path.join(root, file), os.X_OK)):
                        print(f"- {os.path.join(root, file)}")
                        
            print("\nBuild completed successfully!")
        else:
            print("\nBuild failed!")
            
        return build_result.returncode
            
    except Exception as e:
        print(f"Error building project: {str(e)}")
        return 1

if __name__ == '__main__':
    sys.exit(build_cmake_project()) 