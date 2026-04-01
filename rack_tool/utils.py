#!/usr/bin/env python3

import re

# --- Color Definitions ---
class Colors:
    """A class to hold ANSI color codes for terminal output."""
    GREEN = '\033[0;32m'
    RED = '\033[0;31m'
    YELLOW = '\033[1;33m'
    BLUE = '\033[0;34m'
    CYAN = '\033[0;36m'
    NC = '\033[0m' # No Color

def get_visible_length(s):
    """Returns the visible length of a string, ignoring ANSI escape codes."""
    # This regex removes all ANSI escape codes
    return len(re.sub(r'\x1b\[[0-9;]*m', '', s))