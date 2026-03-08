"""
dotconfig - Environment configuration cascade manager for .env files.

Manages a layered configuration system where environment variables are
assembled from multiple source files (common config, secrets, and
developer-local overrides) into a single .env file with marked sections
that can be round-tripped back to the source files.
"""

__version__ = "0.1.0"
