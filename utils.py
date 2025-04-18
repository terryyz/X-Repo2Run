#!/usr/bin/env python3
"""Utility functions for math operations."""

def add_numbers(a, b):
    """Add two numbers and return the result."""
    return a + b

def multiply_numbers(a, b):
    """Multiply two numbers and return the result."""
    return a * b

class MathClass:
    """A class for various math operations."""
    
    def square(self, n):
        """Return the square of a number."""
        return n * n
    
    def cube(self, n):
        """Return the cube of a number."""
        return n * n * n
    
    def factorial(self, n):
        """Return the factorial of a number."""
        if n == 0 or n == 1:
            return 1
        else:
            return n * self.factorial(n - 1) 