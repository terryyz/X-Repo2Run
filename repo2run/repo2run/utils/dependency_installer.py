"""
Dependency installer for Repo2Run.

This module handles installing dependencies using either UV or pip/venv.
"""

import logging
import os
import subprocess
import sys
import shutil
from pathlib import Path


class DependencyInstaller:
    """
    Installs dependencies using either UV or pip/venv.
    """
    
    def __init__(self, repo_path, use_uv=True, logger=None):
        """
        Initialize the dependency installer.
        
        Args:
            repo_path (Path): Path to the repository.
            use_uv (bool): Whether to use UV for dependency management. If False, use pip/venv.
            logger (logging.Logger, optional): Logger instance. If None, a new logger is created.
        """
        self.repo_path = Path(repo_path)
        self.use_uv = use_uv
        self.logger = logger or logging.getLogger(__name__)
    
    def check_uv_installed(self):
        """
        Check if UV is installed, and install it if not.
        
        Returns:
            bool: True if UV is installed or successfully installed, False otherwise.
        """
        if not self.use_uv:
            self.logger.info("UV is not required as --use-uv is not specified.")
            return False
            
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
    
    def check_venv_installed(self):
        """
        Check if venv module is available.
        
        Returns:
            bool: True if venv module is available, False otherwise.
        """
        self.logger.info("Checking if venv module is available")
        
        try:
            import venv
            self.logger.info("venv module is available")
            return True
        except ImportError:
            self.logger.warning("venv module is not available")
            return False
    
    def create_virtual_environment(self, venv_path=None):
        """
        Create a virtual environment using either UV or venv.
        
        Args:
            venv_path (str, optional): Path to the virtual environment. If None, a default path is used.
        
        Returns:
            Path: Path to the created virtual environment.
        
        Raises:
            RuntimeError: If virtual environment creation fails.
        """
        if venv_path is None:
            venv_path = self.repo_path / '.venv'
        else:
            venv_path = Path(venv_path)
        
        self.logger.info(f"Creating virtual environment at {venv_path}")
        
        # Check if pyproject.toml already exists
        pyproject_path = self.repo_path / "pyproject.toml"
        project_already_initialized = pyproject_path.exists()
        
        if self.use_uv:
            if not self.check_uv_installed():
                raise RuntimeError("UV is required to create a virtual environment but is not installed")
            
            try:
                if project_already_initialized:
                    self.logger.info("Project already initialized (pyproject.toml exists)")
                    # Just create the venv without initializing the project
                    result = subprocess.run(
                        ['uv', 'venv', str(venv_path)],
                        cwd=self.repo_path,
                        check=True,
                        capture_output=True,
                        text=True
                    )
                else:
                    # Use uv init to create a virtual environment and initialize the project
                    result = subprocess.run(
                        ['uv', 'init'],
                        cwd=self.repo_path,
                        check=True,
                        capture_output=True,
                        text=True
                    )
                
                self.logger.info(f"Virtual environment created at {venv_path}")
                return venv_path
            except subprocess.CalledProcessError as e:
                self.logger.error(f"Failed to create virtual environment with UV: {e.stderr}")
                raise RuntimeError(f"Failed to create virtual environment with UV: {e.stderr}")
        else:
            # Use venv module to create virtual environment
            self.logger.info("Creating virtual environment using venv module")
            
            try:
                # First, remove any existing venv
                if venv_path.exists():
                    self.logger.info(f"Removing existing virtual environment at {venv_path}")
                    shutil.rmtree(venv_path, ignore_errors=True)
                
                import venv
                venv.create(venv_path, with_pip=True)
                
                self.logger.info(f"Virtual environment created at {venv_path}")
                return venv_path
            except Exception as e:
                self.logger.error(f"Failed to create virtual environment with venv: {str(e)}")
                raise RuntimeError(f"Failed to create virtual environment with venv: {str(e)}")
    
    def install_requirements(self, requirements, venv_path=None):
        """
        Install requirements using either UV or pip.
        
        Args:
            requirements (list): List of requirements to install.
            venv_path (Path, optional): Path to the virtual environment. If None, a default path is used.
        
        Returns:
            list: List of dictionaries with installation results.
        
        Raises:
            RuntimeError: If any requirement fails to install.
        """
        if venv_path is None:
            venv_path = self.repo_path / '.venv'
        else:
            venv_path = Path(venv_path)
        
        if not venv_path.exists():
            self.logger.info(f"Virtual environment not found at {venv_path}. Creating...")
            self.create_virtual_environment(venv_path)
        
        if self.use_uv:
            return self._install_requirements_uv(requirements, venv_path)
        else:
            return self._install_requirements_pip(requirements, venv_path)
    
    def _install_requirements_uv(self, requirements, venv_path):
        """
        Install requirements using UV.
        
        Args:
            requirements (list): List of requirements to install.
            venv_path (Path): Path to the virtual environment.
        
        Returns:
            list: List of dictionaries with installation results.
        
        Raises:
            RuntimeError: If any requirement fails to install.
        """
        if not self.check_uv_installed():
            raise RuntimeError("UV is required to install requirements but is not installed")
        
        self.logger.info(f"Installing {len(requirements)} requirements using UV")
        
        results = []
        failed_requirements = []
        
        for req in requirements:
            try:
                self.logger.info(f"Installing {req}")
                
                # Use uv add to install the requirement
                cmd = [
                    'uv', 
                    'add', 
                    req,
                    '--frozen', '--resolution', 'lowest-direct'
                ]
                
                result = subprocess.run(
                    cmd,
                    cwd=self.repo_path,
                    check=True,
                    capture_output=True,
                    text=True
                )
                
                results.append({
                    'package': req,
                    'success': True,
                    'output': result.stdout,
                    'method': 'uv'
                })
                
                self.logger.info(f"Successfully installed {req}")
            except subprocess.CalledProcessError as e:
                self.logger.warning(f"Failed to install {req}: {e.stderr}")
                
                results.append({
                    'package': req,
                    'success': False,
                    'error': e.stderr,
                    'method': 'uv'
                })
                failed_requirements.append(req)
        
        # Raise an error if any requirements failed to install
        if failed_requirements:
            error_message = f"Failed to install the following requirements: {', '.join(failed_requirements)}"
            self.logger.error(error_message)
            raise RuntimeError(error_message)
        
        # Install pytest as a dev dependency
        try:
            self.logger.info("Installing pytest as a dev dependency")
            
            cmd = [
                'uv',
                'add',
                'pytest',
                '--dev',
                '--frozen', '--resolution', 'lowest-direct'
            ]
            
            subprocess.run(
                cmd, 
                cwd=self.repo_path,
                check=True, 
                capture_output=True, 
                text=True
            )
        except subprocess.CalledProcessError as e:
            self.logger.warning(f"Failed to install pytest: {e.stderr}")
            raise RuntimeError("Failed to install pytest")
        
        return results
    
    def _install_requirements_pip(self, requirements, venv_path):
        """
        Install requirements using pip.
        
        Args:
            requirements (list): List of requirements to install.
            venv_path (Path): Path to the virtual environment.
        
        Returns:
            list: List of dictionaries with installation results.
        
        Raises:
            RuntimeError: If any requirement fails to install.
        """
        self.logger.info(f"Installing {len(requirements)} requirements using pip")
        
        # Get the path to the pip executable in the virtual environment
        if sys.platform == 'win32':
            pip_path = venv_path / 'Scripts' / 'pip.exe'
        else:
            pip_path = venv_path / 'bin' / 'pip'
        
        # Convert to absolute path to ensure it works regardless of the working directory
        pip_path = pip_path.absolute()
        
        if not pip_path.exists():
            self.logger.error(f"pip not found in virtual environment at {pip_path}")
            raise RuntimeError(f"pip not found in virtual environment at {pip_path}")
        
        results = []
        failed_requirements = []
        
        # First try to create a requirements.txt and install all requirements at once
        try:
            self.logger.info("Creating requirements.txt and installing all requirements at once")
            
            # Create a temporary requirements.txt file - use absolute path
            requirements_path = self.repo_path / "requirements.txt.tmp"
            with open(requirements_path, 'w') as f:
                f.write('\n'.join(requirements))
            
            # Ensure requirements_path is absolute
            requirements_path = requirements_path.absolute()
            
            # Install all requirements at once
            cmd = [
                str(pip_path),
                'install',
                '-r',
                str(requirements_path),
                '--no-cache-dir'
            ]
            
            self.logger.info(f"Running pip with command: {' '.join(cmd)}")
            
            result = subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                text=True
            )
            
            # Clean up the temporary file
            requirements_path.unlink()
            
            # Mark all requirements as successfully installed
            for req in requirements:
                results.append({
                    'package': req,
                    'success': True,
                    'output': "Installed via requirements.txt",
                    'method': 'pip batch'
                })
                
            self.logger.info("Successfully installed all requirements via requirements.txt")
        except subprocess.CalledProcessError as e:
            self.logger.warning(f"Failed to install all requirements at once: {e.stderr}")
            
            # Clean up the temporary file if it exists
            if requirements_path.exists():
                requirements_path.unlink()
            
            # Install packages individually
            for req in requirements:
                try:
                    self.logger.info(f"Installing {req}")
                    
                    cmd = [
                        str(pip_path),
                        'install',
                        req,
                        '--no-cache-dir'
                    ]
                    
                    self.logger.info(f"Running pip with command: {' '.join(cmd)}")
                    
                    result = subprocess.run(
                        cmd,
                        check=True,
                        capture_output=True,
                        text=True
                    )
                    
                    results.append({
                        'package': req,
                        'success': True,
                        'output': result.stdout,
                        'method': 'pip individual'
                    })
                    
                    self.logger.info(f"Successfully installed {req}")
                except subprocess.CalledProcessError as e:
                    error_msg = e.stderr
                    self.logger.warning(f"Failed to install {req}: {error_msg}")
                    
                    results.append({
                        'package': req,
                        'success': False,
                        'error': error_msg,
                        'method': 'pip individual'
                    })
                    failed_requirements.append(req)
        
        # Raise an error if any requirements failed to install
        if failed_requirements:
            error_message = f"Failed to install the following requirements: {', '.join(failed_requirements)}"
            self.logger.error(error_message)
            raise RuntimeError(error_message)
        
        # Install pytest if not already installed
        try:
            self.logger.info("Installing pytest if not already installed")
            
            cmd = [
                str(pip_path),
                'install',
                'pytest',
                '--no-cache-dir'
            ]
            
            self.logger.info(f"Running pip with command: {' '.join(cmd)}")
            
            # Make sure pip_path is absolute
            if not os.path.isabs(str(pip_path)):
                pip_path = pip_path.absolute()
                self.logger.info(f"Using absolute pip path: {pip_path}")
            
            result = subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                text=True
            )
            
            self.logger.info("Successfully installed pytest")
        except subprocess.CalledProcessError as e:
            self.logger.warning(f"Failed to install pytest: {e.stderr}")
            raise RuntimeError("Failed to install pytest")
        
        return results 