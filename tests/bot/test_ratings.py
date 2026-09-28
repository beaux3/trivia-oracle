"""Rating a custom question with /good or /bad after its round: the prompt, the one-vote-per-player rule, the window."""
import os
import threading
import unittest
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("TELEGRAM_TOKEN", "test-token")

from trivia_oracle_bot.bot import round_handlers
from trivia_oracle_bot.bot.app import register_handlers
from trivia_oracle_bot.game import round as rnd
from trivia_oracle_bot.game.settings import settings
from trivia_oracle_bot.questions import Tossup

END_HINT = "\n\nNext question: /next@TriviaOracleBot"
RATE_PROMPT = "\n\nPlease rate the question /good or /bad"


def _tossup(**overrides):
    fields = dict(question_sanitized="Clue one. Clue two.", answer="Answer", answer_sanitized="Answer")
    return Tossup(**{**fields, **overrides})


def _custom(id="merlion", **overrides):
    return _tossup(custom=True, category="Singapore", id=id, **overrides)


class _RoundCase(unittest.TestCase):
    def setUp(self):
        saved = dict(vars(settings))
        self.addCleanup(lambda: (vars(settings).clear(), vars(settings).update(saved)))
        settings.sentence_interval = 0.01
        settings.answer_wait = 0.01
        self.backend = mock.Mock()
        self.backend.rate_tossup = mock.AsyncMock(return_value=(1, 0))
        self.backend.record_play = mock.AsyncMock(return_value=(1, 0, None))
        patch = mock.patch.object(rnd, "question_source", self.backend)
        patch.start()
        self.addCleanup(patch.stop)

    def tearDown(self):
        if rnd.round_lock.locked():
            rnd.round_lock.release()
        rnd.current_round["active"] = False
        rnd.current_round["rating"] = None
        rnd.current_round["ended_at"] = None

    def play(self, tossup):
        """Start a round on `tossup` and run it to its end on this thread, returning what was announced."""
        messages = []
        with mock.patch.object(rnd, "_fetch_tossup", mock.AsyncMock(return_value=tossup)), \
             mock.patch.object(rnd.threading, "Thread"):
            rnd.start_round(messages.append, END_HINT, {})
        rnd._run_round(messages.append, END_HINT)
        return messages

    def votes_sent(self):
        return [call.args for call in self.backend.rate_tossup.await_args_list]


class RatingPromptTest(_RoundCase):
    def test_a_custom_round_ends_by_asking_for_a_rating(self):
        messages = self.play(_custom())
        end = next(m for m in messages if "[ROUND END]" in m)
        self.assertTrue(end.endswith(END_HINT + RATE_PROMPT), end)

    def test_the_prompt_comes_after_the_answer_and_the_next_hint(self):
        end = next(m for m in self.play(_custom(answer_sanitized="Hainanese chicken rice")) if "[ROUND END]" in m)
        self.assertLess(end.index("Hainanese chicken rice"), end.index("Next question:"))
        self.assertLess(end.index("Next question:"), end.index("Please rate the question /good or /bad"))

    def test_the_prompt_is_there_when_nobody_answered_too(self):
        messages = self.play(_custom())
        self.assertIn("nobody answered correctly", "\n".join(messages))
        self.assertIn("/good or /bad", "\n".join(messages))

    def test_ordinary_rounds_do_not_ask(self):
        self.assertNotIn("/good", "\n".join(self.play(_tossup(id=None))))

    def test_a_custom_question_the_backend_gave_no_id_for_cannot_be_rated_so_is_not_asked_about(self):
        self.assertNotIn("/good", "\n".join(self.play(_tossup(custom=True, category="Singapore"))))

    def test_the_prompt_is_only_in_the_round_end_message(self):
        messages = self.play(_custom())
        self.assertEqual(sum("/good" in m for m in messages), 1)


