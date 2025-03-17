"""
Tests for the dependency installer.
"""

import os
import tempfile
from pathlib import Path
import pytest
from unittest.mock import patch, MagicMock

from repo2run.utils.dependency_installer import DependencyInstaller


@patch("subprocess.run")
def test_check_uv_installed_success(mock_run):
    """Test checking if UV is installed (success case)."""
    # Mock subprocess.run to return success
    mock_process = MagicMock()
    mock_process.returncode = 0
    mock_process.stdout = "uv 0.1.0"
    mock_run.return_value = mock_process
    
    # Create installer
    installer = DependencyInstaller(Path("."))
    
    # Check if UV is installed
    result = installer.check_uv_installed()
    
    # Check results
    assert result is True
    mock_run.assert_called_once()


@patch("subprocess.run")
def test_check_uv_installed_failure_then_install(mock_run):
    """Test checking if UV is installed (failure case, then install)."""
    # Mock subprocess.run to return failure then success
    mock_process_failure = MagicMock()
    mock_process_failure.returncode = 1
    
    mock_process_success = MagicMock()
    mock_process_success.returncode = 0
    
    mock_run.side_effect = [mock_process_failure, mock_process_success]
    
    # Create installer
    installer = DependencyInstaller(Path("."))
    
    # Check if UV is installed
    result = installer.check_uv_installed()
    
    # Check results
    assert result is True
    assert mock_run.call_count == 2


@patch("subprocess.run")
def test_create_virtual_environment(mock_run):
    """Test creating a virtual environment."""
    # Mock subprocess.run to return success
    mock_process = MagicMock()
    mock_process.returncode = 0
    mock_run.return_value = mock_process
    
    # Create installer
    installer = DependencyInstaller(Path("."))
    
    # Create virtual environment
    with patch.object(installer, "check_uv_installed", return_value=True):
        venv_path = installer.create_virtual_environment()
    
    # Check results
    assert venv_path == Path("./.venv")
    assert mock_run.call_count == 1 