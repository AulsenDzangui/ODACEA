"""Configuration pytest du backend.

Rend les packages du moteur (`core`, `prompts`, …) importables quel que soit le
répertoire d'invocation de pytest, sans installation éditable préalable.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
