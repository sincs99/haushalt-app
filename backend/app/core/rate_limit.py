"""Zentrales Rate-Limiting-Modul (slowapi).

Eigenes Modul, um Circular Imports zwischen main.py und Routern zu vermeiden.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