class SubmitRatingTest(_RoundCase):
    def test_a_vote_after_the_round_is_sent_to_the_backend(self):
        self.play(_custom("merlion"))
        rnd.submit_rating(1, "good")
        self.assertEqual(self.votes_sent(), [("merlion", "good", None)])

    def test_bad_votes_work_too(self):
        self.play(_custom("merlion"))
        rnd.submit_rating(1, "bad")
        self.assertEqual(self.votes_sent(), [("merlion", "bad", None)])

    def test_each_player_counts_once(self):
        self.play(_custom("merlion"))
        rnd.submit_rating(1, "good")
        rnd.submit_rating(2, "good")
        rnd.submit_rating(3, "bad")
        self.assertEqual(self.votes_sent(), [
            ("merlion", "good", None), ("merlion", "good", None), ("merlion", "bad", None),
        ])

    def test_spamming_the_same_vote_is_ignored(self):
        self.play(_custom("merlion"))
        for _ in range(10):
            rnd.submit_rating(1, "good")
        self.assertEqual(self.votes_sent(), [("merlion", "good", None)])

    def test_a_player_who_pressed_the_wrong_one_can_switch_and_the_old_vote_is_withdrawn(self):
        self.play(_custom("merlion"))
        rnd.submit_rating(1, "good")
        rnd.submit_rating(1, "bad")
        self.assertEqual(self.votes_sent(), [("merlion", "good", None), ("merlion", "bad", "good")])

    def test_the_latest_of_a_flurry_of_switches_is_the_one_that_stands(self):
        self.play(_custom("merlion"))
        for rating in ("good", "bad", "bad", "good", "good", "bad"):
            rnd.submit_rating(1, rating)
        self.assertEqual(self.votes_sent(), [
            ("merlion", "good", None), ("merlion", "bad", "good"),
            ("merlion", "good", "bad"), ("merlion", "bad", "good"),
        ])

    def test_switching_back_and_forth_keeps_one_vote_in_total(self):
        self.play(_custom("merlion"))
        tally = {"good": 0, "bad": 0}

        async def rate(_id, rating, previous):
            tally[rating] += 1
            if previous:
                tally[previous] -= 1
            return (tally["good"], tally["bad"])

        self.backend.rate_tossup = mock.AsyncMock(side_effect=rate)
        for rating in ("good", "bad", "good", "bad", "bad", "good"):
            rnd.submit_rating(1, rating)
        self.assertEqual(tally, {"good": 1, "bad": 0})

    def test_an_invalid_rating_is_ignored(self):
        self.play(_custom("merlion"))
        rnd.submit_rating(1, "great")
        self.assertEqual(self.votes_sent(), [])

    def test_nothing_to_rate_before_any_round(self):
        rnd.current_round["rating"] = None
        rnd.submit_rating(1, "good")
        self.assertEqual(self.votes_sent(), [])

    def test_ordinary_questions_cannot_be_rated(self):
        self.play(_tossup(id=None))
        rnd.submit_rating(1, "good")
        self.assertEqual(self.votes_sent(), [])

    def test_no_voting_while_the_round_is_still_running(self):
        messages = []
        with mock.patch.object(rnd, "_fetch_tossup", mock.AsyncMock(return_value=_custom())), \
             mock.patch.object(rnd.threading, "Thread"):
            rnd.start_round(messages.append, END_HINT, {})
        rnd.submit_rating(1, "good")  # the tossup is still being read out
        self.assertEqual(self.votes_sent(), [])

    def test_voting_closes_when_the_next_round_starts(self):
        self.play(_custom("merlion"))
        with mock.patch.object(rnd, "RATING_GRACE_PERIOD", 0):  # bypass the /next rating gate for this test
            self.play(_tossup(id=None))
        rnd.submit_rating(1, "good")
        self.assertEqual(self.votes_sent(), [])

    def test_a_new_custom_round_rates_the_new_question_and_players_may_vote_again(self):
        self.play(_custom("merlion"))
        rnd.submit_rating(1, "good")
        self.play(_custom("laksa"))
        rnd.submit_rating(1, "good")
        self.assertEqual(self.votes_sent(), [("merlion", "good", None), ("laksa", "good", None)])

    def test_the_same_question_coming_round_again_lets_a_player_vote_again(self):
        self.play(_custom("merlion"))
        rnd.submit_rating(1, "good")
        self.play(_custom("merlion"))
        rnd.submit_rating(1, "good")
        self.assertEqual(self.votes_sent(), [("merlion", "good", None), ("merlion", "good", None)])

    def test_a_failed_round_start_does_not_close_voting(self):
        self.play(_custom("merlion"))
        with mock.patch.object(rnd, "RATING_GRACE_PERIOD", 0), \
             mock.patch.object(rnd, "_fetch_tossup", mock.AsyncMock(side_effect=RuntimeError("backend down"))):
            self.assertEqual(rnd.start_round(lambda _: None, END_HINT, {}), rnd.StartResult.FETCH_FAILED)
        rnd.submit_rating(1, "good")
        self.assertEqual(self.votes_sent(), [("merlion", "good", None)])

    def test_a_vote_the_backend_failed_to_record_does_not_count_and_can_be_retried(self):
        self.play(_custom("merlion"))
        self.backend.rate_tossup.side_effect = RuntimeError("backend down")
        rnd.submit_rating(1, "good")  # must not raise
        self.backend.rate_tossup.side_effect = None
        rnd.submit_rating(1, "good")
        self.assertEqual(self.votes_sent(), [("merlion", "good", None), ("merlion", "good", None)])

    def test_a_failed_switch_leaves_the_old_vote_standing(self):
        self.play(_custom("merlion"))
        rnd.submit_rating(1, "good")
        self.backend.rate_tossup.side_effect = RuntimeError("backend down")
        rnd.submit_rating(1, "bad")
        self.backend.rate_tossup.side_effect = None
        rnd.submit_rating(1, "bad")
        self.assertEqual(self.votes_sent()[-1], ("merlion", "bad", "good"))

    def test_a_late_vote_for_the_old_question_does_not_leak_into_the_next_round(self):
        self.play(_custom("merlion"))
        started, release = threading.Event(), threading.Event()

        async def slow_rate(*args):
            started.set()
            release.wait(5)
            return (1, 0)

        self.backend.rate_tossup = mock.AsyncMock(side_effect=slow_rate)
        worker = threading.Thread(target=rnd.submit_rating, args=(1, "good"))
        worker.start()
        self.assertTrue(started.wait(5))
        with mock.patch.object(rnd, "RATING_GRACE_PERIOD", 0):  # bypass the /next rating gate for this test
            self.play(_custom("laksa"))   # the next round begins while that vote is still in flight
        release.set()
        worker.join(5)
        self.backend.rate_tossup = mock.AsyncMock(return_value=(1, 0))
        rnd.submit_rating(1, "good")      # this player's vote on the new question must still count
        self.assertEqual(self.votes_sent(), [("laksa", "good", None)])


