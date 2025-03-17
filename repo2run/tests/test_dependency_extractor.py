"""
Tests for the dependency extractor.
"""

import os
import tempfile
from pathlib import Path
import pytest

from repo2run.utils.dependency_extractor import DependencyExtractor


def test_extract_from_requirements_txt():
    """Test extracting dependencies from requirements.txt."""
    with tempfile.TemporaryDirectory() as temp_dir:
        # Create a requirements.txt file
        temp_path = Path(temp_dir)
        req_file = temp_path / "requirements.txt"
        
        with open(req_file, "w") as f:
            f.write("package1==1.0.0\n")
            f.write("package2>=2.0.0\n")
            f.write("# Comment\n")
            f.write("package3\n")
        
        # Create extractor
        extractor = DependencyExtractor(temp_path)
        
        # Extract requirements
        requirements = extractor._extract_from_requirements_txt()
        
        # Check results
        assert "requirements.txt" in requirements
        assert len(requirements["requirements.txt"]) == 3
        assert "package1==1.0.0" in requirements["requirements.txt"]
        assert "package2>=2.0.0" in requirements["requirements.txt"]
        assert "package3" in requirements["requirements.txt"]


def test_unify_requirements():
    """Test unifying requirements from multiple sources."""
    # Create extractor
    extractor = DependencyExtractor(Path("."))
    
    # Create requirements
    requirements = {
        "source1": ["package1==1.0.0", "package2>=2.0.0", "package3"],
        "source2": ["package1==1.0.0", "package4", "package5==5.0.0"],
    }
    
    # Unify requirements
    unified = extractor.unify_requirements(requirements)
    
    # Check results
    assert len(unified) == 5
    assert "package1==1.0.0" in unified
    assert "package2>=2.0.0" in unified
    assert "package3" in unified
    assert "package4" in unified
    assert "package5==5.0.0" in unified 