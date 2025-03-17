"""
Dependency installer for Repo2Run.

This module handles installing dependencies using UV.
"""

import logging
import os
import subprocess
import sys
from pathlib import Path


class DependencyInstaller:
    """
    Installs dependencies using UV.
    """
    
    def __init__(self, repo_path, logger=None):
        """
        Initialize the dependency installer.
        
        Args:
            repo_path (Path): Path to the repository.
            logger (logging.Logger, optional): Logger instance. If None, a new logger is created.
        """
        self.repo_path = Path(repo_path)
        self.logger = logger or logging.getLogger(__name__)
    
    def check_uv_installed(self):
        """
        Check if UV is installed, and install it if not.
        
        Returns:
            bool: True if UV is installed or successfully installed, False otherwise.
        """
        self.logger.info("Checking if UV is installed")
        
        try:
            result = subprocess.run(
                'uv --version',
                shell=True,
                check=False,
                capture_output=True,
                text=True
            )
            
            if result.returncode == 0:
                self.logger.info(f"UV is installed: {result.stdout.strip()}")
                return True
        except Exception:
            pass
        
        self.logger.info("UV is not installed. Installing UV using pip...")
        
        try:
            result = subprocess.run(
                'pip install uv',
                shell=True,
                check=True,
                capture_output=True,
                text=True
            )
            
            self.logger.info("UV installed successfully via pip")
            return True
        except subprocess.CalledProcessError as e:
            self.logger.error(f"Failed to install UV: {e.stderr.strip()}")
            return False
    
    def create_virtual_environment(self, venv_path=None):
        """
        Create a virtual environment using UV.
        
        Args:
            venv_path (str, optional): Path to the virtual environment. If None, a default path is used.
        
        Returns:
            Path: Path to the created virtual environment.
        
        Raises:
            RuntimeError: If UV is not installed or the virtual environment creation fails.
        """
        if not self.check_uv_installed():
            raise RuntimeError("UV is required to create a virtual environment")
        
        if venv_path is None:
            venv_path = self.repo_path / '.venv'
        else:
            venv_path = Path(venv_path)
        
        self.logger.info(f"Creating virtual environment at {venv_path}")
        
        try:
            result = subprocess.run(
                ['uv', 'venv', str(venv_path)],
                check=True,
                capture_output=True,
                text=True
            )
            
            self.logger.info(f"Virtual environment created at {venv_path}")
            return venv_path
        except subprocess.CalledProcessError as e:
            self.logger.error(f"Failed to create virtual environment: {e.stderr}")
            raise RuntimeError(f"Failed to create virtual environment: {e.stderr}")
    
    def install_requirements(self, requirements, venv_path=None):
        """
        Install requirements using UV.
        
        Args:
            requirements (list): List of requirements to install.
            venv_path (Path, optional): Path to the virtual environment. If None, a default path is used.
        
        Returns:
            list: List of dictionaries with installation results.
        
        Raises:
            RuntimeError: If UV is not installed.
        """
        if not self.check_uv_installed():
            raise RuntimeError("UV is required to install requirements")
        
        if venv_path is None:
            venv_path = self.repo_path / '.venv'
        else:
            venv_path = Path(venv_path)
        
        if not venv_path.exists():
            self.logger.info(f"Virtual environment not found at {venv_path}. Creating...")
            self.create_virtual_environment(venv_path)
        
        self.logger.info(f"Installing {len(requirements)} requirements using UV")
        
        results = []
        
        for req in requirements:
            try:
                self.logger.info(f"Installing {req}")
                
                cmd = [
                    'uv',
                    'pip',
                    'install',
                    req,
                    '--python',
                    str(venv_path / 'bin' / 'python')
                ]
                
                result = subprocess.run(
                    cmd,
                    check=True,
                    capture_output=True,
                    text=True
                )
                
                results.append({
                    'package': req,
                    'success': True,
                    'output': result.stdout
                })
                
                self.logger.info(f"Successfully installed {req}")
            except subprocess.CalledProcessError as e:
                self.logger.warning(f"Failed to install {req}: {e.stderr}")
                
                results.append({
                    'package': req,
                    'success': False,
                    'error': e.stderr
                })
        
        # Install pytest if not already installed
        try:
            self.logger.info("Installing pytest if not already installed")
            
            cmd = [
                'uv',
                'pip',
                'install',
                'pytest',
                '--python',
                str(venv_path / 'bin' / 'python')
            ]
            
            subprocess.run(cmd, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
            self.logger.warning(f"Failed to install pytest: {e.stderr}")
        
        self.logger.info(f"Installed {sum(1 for r in results if r['success'])} out of {len(requirements)} requirements")
        return results 