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
    """Test creating a virtual environment using uv init."""
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
    # Check that uv init was called with the correct arguments
    mock_run.assert_called_with(
        ['uv', 'init'],
        cwd=Path('.'),
        check=True,
        capture_output=True,
        text=True
    )


@patch("subprocess.run")
def test_install_requirements(mock_run):
    """Test installing requirements using uv add."""
    # Mock subprocess.run to return success
    mock_process = MagicMock()
    mock_process.returncode = 0
    mock_run.return_value = mock_process
    
    # Create installer
    installer = DependencyInstaller(Path("."))
    
    # Install requirements
    with patch.object(installer, "check_uv_installed", return_value=True):
        with patch.object(installer, "create_virtual_environment", return_value=Path("./.venv")):
            results = installer.install_requirements(["package1", "package2==1.0.0"])
    
    # Check results
    assert len(results) == 2
    assert results[0]["package"] == "package1"
    assert results[0]["success"] is True
    assert results[1]["package"] == "package2==1.0.0"
    assert results[1]["success"] is True
    
    # Check that uv add was called with the correct arguments
    assert mock_run.call_count >= 2  # At least 2 calls for the packages
    mock_run.assert_any_call(
        ['uv', 'add', 'package1', '--frozen', '--resolution lowest-direct'],
        cwd=Path('.'),
        check=True,
        capture_output=True,
        text=True
    )
    mock_run.assert_any_call(
        ['uv', 'add', 'package2==1.0.0', '--frozen', '--resolution lowest-direct'],
        cwd=Path('.'),
        check=True,
        capture_output=True,
        text=True
    ) 