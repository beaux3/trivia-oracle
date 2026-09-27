"""Backend that calls the qbreader.org API through the vendored client."""
import os
import sys

# The vendored client imports itself as `qbreader.*`, so vendor/ must be on sys.path.
_VENDOR_DIR = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "vendor"))
if _VENDOR_DIR not in sys.path:
    sys.path.insert(0, _VENDOR_DIR)

from .qbreader_api import QbreaderAnswerJudge, QbreaderQuestionSource  # noqa: E402
