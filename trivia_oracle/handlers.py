import logging
import sys

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import Conflict
from telegram.ext import ConversationHandler

from .config import (
    ADMIN_USERNAME, ALL_ARTS, ALL_SCIENCE, CATEGORIES, DIFFICULTIES,
    INPUT_VALUE, SELECT_ADMIN, SELECT_CATEGORIES, SELECT_DIFFICULTIES,
    SELECT_OPTION, SELECT_TIME_FIELD,
)
from .keyboards import build_admin_keyboard, build_category_keyboard, build_difficulty_keyboard
from .scores import format_scoreboard, save_scores, scores, scores_lock
from .settings import settings


# ── /scores ───────────────────────────────────────────────────────────────────

def show_scores(update, _context) -> None:
    update.message.reply_text(format_scoreboard())


# ── /configure — entry point ──────────────────────────────────────────────────

def configure(update, _context) -> int:
    update.message.reply_text(
        "What would you like to configure?",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⏱ Time", callback_data="time")],
            [InlineKeyboardButton("📚 Categories", callback_data="category")],
            [InlineKeyboardButton("🎯 Difficulty", callback_data="difficulty")],
            [InlineKeyboardButton("👁 View Current Settings", callback_data="view_settings")],
            [InlineKeyboardButton("🔒 Admin Settings", callback_data="admin")],
        ]),
    )
    return SELECT_OPTION


# ── SELECT_OPTION state ───────────────────────────────────────────────────────

def configure_select_option(update, context) -> int:
    query = update.callback_query

    if query.data == "admin":
        if not ADMIN_USERNAME or update.effective_user.username != ADMIN_USERNAME:
            query.answer("⛔ Access denied.", show_alert=True)
            return SELECT_OPTION
        query.answer()
        query.edit_message_text("🔒 Admin Settings", reply_markup=build_admin_keyboard())
        return SELECT_ADMIN

    query.answer()

    if query.data == "view_settings":
        cats = "All" if settings.selected_categories == set(CATEGORIES) else ", ".join(sorted(settings.selected_categories))
        diffs = "All" if settings.selected_difficulties == set(DIFFICULTIES) else ", ".join(settings.selected_difficulties)
        query.edit_message_text(
            f"⚙️ Current Settings\n\n"
            f"⏱ Sentence Interval: {settings.sentence_interval}s\n"
            f"⏱ Answer Wait: {settings.answer_wait}s\n\n"
            f"📚 Categories:\n{cats}\n\n"
            f"🎯 Difficulties:\n{diffs}"
        )
        return ConversationHandler.END

    if query.data == "time":
        query.edit_message_text(
            "Which time setting?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(f"Sentence Interval (current: {settings.sentence_interval}s)", callback_data="sentence_interval")],
                [InlineKeyboardButton(f"Answer Wait (current: {settings.answer_wait}s)", callback_data="answer_wait")],
            ]),
        )
        return SELECT_TIME_FIELD

    if query.data == "category":
        label = "All categories" if settings.selected_categories == set(CATEGORIES) else f"{len(settings.selected_categories)} selected"
        query.edit_message_text(f"Toggle categories on/off ({label}):", reply_markup=build_category_keyboard())
        return SELECT_CATEGORIES

    # query.data == "difficulty"
    label = "All difficulties" if settings.selected_difficulties == set(DIFFICULTIES) else f"{len(settings.selected_difficulties)} selected"
    query.edit_message_text(f"Toggle difficulties on/off ({label}):", reply_markup=build_difficulty_keyboard())
    return SELECT_DIFFICULTIES


# ── SELECT_TIME_FIELD state ───────────────────────────────────────────────────

def configure_select_time_field(update, context) -> int:
    query = update.callback_query
    query.answer()
    context.user_data["field"] = query.data
    if query.data == "sentence_interval":
        query.edit_message_text(f"Enter new Sentence Interval in seconds (current: {settings.sentence_interval}s):")
    else:
        query.edit_message_text(f"Enter new Answer Wait in seconds (current: {settings.answer_wait}s):")
    return INPUT_VALUE


# ── INPUT_VALUE state ─────────────────────────────────────────────────────────