class NextGateTest(_RoundCase):
    """/next is refused right after an unrated custom round, until a vote comes in or the grace period passes."""

    def start(self, tossup):
        with mock.patch.object(rnd, "_fetch_tossup", mock.AsyncMock(return_value=tossup)), \
             mock.patch.object(rnd.threading, "Thread"):
            return rnd.start_round(lambda _: None, END_HINT, {})

    def test_next_is_refused_right_after_an_unrated_custom_round(self):
        self.play(_custom("merlion"))
        self.assertEqual(self.start(_tossup(id=None)), rnd.StartResult.NEEDS_RATING)

    def test_a_vote_opens_next_back_up(self):
        self.play(_custom("merlion"))
        rnd.submit_rating(1, "good")
        self.assertEqual(self.start(_tossup(id=None)), rnd.StartResult.STARTED)

    def test_next_opens_up_on_its_own_once_the_grace_period_passes(self):
        self.play(_custom("merlion"))
        later = rnd.time.monotonic() + rnd.RATING_GRACE_PERIOD + 1
        with mock.patch.object(rnd.time, "monotonic", return_value=later):
            self.assertEqual(self.start(_tossup(id=None)), rnd.StartResult.STARTED)

    def test_ordinary_rounds_never_gate_next(self):
        self.play(_tossup(id=None))
        self.assertEqual(self.start(_tossup(id=None)), rnd.StartResult.STARTED)

    def test_a_custom_question_nobody_can_rate_does_not_gate_next(self):
        self.play(_tossup(custom=True, category="Singapore"))  # no id: not ratable, so never gates
        self.assertEqual(self.start(_tossup(id=None)), rnd.StartResult.STARTED)

    def test_a_round_still_in_progress_is_just_busy_not_a_rating_prompt(self):
        with mock.patch.object(rnd, "_fetch_tossup", mock.AsyncMock(return_value=_custom("merlion"))), \
             mock.patch.object(rnd.threading, "Thread"):
            self.assertEqual(rnd.start_round(lambda _: None, END_HINT, {}), rnd.StartResult.STARTED)
        self.assertEqual(self.start(_tossup(id=None)), rnd.StartResult.BUSY)


class NextGateHandlerTest(_RoundCase):
    """The /next handler's reply when NextGateTest's gate blocks it."""

    def test_the_player_who_tried_next_is_told_to_rate_first(self):
        self.play(_custom("merlion"))
        bot = mock.Mock(username="TriviaOracleBot")
        update = SimpleNamespace(
            effective_chat=SimpleNamespace(id=-100),
            message=SimpleNamespace(message_id=42),
        )
        context = SimpleNamespace(bot=bot, chat_data={})
        with mock.patch.object(rnd, "_fetch_tossup", mock.AsyncMock(return_value=_tossup(id=None))), \
             mock.patch.object(rnd.threading, "Thread"):
            round_handlers.start_round(update, context)
        bot.send_message.assert_called_once_with(
            chat_id=-100, text=round_handlers.NEEDS_RATING_TEXT, reply_to_message_id=42,
        )


class RatingHandlerTest(unittest.TestCase):
    def update(self, user_id=7):
        return SimpleNamespace(effective_user=SimpleNamespace(id=user_id, first_name="Ada"))

    def test_good_and_bad_commands_submit_that_players_rating(self):
        with mock.patch.object(round_handlers.game_round, "submit_rating") as submit:
            round_handlers.rate_good(self.update(7), None)
            round_handlers.rate_bad(self.update(8), None)
        self.assertEqual(submit.call_args_list, [mock.call(7, "good"), mock.call(8, "bad")])

    def test_the_commands_are_registered_and_do_not_block_other_updates(self):
        handlers = []
        dp = SimpleNamespace(add_handler=handlers.append, add_error_handler=lambda _: None)
        register_handlers(dp)
        commands = {tuple(h.command): h for h in handlers if hasattr(h, "command")}
        for command in (("good",), ("bad",)):
            self.assertIn(command, commands)
            self.assertTrue(commands[command].run_async)


if __name__ == "__main__":
    unittest.main()
