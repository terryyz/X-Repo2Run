"""
Repository manager for Repo2Run.

This module handles cloning repositories from GitHub and setting up local repositories.
"""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
import logging


class RepoManager:
    """
    Manages repository operations such as cloning and setting up local repositories.
    """
    
    def __init__(self, workspace_dir=None, logger=None):
        """
        Initialize the repository manager.
        
        Args:
            workspace_dir (str, optional): Directory to use as workspace. If None, a temporary directory is created.
            logger (logging.Logger, optional): Logger instance. If None, a new logger is created.
        """
        self.logger = logger or logging.getLogger(__name__)
        
        if workspace_dir:
            self.workspace_dir = Path(workspace_dir)
            self.workspace_dir.mkdir(parents=True, exist_ok=True)
            self.temp_dir = None
        else:
            self.temp_dir = tempfile.TemporaryDirectory()
            self.workspace_dir = Path(self.temp_dir.name)
        
        self.logger.debug(f"Workspace directory: {self.workspace_dir}")
    
    def __del__(self):
        """Clean up temporary directory if it exists."""
        if self.temp_dir:
            self.temp_dir.cleanup()
    
    def clone_repository(self, full_name, sha):
        """
        Clone a repository from GitHub.
        
        Args:
            full_name (str): Full name of the repository (e.g., "user/repo").
            sha (str): SHA of the commit to checkout.
        
        Returns:
            Path: Path to the cloned repository.
        
        Raises:
            ValueError: If the repository name is invalid.
            subprocess.CalledProcessError: If the clone or checkout fails.
        """
        if len(full_name.split('/')) != 2:
            raise ValueError("Repository name must be in the format 'user/repo'")
        
        author_name, repo_name = full_name.split('/')
        
        # Create directory structure
        repo_dir = self.workspace_dir / "github" / author_name / repo_name
        if repo_dir.exists():
            self.logger.info(f"Removing existing repository at {repo_dir}")
            shutil.rmtree(repo_dir)
        
        repo_dir.mkdir(parents=True, exist_ok=True)
        
        # Clone the repository
        self.logger.info(f"Cloning repository {full_name}")
        clone_cmd = f"git clone https://github.com/{full_name}.git {repo_dir}"
        
        try:
            subprocess.run(clone_cmd, shell=True, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
            self.logger.error(f"Failed to clone repository: {e.stderr}")
            raise
        
        # Checkout the specified SHA
        self.logger.info(f"Checking out SHA {sha}")
        checkout_cmd = f"git checkout {sha}"
        
        try:
            subprocess.run(checkout_cmd, cwd=repo_dir, shell=True, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
            self.logger.error(f"Failed to checkout SHA: {e.stderr}")
            raise
        
        # Save SHA information
        with open(repo_dir / "sha.txt", "w") as f:
            f.write(sha)
        
        self.logger.info(f"Repository cloned successfully to {repo_dir}")
        return repo_dir
    
    def setup_local_repository(self, local_path):
        """
        Set up a local repository for processing.
        
        Args:
            local_path (Path): Path to the local repository.
        
        Returns:
            Path: Path to the set up repository.
        
        Raises:
            FileNotFoundError: If the local path does not exist.
        """
        if not local_path.exists():
            raise FileNotFoundError(f"Local path {local_path} does not exist")
        
        # Extract repository name from the local path
        repo_name = local_path.name
        
        # Create directory structure
        repo_dir = self.workspace_dir / "local" / repo_name
        if repo_dir.exists():
            self.logger.info(f"Removing existing repository at {repo_dir}")
            shutil.rmtree(repo_dir)
        
        repo_dir.mkdir(parents=True, exist_ok=True)
        
        # Copy all files from local_path to repository directory
        self.logger.info(f"Copying files from {local_path} to {repo_dir}")
        
        for item in os.listdir(local_path):
            src = local_path / item
            dst = repo_dir / item
            
            if dst.exists():
                if dst.is_dir():
                    shutil.rmtree(dst)
                else:
                    dst.unlink()
            
            if src.is_dir():
                shutil.copytree(src, dst)
            else:
                shutil.copy2(src, dst)
        
        # Save SHA information (using "local" as placeholder)
        with open(repo_dir / "sha.txt", "w") as f:
            f.write("local")
        
        self.logger.info(f"Local repository set up successfully at {repo_dir}")
        return repo_dir 