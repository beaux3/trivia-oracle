import json
import os

def _load_secrets() -> dict:
    path = os.path.join(os.path.dirname(__file__), "secrets.json")
    with open(path) as f:
        return json.load(f)

_secrets = _load_secrets()
TOKEN: str = _secrets["TELEGRAM_TOKEN"]

SCORES_FILE = "/app/scores.md"
POINTS_PER_CORRECT = 10
POINTS_PER_WRONG = 1
ADMIN_USERNAME = "terenegade"

# ── qbreader category/subcategory lists ───────────────────────────────────────
# All entries are valid qbreader Subcategory or AlternateSubcategory string values.
# They are split at query time into the correct API parameters (see round.py).

CATEGORIES = [
    # Literature — Subcategory + AlternateSubcategory
    "American Literature", "British Literature", "Classical Literature",
    "European Literature", "World Literature", "Other Literature",
    "Drama", "Long Fiction", "Poetry", "Short Fiction", "Misc Literature",
    # History — Subcategory
    "American History", "Ancient History", "European History",
    "World History", "Other History",
    # Science — Subcategory
    "Biology", "Chemistry", "Physics", "Other Science",
    # Science — AlternateSubcategory
    "Math", "Astronomy", "Computer Science", "Earth Science", "Engineering", "Misc Science",
    # Fine Arts — Subcategory
    "Visual Fine Arts", "Auditory Fine Arts", "Other Fine Arts",
    # Fine Arts — AlternateSubcategory
    "Architecture", "Dance", "Film", "Jazz", "Musicals", "Opera", "Photography", "Misc Arts",
    # Religion — Subcategory + AlternateSubcategory
    "Religion", "Beliefs", "Practices",
    # Standalone Subcategories (no further breakdown in qbreader)
    "Mythology", "Philosophy", "Current Events", "Geography", "Other Academic",
    # Social Science — Subcategory + AlternateSubcategory
    "Social Science", "Anthropology", "Economics", "Linguistics",
    "Psychology", "Sociology", "Other Social Science",
    # Pop Culture — Subcategory
    "Movies", "Music", "Sports", "Television", "Video Games", "Other Pop Culture",
]

# These are valid qbreader AlternateSubcategory values.
# At query time, selected entries from this set go to alternate_subcategories=;
# everything else goes to subcategories=. (See round.py: _build_api_filters)
ALL_ALT_SUBCATEGORIES = {
    "Drama", "Long Fiction", "Poetry", "Short Fiction", "Misc Literature",
    "Math", "Astronomy", "Computer Science", "Earth Science", "Engineering", "Misc Science",
    "Architecture", "Dance", "Film", "Jazz", "Musicals", "Opera", "Photography", "Misc Arts",
    "Beliefs", "Practices",
    "Anthropology", "Economics", "Linguistics", "Psychology", "Sociology", "Other Social Science",
}

# Convenience sets used by the category keyboard bulk-toggle buttons
ALL_SCIENCE = {
    "Biology", "Chemistry", "Physics", "Other Science",
    "Math", "Astronomy", "Computer Science", "Earth Science", "Engineering", "Misc Science",
}

ALL_ARTS = {
    "Visual Fine Arts", "Auditory Fine Arts", "Other Fine Arts",
    "Architecture", "Dance", "Film", "Jazz", "Musicals", "Opera", "Photography", "Misc Arts",
}

# ── Difficulty map: display label → qbreader numeric string ───────────────────
DIFFICULTIES = {
    "Unrated (0)":          "0",
    "Middle School (1)":    "1",
    "HS Easy (2)":          "2",
    "HS Regular (3)":       "3",
    "HS Hard (4)":          "4",
    "HS Nationals (5)":     "5",
    "College ⭐ (6)":       "6",
    "College ⭐⭐ (7)":     "7",
    "College ⭐⭐⭐ (8)":   "8",
    "College ⭐⭐⭐⭐ (9)": "9",
    "Open (10)":            "10",
}

# ── ConversationHandler state IDs ─────────────────────────────────────────────
SELECT_OPTION, SELECT_TIME_FIELD, INPUT_VALUE, SELECT_CATEGORIES, SELECT_DIFFICULTIES, SELECT_ADMIN = range(6)
