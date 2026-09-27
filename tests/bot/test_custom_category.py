"""Custom categories: the /configure buttons ("All Custom" + one per category), how they become a
backend request, and the round header."""
import os
import unittest
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("TELEGRAM_TOKEN", "test-token")

from trivia_oracle_bot.bot import handlers
from trivia_oracle_bot.bot.keyboards import build_category_keyboard
from trivia_oracle_bot.config import CATEGORIES, CUSTOM_CATEGORIES, SELECT_CATEGORIES
from trivia_oracle_bot.game import round as rnd
from trivia_oracle_bot.game.settings import settings
from trivia_oracle_bot.questions import Tossup


class _SettingsCase(unittest.TestCase):
    def setUp(self):
        saved = dict(vars(settings))
        self.addCleanup(lambda: (vars(settings).clear(), vars(settings).update(saved)))
        settings.selected_categories = set(CATEGORIES)
        settings.custom_all = False
        settings.selected_custom_categories = set()


def _button_labels(markup):
    return {button.callback_data: button.text for row in markup.inline_keyboard for button in row}


def _click(data):
    query = mock.Mock(data=data)
    update = SimpleNamespace(callback_query=query)
    return handlers.configure_toggle_category(update, None), query


class CustomKeyboardTest(_SettingsCase):
    def test_all_custom_is_off_by_default_and_has_its_own_button(self):
        self.assertFalse(settings.custom_all)
        label = _button_labels(build_category_keyboard())["cat_toggle_custom_all"]
        self.assertIn("All Custom", label)
        self.assertIn("☐", label)

    def test_every_custom_category_gets_its_own_unticked_button(self):
        labels = _button_labels(build_category_keyboard())
        for cat in CUSTOM_CATEGORIES:
            label = labels[f"cat_custom:{cat}"]
            self.assertIn(f"Custom: {cat}", label)
            self.assertIn("☐", label)

    def test_all_custom_button_shows_a_tick_once_on(self):
        settings.custom_all = True
        self.assertIn("✅", _button_labels(build_category_keyboard())["cat_toggle_custom_all"])

    def test_a_specific_category_button_shows_a_tick_once_selected(self):
        settings.selected_custom_categories = {"Singapore"}
        labels = _button_labels(build_category_keyboard())
        self.assertIn("✅", labels["cat_custom:Singapore"])
        self.assertIn("☐", labels["cat_custom:Memes"])

    def test_clicking_all_custom_toggles_it_without_touching_anything_else(self):
        state, query = _click("cat_toggle_custom_all")
        self.assertEqual(state, SELECT_CATEGORIES)
        self.assertTrue(settings.custom_all)
        self.assertEqual(settings.selected_categories, set(CATEGORIES))
        self.assertEqual(settings.selected_custom_categories, set())
        query.edit_message_reply_markup.assert_called_once()

        _click("cat_toggle_custom_all")
        self.assertFalse(settings.custom_all)

    def test_clicking_a_specific_category_toggles_only_that_one(self):
        _click("cat_custom:Singapore")
        self.assertEqual(settings.selected_custom_categories, {"Singapore"})
        self.assertFalse(settings.custom_all)

        _click("cat_custom:Memes")
        self.assertEqual(settings.selected_custom_categories, {"Singapore", "Memes"})

        _click("cat_custom:Singapore")
        self.assertEqual(settings.selected_custom_categories, {"Memes"})

    def test_select_all_and_deselect_all_leave_custom_picks_alone(self):
        settings.custom_all = True
        settings.selected_custom_categories = {"Snowsports"}
        _click("cat_toggle_all")
        self.assertEqual(settings.selected_categories, set())
        self.assertTrue(settings.custom_all)
        self.assertEqual(settings.selected_custom_categories, {"Snowsports"})
        _click("cat_toggle_all")
        self.assertEqual(settings.selected_categories, set(CATEGORIES))
        self.assertTrue(settings.custom_all)
        self.assertEqual(settings.selected_custom_categories, {"Snowsports"})

    def test_all_custom_alone_is_enough_to_save(self):
        settings.selected_categories = set()
        settings.custom_all = True
        _, query = _click("cat_save")
        self.assertIn("Categories saved", query.edit_message_text.call_args.args[0])
        self.assertIn("All Custom", query.edit_message_text.call_args.args[0])

    def test_a_specific_custom_category_alone_is_enough_to_save(self):
        settings.selected_categories = set()
        settings.selected_custom_categories = {"Memes"}
        _, query = _click("cat_save")
        self.assertIn("Categories saved", query.edit_message_text.call_args.args[0])
        self.assertIn("Custom: Memes", query.edit_message_text.call_args.args[0])

    def test_saving_with_nothing_selected_is_still_refused(self):
        settings.selected_categories = set()
        state, query = _click("cat_save")
        self.assertEqual(state, SELECT_CATEGORIES)
        query.answer.assert_called_with("⚠️ Select at least one category!", show_alert=True)

    def test_saved_summary_mentions_custom_picks_next_to_the_other_categories(self):
        settings.selected_categories = {"Biology"}
        settings.custom_all = True
        _, query = _click("cat_save")
        self.assertEqual(query.edit_message_text.call_args.args[0], "✅ Categories saved:\nBiology, All Custom")

    def test_saved_summary_lists_each_specific_custom_category(self):
        settings.selected_categories = {"Biology"}
        settings.selected_custom_categories = {"Memes", "Singapore"}
        _, query = _click("cat_save")
        self.assertEqual(
            query.edit_message_text.call_args.args[0],
            "✅ Categories saved:\nBiology, Custom: Singapore, Custom: Memes",
        )


