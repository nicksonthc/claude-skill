import sys

# The tests import core/scorecard.py by path; a __pycache__ there would be vendored into every repo.
sys.dont_write_bytecode = True
