import pytest

import qbreader._api_utils as api_utils
from qbreader.types import AlternateSubcategory, Category, Difficulty, Subcategory
from tests import assert_exception, assert_warning


class TestNormalization:
    """Test normalization functions."""

    @pytest.mark.parametrize(
        "unnormalized, enum_type, expected",
        [
            (None, Category, ""),
            (Difficulty.OPEN, Difficulty, "10"),
            ("Long Fiction", AlternateSubcategory, "Long Fiction"),
            ("0", Difficulty, "0"),
            (1, Difficulty, "1"),
            ([Category.FINE_ARTS, Category.RELIGION], Category, "Religion,Fine Arts"),
            (
                ["Religion", "Pop Culture", "Mythology"],
                Category,
                "Mythology,Pop Culture,Religion",
            ),
            (["0", "1", "2"], Difficulty, "2,1,0"),
            ([0, 1, 2], Difficulty, "1,2,0"),
            (["History", "History"], Category, "History"),
            ("Science", Subcategory, "Science"),
        ],
    )
    def test_normalize_enumlike(self, unnormalized, enum_type, expected):
        result = api_utils.normalize_enumlike(unnormalized, enum_type)
        sorted_result = sorted(result.split(","))
        sorted_expected = sorted(expected.split(","))
        assert sorted_result == sorted_expected

    @pytest.mark.parametrize(
        "unnormalized, enum_type, exception",
        [
            (True, Category, TypeError),
            (3.5, Category, TypeError),
            (["Social Science", 3.5], Category, TypeError),
        ],
    )
    def test_normalize_enumlike_exception(self, unnormalized, enum_type, exception):
        assert_exception(
            api_utils.normalize_enumlike, exception, unnormalized, enum_type
        )

    @pytest.mark.parametrize(
        "unnormalized, enum_type, expected, warning",
        [
            (11, Difficulty, "", UserWarning),
            ("0.5", Difficulty, "", UserWarning),
            ("History", AlternateSubcategory, "", UserWarning),
            (AlternateSubcategory.JAZZ, Category, "", UserWarning),
            (
                [Category.SCIENCE, Category.FINE_ARTS, Subcategory.MUSIC],
                Category,
                "Science,Fine Arts",
                UserWarning,
            ),
            ([Difficulty.OPEN, 999], Difficulty, "10", UserWarning),
        ],
    )
    def test_normalize_enumlike_warning(
        self, unnormalized, enum_type, expected, warning
    ):
        result = assert_warning(
            api_utils.normalize_enumlike, warning, unnormalized, enum_type
        )
        sorted_result = sorted(result.split(","))
        sorted_expected = sorted(expected.split(","))
        assert sorted_result == sorted_expected

    @pytest.mark.parametrize(
        "boolean, expected",
        [
            (True, "true"),
            (False, "false"),
            ("true", "true"),
            ("false", "false"),
        ],
    )
    def test_normalize_bool(self, boolean, expected):
        assert api_utils.normalize_bool(boolean) == expected

    @pytest.mark.parametrize(
        "boolean, exception", [(None, TypeError), (1, TypeError), ("1", ValueError)]
    )
    def test_normalize_bool_exception(self, boolean, exception):
        assert_exception(api_utils.normalize_bool, exception, boolean)

    @pytest.mark.parametrize(
        "diff, expected",
        [
            (Difficulty.HS_REGS, "3"),
            (10, "10"),
            ("2", "2"),
            ([Difficulty.HS_REGS], "3"),
            ([Difficulty.HS_REGS, Difficulty.HS_HARD], "3,4"),
            ([Difficulty.HS_REGS, "3", "4"], "3,4"),
            (["3", "4"], "3,4"),
            (["1", "4", 7], "1,4,7"),
            (["3", "2", 5, Difficulty.HS_HARD], "2,3,4,5"),
            (list(range(11)), "0,1,2,3,4,5,6,7,8,9,10"),
            (None, ""),
            ([], ""),
        ],
    )
    def test_normalize_diff(self, diff, expected):
        assert set(api_utils.normalize_diff(diff).split(",")) == set(
            expected.split(",")
        )  # contains the same elements

    @pytest.mark.parametrize(
        "diff, exception",
        [
            (3.14, TypeError),
            (3 + 4j, TypeError),
            (True, TypeError),
            ([3.14], TypeError),
        ],
    )
    def test_normalize_diff_exception(self, diff, exception):
        assert_exception(api_utils.normalize_diff, exception, diff)

    @pytest.mark.parametrize(
        "diff, warning",
        [
            ("3.14", UserWarning),
            ("11", UserWarning),
            (["-1"], UserWarning),
            (1000, UserWarning),
        ],
    )
    def test_normalize_diff_warning(self, diff, warning):
        assert assert_warning(api_utils.normalize_diff, warning, diff) == ""

    @pytest.mark.parametrize(
        "cat, expected",
        [
            (Category.SCIENCE, "Science"),
            (Category.SCIENCE.value, "Science"),
            ("Science", "Science"),
            (["Science"], "Science"),
            ([Category.SCIENCE], "Science"),
            ([Category.SCIENCE, Category.LITERATURE], "Science,Literature"),
            ([Category.SCIENCE, "Literature"], "Science,Literature"),
            (["Science", "Literature"], "Science,Literature"),
            (["Science", "Literature", "Literature"], "Science,Literature"),
            (
                [
                    "Science",
                    "Literature",
                    "Literature",
                    Category.SCIENCE,
                    Category.HISTORY,
                ],
                "Science,Literature,History",
            ),
        ],
    )
    def test_normalize_cat(self, cat, expected):
        assert set(api_utils.normalize_cat(cat).split(",")) == set(expected.split(","))

    @pytest.mark.parametrize(
        "cat, exception",
        [
            (3.14, TypeError),
            (3 + 4j, TypeError),
            (True, TypeError),
            ([3.14], TypeError),
        ],
    )
    def test_normalize_cat_exception(self, cat, exception):
        assert_exception(api_utils.normalize_cat, exception, cat)

    @pytest.mark.parametrize(
        "cat, warning",
        [
            ("3.14", UserWarning),
            ("11", UserWarning),
            (["-1"], UserWarning),
            (1000, UserWarning),
        ],
    )
    def test_normalize_cat_warning(self, cat, warning):
        assert assert_warning(api_utils.normalize_cat, warning, cat) == ""

    @pytest.mark.parametrize(
        "subcat, expected",
        [  # reused because subcat is a superset of cat
            (Subcategory.SCIENCE, "Science"),
            (Subcategory.SCIENCE.value, "Science"),
            ("Science", "Science"),
            (["Science"], "Science"),
            ([Subcategory.SCIENCE], "Science"),
            ([Subcategory.SCIENCE, Subcategory.LITERATURE], "Science,Literature"),
            ([Subcategory.SCIENCE, "Literature"], "Science,Literature"),
            (["Science", "Literature"], "Science,Literature"),
            (["Science", "Literature", "Literature"], "Science,Literature"),
            (
                [
                    "Science",
                    "Literature",
                    "Literature",
                    Subcategory.SCIENCE,
                    Subcategory.HISTORY,
                ],
                "Science,Literature,History",
            ),
        ],
    )
    def test_normalize_subcat(self, subcat, expected):
        assert set(api_utils.normalize_subcat(subcat).split(",")) == set(
            expected.split(",")
        )

    @pytest.mark.parametrize(
        "subcat, exception",
        [
            (3.14, TypeError),
            (3 + 4j, TypeError),
            (True, TypeError),
            ([3.14], TypeError),
        ],
    )
    def test_normalize_subcat_exception(self, subcat, exception):
        assert_exception(api_utils.normalize_subcat, exception, subcat)

    @pytest.mark.parametrize(
        "subcat, warning",
        [
            ("3.14", UserWarning),
            ("11", UserWarning),
            (["-1"], UserWarning),
            (1000, UserWarning),
        ],
    )
    def test_normalize_subcat_warning(self, subcat, warning):
        assert assert_warning(api_utils.normalize_cat, warning, subcat) == ""

    @pytest.mark.parametrize(
        "cats, subcats, alt_subcats, expected",
        [
            (None, None, None, ("", "", "")),
            ([], [], [], ("", "", "")),
            (None, None, "Beliefs", ("", "", "Beliefs")),
            (None, None, "Drama", ("Literature", "", "Drama")),
            (None, None, "Jazz", ("", "Other Fine Arts", "Jazz")),
            ("History", None, None, ("History", "", "")),
            (["History", "Literature"], None, None, ("History,Literature", "", "")),
            (None, "Other Science", None, ("", "Other Science", "")),
            (None, ["Other Science", "Sports"], None, ("", "Other Science,Sports", "")),
            (
                None,
                None,
                ["Astronomy", "Earth Science"],
                ("", "Other Science", "Astronomy,Earth Science"),
            ),
            (
                ["Social Science"],
                ["Television"],
                ["Beliefs", "Drama", "Misc Science"],
                (
                    "Social Science,Literature",
                    "Television,Other Science",
                    "Beliefs,Drama,Misc Science",
                ),
            ),
            (["History", "History", "History", "History"], [], [], ("History", "", "")),
        ],
    )
    def test_normalize_cats(self, cats, subcats, alt_subcats, expected):
        result = api_utils.normalize_cats(cats, subcats, alt_subcats)
        sorted_result = [sorted(x.split(",")) for x in result]
        sorted_expected = [sorted(x.split(",")) for x in expected]
        assert sorted_result == sorted_expected

    @pytest.mark.parametrize(
        "cats, subcats, alt_subcats, exception",
        [
            (None, None, "", ValueError),
            ("Science ", None, [], ValueError),
            ("Geography", [None], [], ValueError),
            (["History", ""], [], [], ValueError),
        ],
    )
    def test_normalize_cats_exception(self, cats, subcats, alt_subcats, exception):
        assert_exception(
            api_utils.normalize_cats, exception, cats, subcats, alt_subcats
        )