def configure_input_value(update, context) -> int:
    try:
        value = float(update.message.text.strip())
        if value <= 0:
            raise ValueError
    except ValueError:
        update.message.reply_text("Please enter a valid positive number.")
        return INPUT_VALUE

    field = context.user_data.get("field")
    if field == "sentence_interval":
        settings.sentence_interval = value
        update.message.reply_text(f"✅ Sentence Interval set to {value}s")
    elif field == "answer_wait":
        settings.answer_wait = value
        update.message.reply_text(f"✅ Answer Wait set to {value}s")
    return ConversationHandler.END


# ── SELECT_CATEGORIES state ───────────────────────────────────────────────────

def configure_toggle_category(update, _context) -> int:
    query = update.callback_query
    query.answer()

    if query.data == "cat_save":
        if not settings.selected_categories:
            query.answer("⚠️ Select at least one category!", show_alert=True)
            return SELECT_CATEGORIES
        label = "All categories" if settings.selected_categories == set(CATEGORIES) else ", ".join(sorted(settings.selected_categories))
        query.edit_message_text(f"✅ Categories saved:\n{label}")
        return ConversationHandler.END

    if query.data == "cat_toggle_arts":
        if ALL_ARTS.issubset(settings.selected_categories):
            settings.selected_categories -= ALL_ARTS
        else:
            settings.selected_categories |= ALL_ARTS
    elif query.data == "cat_toggle_science":
        if ALL_SCIENCE.issubset(settings.selected_categories):
            settings.selected_categories -= ALL_SCIENCE
        else:
            settings.selected_categories |= ALL_SCIENCE
    elif query.data == "cat_toggle_all":
        if settings.selected_categories == set(CATEGORIES):
            settings.selected_categories.clear()
        else:
            settings.selected_categories = set(CATEGORIES)
    else:
        cat = query.data[len("cat:"):]
        if cat in settings.selected_categories:
            settings.selected_categories.discard(cat)
        else:
            settings.selected_categories.add(cat)

    query.edit_message_reply_markup(reply_markup=build_category_keyboard())
    return SELECT_CATEGORIES


# ── SELECT_DIFFICULTIES state ─────────────────────────────────────────────────

def configure_toggle_difficulty(update, _context) -> int:
    query = update.callback_query
    query.answer()

    if query.data == "diff_save":
        if not settings.selected_difficulties:
            query.answer("⚠️ Select at least one difficulty!", show_alert=True)
            return SELECT_DIFFICULTIES
        label = "All difficulties" if settings.selected_difficulties == set(DIFFICULTIES) else ", ".join(settings.selected_difficulties)
        query.edit_message_text(f"✅ Difficulties saved:\n{label}")
        return ConversationHandler.END

    if query.data == "diff_toggle_all":
        if settings.selected_difficulties == set(DIFFICULTIES):
            settings.selected_difficulties.clear()
        else:
            settings.selected_difficulties = set(DIFFICULTIES)
    else:
        name = query.data[len("diff:"):]
        if name in settings.selected_difficulties:
            settings.selected_difficulties.discard(name)
        else:
            settings.selected_difficulties.add(name)

    query.edit_message_reply_markup(reply_markup=build_difficulty_keyboard())
    return SELECT_DIFFICULTIES


# ── SELECT_ADMIN state ────────────────────────────────────────────────────────

def configure_admin(update, _context) -> int:
    query = update.callback_query
    if not ADMIN_USERNAME or update.effective_user.username != ADMIN_USERNAME:
        query.answer("⛔ Access denied.", show_alert=True)
        return ConversationHandler.END

    query.answer()

    if query.data == "admin_reset":
        query.edit_message_text(
            "⚠️ Are you sure you want to reset ALL scores? This cannot be undone.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ Yes, reset", callback_data="admin_reset_confirm"),
                InlineKeyboardButton("❌ No, cancel", callback_data="admin_reset_cancel"),
            ]]),
        )
    elif query.data == "admin_reset_confirm":
        with scores_lock:
            scores.clear()
            save_scores()
        query.edit_message_text("✅ All scores have been reset.")
        return ConversationHandler.END
    elif query.data == "admin_reset_cancel":
        query.edit_message_text("🔒 Admin Settings", reply_markup=build_admin_keyboard())

    return SELECT_ADMIN


# ── Error handler ─────────────────────────────────────────────────────────────

def error_handler(update, context) -> None:
    if isinstance(context.error, Conflict):
        logging.error("Another bot instance is already running. Shutting down.")
        sys.exit(1)
    logging.error("Update %s caused error: %s", update, context.error)
