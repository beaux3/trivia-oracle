from .config import CATEGORIES, DIFFICULTIES


class _Settings:
    """
    Mutable runtime state modified by /configure.

    Use attribute access everywhere — never rebind the `settings` name itself.
    In-place set operations (|=, -=, .add, .discard, .clear) work fine on the
    set attributes. Scalar reassignment (sentence_interval = x) also works
    because we're writing to the object, not to a module-level variable.
    """

    def __init__(self):
        self.sentence_interval: float = 5.0
        self.answer_wait: float = 10.0
        self.selected_categories: set = set(CATEGORIES)
        self.selected_difficulties: set = {"HS Easy (2)", "HS Regular (3)"}
        self.scoring_modes: set = set()  # enabled keys of config.SCORING_MODES; empty = default


settings = _Settings()
