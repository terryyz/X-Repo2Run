"""
Dependency extractor for Repo2Run.

This module handles extracting dependencies from various sources such as:
- requirements.txt
- setup.py
- pyproject.toml
- Pipfile
- environment.yml
- etc.
"""

import ast
import configparser
import logging
import os
import re
import subprocess
from pathlib import Path
import tomli
import yaml


class DependencyExtractor:
    """
    Extracts dependencies from various sources in a repository.
    """
    
    def __init__(self, repo_path, logger=None):
        """
        Initialize the dependency extractor.
        
        Args:
            repo_path (Path): Path to the repository.
            logger (logging.Logger, optional): Logger instance. If None, a new logger is created.
        """
        self.repo_path = Path(repo_path)
        self.logger = logger or logging.getLogger(__name__)
    
    def extract_all_requirements(self):
        """
        Extract requirements from all supported sources.
        
        Returns:
            dict: Dictionary mapping source files to their requirements.
        """
        self.logger.info("Extracting requirements from all sources")
        
        requirements = {}
        
        # Extract from requirements.txt and similar files
        requirements.update(self._extract_from_requirements_txt())
        
        # Extract from setup.py
        requirements.update(self._extract_from_setup_py())
        
        # Extract from pyproject.toml
        requirements.update(self._extract_from_pyproject_toml())
        
        # Extract from Pipfile
        requirements.update(self._extract_from_pipfile())
        
        # Extract from environment.yml
        requirements.update(self._extract_from_environment_yml())

        if not requirements:
            requirements = self._extract_using_pipreqs()
        
        self.logger.info(f"Found requirements from {len(requirements)} sources")
        return requirements
    
    def unify_requirements(self, requirements):
        """
        Unify requirements from multiple sources.
        
        Args:
            requirements (dict): Dictionary mapping source files to their requirements.
        
        Returns:
            list: List of unified requirements.
        """
        self.logger.info("Unifying requirements")
        
        # Flatten all requirements
        all_reqs = []
        for source, reqs in requirements.items():
            all_reqs.extend(reqs)
        
        # Parse requirements to extract package names and versions
        parsed_reqs = {}
        for req in all_reqs:
            # Skip empty lines and comments
            if not req or req.startswith('#'):
                continue
            
            # Handle requirements with version specifiers
            match = re.match(r'^([a-zA-Z0-9_\-\.]+)([<>=!~].+)?$', req)
            if match:
                package_name = match.group(1).lower()
                version_spec = match.group(2) or ''
                
                # Update parsed requirements
                if package_name in parsed_reqs:
                    # If we already have a version spec, keep the more specific one
                    if not parsed_reqs[package_name] or (version_spec and len(version_spec) > len(parsed_reqs[package_name])):
                        parsed_reqs[package_name] = version_spec
                else:
                    parsed_reqs[package_name] = version_spec
        
        # Reconstruct unified requirements
        unified_reqs = [f"{package}{version}" for package, version in parsed_reqs.items()]
        unified_reqs.sort()
        
        self.logger.info(f"Unified {len(all_reqs)} requirements into {len(unified_reqs)} unique packages")
        return unified_reqs
    
    def _extract_from_requirements_txt(self):
        """
        Extract requirements from requirements.txt and similar files.
        
        Returns:
            dict: Dictionary mapping source files to their requirements.
        """
        requirements = {}
        
        # Find all requirements*.txt files
        req_files = list(self.repo_path.glob("**/requirements*.txt"))
        req_files.extend(self.repo_path.glob("**/requirements/*.txt"))
        req_files.extend(self.repo_path.glob("**/deps/*.txt"))
        
        for req_file in req_files:
            try:
                with open(req_file, 'r') as f:
                    content = f.read()
                
                # Parse requirements
                reqs = []
                for line in content.splitlines():
                    line = line.strip()
                    
                    # Skip empty lines and comments
                    if not line or line.startswith('#'):
                        continue
                    
                    # Skip options and URLs
                    if line.startswith('-') or line.startswith('http'):
                        continue
                    
                    # Handle requirements with version specifiers
                    reqs.append(line)
                
                if reqs:
                    rel_path = req_file.relative_to(self.repo_path)
                    requirements[str(rel_path)] = reqs
                    self.logger.debug(f"Extracted {len(reqs)} requirements from {rel_path}")
            
            except Exception as e:
                self.logger.warning(f"Failed to extract requirements from {req_file}: {str(e)}")
        
        return requirements
    
    def _extract_from_setup_py(self):
        """
        Extract requirements from setup.py.
        
        Returns:
            dict: Dictionary mapping source files to their requirements.
        """
        requirements = {}
        
        # Find all setup.py files
        setup_files = list(self.repo_path.glob("**/setup.py"))
        
        for setup_file in setup_files:
            try:
                with open(setup_file, 'r') as f:
                    content = f.read()
                
                # Parse setup.py using AST
                tree = ast.parse(content)
                
                # Find install_requires and extras_require
                install_requires = []
                extras_require = []
                
                for node in ast.walk(tree):
                    if isinstance(node, ast.Call) and getattr(node, 'func', None) and getattr(node.func, 'id', '') == 'setup':
                        for keyword in node.keywords:
                            if keyword.arg == 'install_requires':
                                if isinstance(keyword.value, ast.List):
                                    for elt in keyword.value.elts:
                                        if isinstance(elt, ast.Str):
                                            install_requires.append(elt.s)
                            
                            elif keyword.arg == 'extras_require':
                                if isinstance(keyword.value, ast.Dict):
                                    for i, key in enumerate(keyword.value.keys):
                                        if isinstance(key, ast.Str) and isinstance(keyword.value.values[i], ast.List):
                                            for elt in keyword.value.values[i].elts:
                                                if isinstance(elt, ast.Str):
                                                    extras_require.append(elt.s)
                
                reqs = install_requires + extras_require
                
                if reqs:
                    rel_path = setup_file.relative_to(self.repo_path)
                    requirements[str(rel_path)] = reqs
                    self.logger.debug(f"Extracted {len(reqs)} requirements from {rel_path}")
            
            except Exception as e:
                self.logger.warning(f"Failed to extract requirements from {setup_file}: {str(e)}")
        
        return requirements
    
    def _extract_from_pyproject_toml(self):
        """
        Extract requirements from pyproject.toml.
        
        Returns:
            dict: Dictionary mapping source files to their requirements.
        """
        requirements = {}
        
        # Find all pyproject.toml files
        pyproject_files = list(self.repo_path.glob("**/pyproject.toml"))
        
        for pyproject_file in pyproject_files:
            try:
                with open(pyproject_file, 'rb') as f:
                    data = tomli.load(f)
                
                reqs = []
                
                # Poetry dependencies
                if 'tool' in data and 'poetry' in data['tool'] and 'dependencies' in data['tool']['poetry']:
                    for package, version in data['tool']['poetry']['dependencies'].items():
                        if package != 'python' and not isinstance(version, dict):
                            reqs.append(f"{package}{version if isinstance(version, str) else ''}")
                
                # Poetry dev dependencies
                if 'tool' in data and 'poetry' in data['tool'] and 'dev-dependencies' in data['tool']['poetry']:
                    for package, version in data['tool']['poetry']['dev-dependencies'].items():
                        if not isinstance(version, dict):
                            reqs.append(f"{package}{version if isinstance(version, str) else ''}")
                
                # PEP 621 dependencies
                if 'project' in data and 'dependencies' in data['project']:
                    for dep in data['project']['dependencies']:
                        reqs.append(dep)
                
                # PEP 621 optional dependencies
                if 'project' in data and 'optional-dependencies' in data['project']:
                    for group, deps in data['project']['optional-dependencies'].items():
                        for dep in deps:
                            reqs.append(dep)
                
                if reqs:
                    rel_path = pyproject_file.relative_to(self.repo_path)
                    requirements[str(rel_path)] = reqs
                    self.logger.debug(f"Extracted {len(reqs)} requirements from {rel_path}")
            
            except Exception as e:
                self.logger.warning(f"Failed to extract requirements from {pyproject_file}: {str(e)}")
        
        return requirements
    
    def _extract_from_pipfile(self):
        """
        Extract requirements from Pipfile.
        
        Returns:
            dict: Dictionary mapping source files to their requirements.
        """
        requirements = {}
        
        # Find all Pipfile files
        pipfile_files = list(self.repo_path.glob("**/Pipfile"))
        
        for pipfile_file in pipfile_files:
            try:
                config = configparser.ConfigParser()
                config.read(pipfile_file)
                
                reqs = []
                
                # Extract packages
                if 'packages' in config:
                    for package, version in config['packages'].items():
                        if version == '*':
                            reqs.append(package)
                        else:
                            reqs.append(f"{package}{version}")
                
                # Extract dev-packages
                if 'dev-packages' in config:
                    for package, version in config['dev-packages'].items():
                        if version == '*':
                            reqs.append(package)
                        else:
                            reqs.append(f"{package}{version}")
                
                if reqs:
                    rel_path = pipfile_file.relative_to(self.repo_path)
                    requirements[str(rel_path)] = reqs
                    self.logger.debug(f"Extracted {len(reqs)} requirements from {rel_path}")
            
            except Exception as e:
                self.logger.warning(f"Failed to extract requirements from {pipfile_file}: {str(e)}")
        
        return requirements
    
    def _extract_from_environment_yml(self):
        """
        Extract requirements from environment.yml.
        
        Returns:
            dict: Dictionary mapping source files to their requirements.
        """
        requirements = {}
        
        # Find all environment.yml files
        env_files = list(self.repo_path.glob("**/environment.yml"))
        env_files.extend(self.repo_path.glob("**/environment.yaml"))
        
        for env_file in env_files:
            try:
                with open(env_file, 'r') as f:
                    data = yaml.safe_load(f)
                
                reqs = []
                
                # Extract dependencies
                if 'dependencies' in data:
                    for dep in data['dependencies']:
                        if isinstance(dep, str) and not dep.startswith('python'):
                            # Handle conda-forge::package=version format
                            if '::' in dep:
                                dep = dep.split('::')[1]
                            
                            # Handle package=version format
                            if '=' in dep:
                                package, version = dep.split('=', 1)
                                reqs.append(f"{package}=={version}")
                            else:
                                reqs.append(dep)
                
                if reqs:
                    rel_path = env_file.relative_to(self.repo_path)
                    requirements[str(rel_path)] = reqs
                    self.logger.debug(f"Extracted {len(reqs)} requirements from {rel_path}")
            
            except Exception as e:
                self.logger.warning(f"Failed to extract requirements from {env_file}: {str(e)}")
        
        return requirements
    
    def _extract_using_pipreqs(self):
        """
        Extract requirements using pipreqs.
        
        Returns:
            dict: Dictionary mapping source files to their requirements.
        """
        requirements = {}
        
        try:
            # Create .pipreqs directory
            pipreqs_dir = self.repo_path / '.pipreqs'
            pipreqs_dir.mkdir(exist_ok=True)
            
            # Run pipreqs
            pipreqs_output = pipreqs_dir / 'requirements_pipreqs.txt'
            cmd = f"pipreqs --savepath={pipreqs_output} --force {self.repo_path}"
            
            self.logger.debug(f"Running pipreqs: {cmd}")
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            
            if result.returncode == 0 and pipreqs_output.exists():
                with open(pipreqs_output, 'r') as f:
                    content = f.read()
                
                reqs = [line.strip() for line in content.splitlines() if line.strip() and not line.startswith('#')]
                
                if reqs:
                    requirements['pipreqs'] = reqs
                    self.logger.debug(f"Extracted {len(reqs)} requirements using pipreqs")
            else:
                self.logger.warning(f"pipreqs failed: {result.stderr}")
        
        except Exception as e:
            self.logger.warning(f"Failed to extract requirements using pipreqs: {str(e)}")
        
        return requirements 