class BuildFiltersCustomTest(_SettingsCase):
    def test_no_custom_selection_excludes_custom_questions(self):
        self.assertEqual(rnd._build_filters().custom, "exclude")

    def test_all_custom_with_other_categories_mixes_them_in(self):
        settings.custom_all = True
        filters = rnd._build_filters()
        self.assertEqual((filters.custom, filters.custom_subcategories), ("include", None))
        settings.selected_categories = {"Biology"}
        filters = rnd._build_filters()
        self.assertEqual((filters.custom, filters.subcategories, filters.custom_subcategories),
                         ("include", ["Biology"], None))

    def test_all_custom_with_nothing_else_selected_is_custom_only(self):
        settings.custom_all = True
        settings.selected_categories = set()
        self.assertEqual(rnd._build_filters().custom, "only")

    def test_a_specific_custom_category_narrows_the_custom_draw(self):
        settings.selected_custom_categories = {"Memes"}
        settings.selected_categories = set()
        filters = rnd._build_filters()
        self.assertEqual((filters.custom, filters.custom_subcategories), ("only", ["Memes"]))

    def test_several_specific_custom_categories_are_all_passed_through(self):
        settings.selected_custom_categories = {"Memes", "Singapore"}
        settings.selected_categories = set()
        self.assertEqual(rnd._build_filters().custom_subcategories, ["Memes", "Singapore"])

    def test_all_custom_overrides_specific_categories_in_the_wire_filter(self):
        settings.custom_all = True
        settings.selected_custom_categories = {"Memes"}
        settings.selected_categories = set()
        # "All Custom" draws from the whole database; custom_subcategories stays unset even
        # though a specific category is also ticked.
        self.assertEqual(rnd._build_filters().custom_subcategories, None)


def _tossup(**overrides):
    fields = dict(question_sanitized="Clue one. Clue two.", answer="Answer", answer_sanitized="Answer")
    return Tossup(**{**fields, **overrides})


class RoundHeaderTest(_SettingsCase):
    def setUp(self):
        super().setUp()
        settings.sentence_interval = 0.01
        settings.answer_wait = 0.01

    def tearDown(self):
        if rnd.round_lock.locked():
            rnd.round_lock.release()
        rnd.current_round["active"] = False

    def _play(self, tossup):
        """Start a round on `tossup` and run it to the end on this thread, returning what was announced."""
        messages = []
        with mock.patch.object(rnd, "_fetch_tossup", mock.AsyncMock(return_value=tossup)), \
             mock.patch.object(rnd.threading, "Thread"):
            rnd.start_round(messages.append, "", {})
        rnd._run_round(messages.append, "")
        return messages

    def test_custom_round_announces_the_label_and_category_in_its_own_message_before_the_first_clue(self):
        messages = self._play(_tossup(custom=True, category="Singapore"))
        self.assertEqual(messages[0], "📝 Custom question\nCategory: Singapore")
        self.assertEqual(messages[1], "🎯\nClue one.\n⏳⏳")

    def test_the_label_is_only_sent_once(self):
        messages = self._play(_tossup(custom=True, category="Singapore"))
        self.assertEqual(messages[2], "🎯🎯\nClue two.\n⏳")
        self.assertEqual(sum("Custom question" in m for m in messages), 1)

    def test_custom_question_without_a_category_still_says_it_is_custom(self):
        messages = self._play(_tossup(custom=True))
        self.assertEqual(messages[0], "📝 Custom question")
        self.assertEqual(messages[1], "🎯\nClue one.\n⏳⏳")

    def test_ordinary_questions_have_no_label(self):
        messages = self._play(_tossup())
        self.assertEqual(messages[0], "🎯\nClue one.\n⏳⏳")

    def test_a_later_ordinary_round_does_not_inherit_the_label(self):
        self._play(_tossup(custom=True, category="Singapore"))
        messages = self._play(_tossup(question_sanitized="Other clue one. Other clue two."))
        self.assertNotIn("Custom", messages[0])


if __name__ == "__main__":
    unittest.main()