class TestMiscUtil:
    """Test miscellaneous util functions"""

    @pytest.mark.parametrize(
        "dictionary, expected",
        [
            ({"a": 1, "b": 2, "c": 3}, {"a": 1, "b": 2, "c": 3}),
            ({"a": 1, "b": None, "c": 3}, {"a": 1, "c": 3}),
            ({"a": 1, "b": None, None: ""}, {"a": 1}),
            (
                {"a": 1, "b": None, None: None, "c": True, "d": False},
                {"a": 1, "c": True, "d": False},
            ),
        ],
    )
    def test_prune_none(self, dictionary, expected):
        assert api_utils.prune_none(dictionary) == expected

    @pytest.mark.parametrize(
        "typed_alt_subcat, expected",
        [
            (AlternateSubcategory.ASTRONOMY, (None, Subcategory.OTHER_SCIENCE)),
            (AlternateSubcategory.ARCHITECTURE, (None, Subcategory.OTHER_FINE_ARTS)),
            (AlternateSubcategory.ANTHROPOLOGY, (None, Subcategory.SOCIAL_SCIENCE)),
            (AlternateSubcategory.DRAMA, (Category.LITERATURE, None)),
            (AlternateSubcategory.BELIEFS, (None, None)),
            (AlternateSubcategory.PRACTICES, (None, None)),
            (AlternateSubcategory.MISC_ARTS, (None, Subcategory.OTHER_FINE_ARTS)),
            (AlternateSubcategory.MISC_LITERATURE, (Category.LITERATURE, None)),
            (AlternateSubcategory.MISC_SCIENCE, (None, Subcategory.OTHER_SCIENCE)),
        ],
    )
    def test_category_correspondence(self, typed_alt_subcat, expected):
        assert api_utils.category_correspondence(typed_alt_subcat) == expected

    @pytest.mark.parametrize(
        "typed_alt_subcat, exception",
        [
            ("hey this isn't an alternate subca", ValueError),
            (15, ValueError),
            ([AlternateSubcategory.ASTRONOMY], ValueError),
            ({AlternateSubcategory.MATH, AlternateSubcategory.FILM}, ValueError),
            ((AlternateSubcategory.DRAMA, AlternateSubcategory.JAZZ), ValueError),
        ],
    )
    def test_category_correspondence_exception(self, typed_alt_subcat, exception):
        assert_exception(api_utils.category_correspondence, exception, typed_alt_subcat)
