from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from .config import ALL_ARTS, ALL_SCIENCE, CATEGORIES, DIFFICULTIES, SCORING_MODES
from .settings import settings


def build_category_keyboard() -> InlineKeyboardMarkup:
    rows = []
    for i in range(0, len(CATEGORIES), 2):
        row = []
        for cat in CATEGORIES[i:i + 2]:
            mark = "✅" if cat in settings.selected_categories else "☐"
            suffix = " 🔬" if cat in ALL_SCIENCE else " 🎭" if cat in ALL_ARTS else ""
            row.append(InlineKeyboardButton(f"{mark} {cat}{suffix}", callback_data=f"cat:{cat}"))
        rows.append(row)

    arts_on = ALL_ARTS.issubset(settings.selected_categories)
    rows.append([InlineKeyboardButton(
        "🎭 ☐ Deselect All Arts 🎭" if arts_on else "🎭 ✅ Select All Arts 🎭",
        callback_data="cat_toggle_arts",
    )])

    science_on = ALL_SCIENCE.issubset(settings.selected_categories)
    rows.append([InlineKeyboardButton(
        "🔬 ☐ Deselect All Science 🔬" if science_on else "🔬 ✅ Select All Science 🔬",
        callback_data="cat_toggle_science",
    )])

    all_on = settings.selected_categories == set(CATEGORIES)
    rows.append([InlineKeyboardButton(
        "☐ Deselect All" if all_on else "✅ Select All",
        callback_data="cat_toggle_all",
    )])
    rows.append([InlineKeyboardButton("💾 Save", callback_data="cat_save")])
    return InlineKeyboardMarkup(rows)


def build_difficulty_keyboard() -> InlineKeyboardMarkup:
    rows = []
    diff_names = list(DIFFICULTIES.keys())
    for i in range(0, len(diff_names), 2):
        row = []
        for name in diff_names[i:i + 2]:
            mark = "✅" if name in settings.selected_difficulties else "☐"
            row.append(InlineKeyboardButton(f"{mark} {name}", callback_data=f"diff:{name}"))
        rows.append(row)

    all_on = settings.selected_difficulties == set(DIFFICULTIES)
    rows.append([InlineKeyboardButton(
        "☐ Deselect All" if all_on else "✅ Select All",
        callback_data="diff_toggle_all",
    )])
    rows.append([InlineKeyboardButton("💾 Save", callback_data="diff_save")])
    return InlineKeyboardMarkup(rows)


def build_scoring_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(
            f"{'✅' if key in settings.scoring_modes else '☐'} {label}",
            callback_data=f"score:{key}",
        )]
        for key, label in SCORING_MODES.items()
    ]
    rows.append([InlineKeyboardButton("💾 Save", callback_data="score_save")])
    return InlineKeyboardMarkup(rows)


def build_admin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🗑 Reset All Scores", callback_data="admin_reset")],
    ])
