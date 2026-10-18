"""Old name of bench/taskmetrics.py (measurements work between any models and agents); the module is aliased, so every
existing `import mechanical` and `mechanical.<name>` keeps working."""
import sys

import taskmetrics

sys.modules[__name__] = taskmetrics
