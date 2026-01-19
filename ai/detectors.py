"""
ai/detectors.py - Query Pattern Detection Functions

This module contains all the helper functions for detecting patterns
in natural language queries. It handles detection of:
- Sorting preferences (longest, shortest, newest, alphabetical)
- Profile picture filters (with/without profile pic)
- Name length parity (odd/even number of letters)
- Gender filters (male, female, other)
- Name search patterns (starts with, contains, named, etc.)
- Unsupported patterns (for user warnings)

These functions are used by the simple parser to avoid AI API calls
for common query patterns.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ==============================================================================
# CONSTANTS
# ==============================================================================

# String literals used multiple times
SORT_SHORTEST = 'shortest'
SORT_LONGEST = 'longest'
SORT_NEWEST = 'newest'
PATTERN_STARTS_WITH = 'starts with'

# Sorting keyword sets
_LONGEST_WORDS = frozenset({SORT_LONGEST, 'long', 'biggest', 'big', 'most characters'})
_SHORTEST_WORDS = frozenset({SORT_SHORTEST, 'short', 'smallest', 'small', 'fewest', 'least'})
_NEWEST_WORDS = frozenset({SORT_NEWEST, 'most recent', 'recently created', 'latest', 'recent'})
_OLDEST_WORDS = frozenset({'oldest', 'first created', 'earliest'})
_ALPHA_ASC_WORDS = frozenset({'alphabetical', 'a-z', 'a to z'})
_ALPHA_DESC_WORDS = frozenset({'reverse alphabetical', 'z-a', 'z to a'})

# Gender detection constants
_FEMALE_WORDS = frozenset({'female', 'woman', 'women', 'lady', 'ladies'})
_MALE_WORDS = frozenset({'male', 'guy', 'guys', 'man', 'men'})
_FEMALE_TYPOS = frozenset({'fmale', 'femal', 'femails', 'femail'})
_NAME_PREFIXES = frozenset({'named', 'called', 'name'})

# Name search pattern constants
_STARTS_WITH_PATTERNS = frozenset([
    PATTERN_STARTS_WITH, 'starting with', 'begins with', 'beginning with',
    'begin with', 'start with', 'start at', 'starting letter'
])
_FILTER_WORDS = frozenset({
    'female', 'male', 'other', 'newest', 'oldest', 'latest', 'recent',
    SORT_LONGEST, SORT_SHORTEST, 'with', 'without', 'no', 'user', 'users'
})
_COMMAND_WORDS = frozenset({
    'find', 'show', 'list', 'get', 'search', 'display', 'give', 'fetch',
    'all', 'the', 'users', 'user', 'people', 'person', 'names', 'name'
})
_ARTICLES = frozenset({'a', 'an', 'the', 'that', 'is'})
_SORTING_WORDS = frozenset({'oldest', SORT_NEWEST, SORT_LONGEST, SORT_SHORTEST, 'with', 'without'})

# ==============================================================================
# UNSUPPORTED PATTERN DETECTION
# ==============================================================================


def detect_unsupported_patterns(query_lower: str) -> list:
    """
    Detect unsupported query patterns and return warnings.

    Args:
        query_lower: Lowercase query string

    Returns:
        list: Warning messages for unsupported patterns
    """
    warnings = []
    words = set(query_lower.split())

    # Negation/exclusion (but not "no profile pic" which is supported)
    has_negation = bool(words & {'except', 'exclude'})
    has_not_without_profile = 'not' in words and 'profile' not in query_lower
    if has_negation or has_not_without_profile:
        warnings.append("Negation/exclusion queries are not supported - showing matching results instead")

    # OR logic between genders
    if 'or' in words and bool(words & {'male', 'female', 'other'}):
        warnings.append("OR logic between genders is not supported - using first gender found")

    # Ends-with filtering
    if 'ends with' in query_lower or 'end with' in query_lower:
        warnings.append(f"Ends-with filtering is not supported - use 'contains' or '{PATTERN_STARTS_WITH}' instead")

    # Exact length filtering
    if 'exactly' in words and bool(words & {'letter', 'char', 'character'}):
        warnings.append("Exact length filtering is not supported - only odd/even length is available")

    for warning in warnings:
        logger.warning("Unsupported query pattern: %s", warning)

    return warnings


# ==============================================================================
# SORTING DETECTION
# ==============================================================================


def _detect_length_sorting(query_lower: str, words: list, has_username: bool, has_name: bool) -> Optional[tuple]:
    """Detect length-based sorting (longest/shortest)."""
    has_longest = any(word in query_lower for word in _LONGEST_WORDS)
    has_shortest = any(word in query_lower for word in _SHORTEST_WORDS)

    if has_longest:
        field = "username_length" if has_username else "name_length"
        if has_username or has_name or 'first' in words:
            return field, "desc"

    if has_shortest:
        field = "username_length" if has_username else "name_length"
        if has_username or has_name or 'first' in words:
            return field, "asc"

    return None


def _detect_date_sorting(query_lower: str) -> Optional[tuple]:
    """Detect date-based sorting (newest/oldest)."""
    if any(word in query_lower for word in _NEWEST_WORDS) or 'signups' in query_lower:
        return "created_at", "desc"
    if any(word in query_lower for word in _OLDEST_WORDS):
        return "created_at", "asc"
    return None


def _detect_alpha_sorting(query_lower: str, has_username: bool, has_name: bool) -> Optional[tuple]:
    """Detect alphabetical sorting (a-z / z-a)."""
    if any(word in query_lower for word in _ALPHA_DESC_WORDS):
        return ("username", "desc") if has_username else ("name", "desc")

    if any(word in query_lower for word in _ALPHA_ASC_WORDS):
        if has_username:
            return "username", "asc"
        # Default to name sorting for "alphabetical order" without specific field
        return "name", "asc"

    return None


def _detect_explicit_sort(words: list) -> Optional[tuple]:
    """Detect explicit 'sort by X' / 'order by X' / 'sorted by X' pattern."""
    has_sort_word = 'sort' in words or 'sorted' in words or 'order' in words or 'ordered' in words
    if not (has_sort_word and 'by' in words):
        return None

    by_idx = words.index('by')
    if by_idx + 1 >= len(words):
        return None

    sort_field = words[by_idx + 1]
    field_map = {
        'username': ("username", "asc"),
        'usernames': ("username", "asc"),
        'name': ("name", "asc"),
        'names': ("name", "asc"),
        'date': ("created_at", "desc"),
        'created': ("created_at", "desc"),
        'time': ("created_at", "desc"),
    }
    return field_map.get(sort_field)


def detect_sorting(query_lower: str) -> tuple:
    """
    Detect sorting preferences from query.

    Args:
        query_lower: Lowercase query string

    Returns:
        tuple: (sort_by, sort_order) where sort_by can be None
    """
    words = query_lower.split()
    has_username = 'username' in query_lower or 'usernames' in query_lower
    has_name = 'name' in query_lower or 'names' in query_lower

    # Try each sorting type in priority order
    result = _detect_length_sorting(query_lower, words, has_username, has_name)
    if result:
        return result

    result = _detect_date_sorting(query_lower)
    if result:
        return result

    result = _detect_alpha_sorting(query_lower, has_username, has_name)
    if result:
        return result

    result = _detect_explicit_sort(words)
    if result:
        return result

    return None, "desc"


# ==============================================================================
# PROFILE PICTURE DETECTION
# ==============================================================================


def detect_profile_pic_filter(query_lower: str) -> Optional[bool]:
    """
    Detect profile picture filter from query.

    Handles various ways users express whether they want users with
    or without profile pictures.

    Returns:
        True: User wants results WITH profile pictures
        False: User wants results WITHOUT profile pictures
        None: No profile picture filter detected
    """
    image_words = ['pic', 'picture', 'photo', 'image', 'avatar']
    has_image_word = any(word in query_lower for word in image_words)

    if not has_image_word and 'profile' not in query_lower:
        return None

    # Check for "WITHOUT" indicators FIRST (negation takes priority)
    without_indicators = [
        'without pic', 'without pics', 'without photo', 'without photos',
        'without profile', 'without avatar', 'without avatars',
        'without picture', 'without pictures',
        'no pic', 'no pics', 'no photo', 'no photos',
        'no profile', 'no avatar', 'no avatars',
        'no picture', 'no pictures',
        'missing pic', 'missing pics', 'missing photo', 'missing photos',
        'missing profile', 'missing avatar', 'missing picture',
        "don't have pic", "don't have picture", "don't have photo",
        "doesn't have pic", "doesn't have picture", "doesn't have photo",
        "w/o pic", "w/o photo", "w/o profile", "w/o avatar",
    ]
    if any(indicator in query_lower for indicator in without_indicators):
        return False

    # Check for "HAS/WITH" indicators
    has_indicators = [
        'with pic', 'with photo', 'with profile', 'with avatar',
        'with picture', 'with pics', 'with photos', 'with avatars',
        'has pic', 'has photo', 'has avatar', 'has picture',
        'have pic', 'have photo', 'have avatar', 'have picture',
        'got pic', 'got photo', 'got avatar', 'got picture',
        'profile pic', 'profile picture', 'profile photo'
    ]
    if any(indicator in query_lower for indicator in has_indicators):
        return True

    return None


# ==============================================================================
# NAME LENGTH PARITY DETECTION
# ==============================================================================


def detect_name_length_parity(query_lower: str) -> Optional[str]:
    """
    Detect odd/even name length filter from query.

    Args:
        query_lower: Lowercase query string

    Returns:
        "odd", "even", or None
    """
    length_words = ['letter', 'character', 'length']
    has_length_word = any(word in query_lower for word in length_words)

    if 'odd' in query_lower and (has_length_word or 'name' in query_lower):
        return "odd"

    if 'even' in query_lower and (has_length_word or 'name' in query_lower):
        return "even"

    return None


# ==============================================================================
# GENDER DETECTION
# ==============================================================================


def _is_name_not_gender(gender_word: str, words: list) -> bool:
    """Check if a gender word is actually a name (preceded by 'named', etc.)."""
    if gender_word not in words:
        return False
    idx = words.index(gender_word)
    return idx > 0 and words[idx - 1] in _NAME_PREFIXES


def _detect_other_gender(query_lower: str, words: list) -> Optional[tuple]:
    """Detect 'Other' gender (non-binary, other gender, etc.)."""
    if 'other gender' in query_lower or 'other-gender' in query_lower:
        return "Other", None
    if 'non-binary' in query_lower or 'non binary' in query_lower or 'nonbinary' in query_lower:
        return "Other", None
    if 'nb' in words:
        return "Other", "Interpreted as 'non-binary'"
    return None


def _detect_female_gender(query_lower: str, words: list) -> Optional[tuple]:
    """Detect female gender from query."""
    if _is_name_not_gender('female', words):
        return None

    if any(word in words for word in _FEMALE_WORDS) or 'female' in query_lower:
        return "Female", None

    if any(typo in query_lower for typo in _FEMALE_TYPOS) and 'male' not in words:
        return "Female", "Interpreted as 'female' (possible typo corrected)"

    return None


def _detect_male_gender(words: list) -> Optional[tuple]:
    """Detect male gender from query."""
    if _is_name_not_gender('male', words):
        return None
    if any(word in words for word in _MALE_WORDS):
        return "Male", None
    return None


def detect_gender(query_lower: str) -> tuple:
    """
    Detect gender filter from query.

    Args:
        query_lower: Lowercase query string

    Returns:
        tuple: (gender, warning) where gender is "Male", "Female", "Other", or None
    """
    words = query_lower.split()

    # Check Other gender first
    result = _detect_other_gender(query_lower, words)
    if result:
        return result

    # Check Female before Male (female contains "male" as substring)
    result = _detect_female_gender(query_lower, words)
    if result:
        return result

    # Check Male
    result = _detect_male_gender(words)
    if result:
        return result

    # Fallback: "other" with context
    if not _is_name_not_gender('other', words):
        if 'other' in words and ('gender' in query_lower or 'user' in query_lower):
            return "Other", None

    return None, None


# ==============================================================================
# NAME SEARCH DETECTION - HELPER FUNCTIONS
# ==============================================================================


def _extract_word_after(query_lower: str, keywords: list, excluded_words: set) -> Optional[str]:
    """Extract the word following any of the keywords, excluding certain words."""
    words = query_lower.split()
    for i, word in enumerate(words):
        if word in keywords and i + 1 < len(words):
            next_word = words[i + 1]
            if next_word in excluded_words:
                continue
            if next_word and next_word[0].isalpha():
                return next_word
    return None


def _capitalize_name(name: str) -> str:
    """Capitalize name parts (handles apostrophes like O'Brien)."""
    parts = name.split("'")
    return "'".join(part.capitalize() for part in parts)


def _find_letter_after_with(words: list) -> Optional[str]:
    """Find a single letter following 'with' in a word list."""
    articles = {'a', 'an', 'the', 'letter'}
    for i, word in enumerate(words):
        if word != 'with' or i + 1 >= len(words):
            continue
        next_word = words[i + 1]
        if next_word in articles and i + 2 < len(words):
            next_word = words[i + 2]
        if len(next_word) == 1 and next_word.isalpha():
            return next_word.upper()
    return None


def _find_letter_after_pattern(words: list, pattern_words: list) -> Optional[str]:
    """Find a single letter that appears after a pattern in words."""
    for i, word in enumerate(words):
        if word != pattern_words[0]:
            continue
        next_idx = i + len(pattern_words)
        if next_idx < len(words):
            next_word = words[next_idx]
            if len(next_word) == 1 and next_word.isalpha():
                return next_word.upper()
    return None


# ==============================================================================
# NAME SEARCH DETECTION - PATTERN MATCHERS
# ==============================================================================


def _detect_show_x_names(words: list) -> Optional[tuple]:
    """Pattern 1: 'show X names' - single letter before 'names'."""
    if 'names' not in words or len(words) < 2:
        return None
    names_idx = words.index('names')
    if names_idx >= 1:
        prev_word = words[names_idx - 1]
        if len(prev_word) == 1 and prev_word.isalpha():
            return prev_word.upper(), True
    return None


def _detect_starts_with_pattern(query_lower: str, words: list) -> Optional[tuple]:
    """Pattern 2: 'starts with X' variants."""
    for pattern in _STARTS_WITH_PATTERNS:
        if pattern not in query_lower:
            continue
        letter = _find_letter_after_with(words)
        if letter:
            return letter, True
        result = _find_letter_after_pattern(words, pattern.split())
        if result:
            return result, True
    return None


def _detect_letter_in_name(words: list) -> Optional[tuple]:
    """Pattern 3: 'letter X in name'."""
    if 'letter' not in words:
        return None
    letter_idx = words.index('letter')
    if letter_idx + 1 >= len(words):
        return None
    next_word = words[letter_idx + 1]
    if len(next_word) == 1 and next_word.isalpha():
        if 'name' in words[letter_idx:] or 'names' in words[letter_idx:]:
            return next_word.upper(), False
    return None


def _detect_containing_pattern(words: list) -> Optional[tuple]:
    """Pattern 4: 'containing X'."""
    if 'containing' not in words:
        return None
    idx = words.index('containing')
    if idx + 1 >= len(words):
        return None
    next_word = words[idx + 1]
    if len(next_word) == 1 and next_word.isalpha():
        return next_word.upper(), False
    if next_word not in _ARTICLES:
        return _capitalize_name(next_word), False
    return None


def _detect_name_like_pattern(words: list) -> Optional[tuple]:
    """Pattern 5: 'name like X'."""
    if 'like' not in words:
        return None
    idx = words.index('like')
    if idx > 0 and 'name' in words[:idx] and idx + 1 < len(words):
        next_word = words[idx + 1]
        if next_word not in _ARTICLES:
            return _capitalize_name(next_word), False
    return None


def _detect_named_called_pattern(query_lower: str) -> Optional[tuple]:
    """Pattern 6: 'named X' / 'called X'."""
    excluded = {
        'that', 'is', 'of', 'which', 'who', 'a', 'an', 'the',
        'users', 'user', 'people', 'all', 'me'
    }
    name = _extract_word_after(query_lower, ['named', 'called'], excluded)
    if name and name.lower() not in _SORTING_WORDS:
        return _capitalize_name(name), False
    return None


def _detect_show_name_filter(words: list) -> Optional[tuple]:
    """Pattern 7: 'show/find X <filter>'."""
    if len(words) < 3 or words[0] not in {'show', 'find'}:
        return None
    potential_name = words[1]
    if potential_name not in _FILTER_WORDS and potential_name[0].isalpha():
        if words[2] in _FILTER_WORDS:
            return _capitalize_name(potential_name), False
    return None


def _detect_name_users_pattern(words: list) -> Optional[tuple]:
    """Pattern 8: 'X users'."""
    if len(words) < 2 or words[-1] not in {'users', 'user'}:
        return None
    potential_name = words[0]
    cmd_words = {
        'find', 'show', 'list', 'get', 'search', 'display', 'give', 'fetch',
        'all', 'the', 'female', 'male', 'other', SORT_NEWEST, 'oldest',
        # Include common typos
        'fmale', 'femal', 'femails', 'femail',
    }
    excluded = {
        SORT_NEWEST, 'oldest', 'female', 'male', 'other',
        'fmale', 'femal', 'femails', 'femail',  # typos
    }
    if potential_name not in cmd_words and potential_name[0].isalpha():
        if potential_name not in excluded:
            return _capitalize_name(potential_name), False
    return None


def _detect_name_filter_pattern(words: list, gender: Optional[str]) -> Optional[tuple]:
    """Pattern 9: Name at start followed by filter."""
    if len(words) < 2:
        return None
    first_word = words[0]
    filter_words = {
        'female', 'male', 'other', SORT_NEWEST, 'oldest', 'latest', 'recent',
        SORT_LONGEST, SORT_SHORTEST, 'with', 'without', 'no'
    }
    # Don't treat gender/filter words themselves as names
    excluded_first_words = {
        'female', 'male', 'other', 'fmale', 'femal',  # gender words/typos
        SORT_NEWEST, 'oldest', 'latest', 'recent',  # date sorting
        SORT_LONGEST, SORT_SHORTEST, 'alphabetical', 'sorted',  # sorting
    }
    if first_word in excluded_first_words:
        return None
    if first_word not in _COMMAND_WORDS and first_word[0].isalpha():
        if words[1] in filter_words or gender is not None:
            return _capitalize_name(first_word), False
    return None


def _detect_with_name_pattern(query_lower: str, gender: Optional[str], has_profile_pic: Optional[bool]) -> Optional[tuple]:
    """Pattern 10: 'with X' for name (when gender set, no pic filter)."""
    if not gender or has_profile_pic is not None:
        return None
    excluded_with = {
        'a', 'an', 'the', 'that', 'is', 'of', 'odd', 'even',
        'profile', 'pic', 'picture', 'photo', 'avatar'
    }
    name = _extract_word_after(query_lower, ['with'], excluded_with)
    if name:
        return _capitalize_name(name), False
    return None


def detect_name_search(query_lower: str, gender: Optional[str], has_profile_pic: Optional[bool]) -> tuple:
    """
    Detect name search patterns from query.

    Tries multiple patterns in priority order to extract name search terms.

    Args:
        query_lower: Lowercase query string
        gender: Detected gender filter (for context)
        has_profile_pic: Detected profile pic filter (for context)

    Returns:
        tuple: (name_substr, starts_with_mode)
    """
    words = query_lower.split()

    patterns = [
        lambda: _detect_show_x_names(words),
        lambda: _detect_starts_with_pattern(query_lower, words),
        lambda: _detect_letter_in_name(words),
        lambda: _detect_containing_pattern(words),
        lambda: _detect_name_like_pattern(words),
        lambda: _detect_named_called_pattern(query_lower),
        lambda: _detect_show_name_filter(words),
        lambda: _detect_name_users_pattern(words),
        lambda: _detect_name_filter_pattern(words, gender),
        lambda: _detect_with_name_pattern(query_lower, gender, has_profile_pic),
    ]

    for pattern_func in patterns:
        result = pattern_func()
        if result:
            return result

    return None, False


# ==============================================================================
# BARE NAME DETECTION
# ==============================================================================


def _is_valid_name_chars(text: str) -> bool:
    """Check if text contains only valid name characters."""
    if not text or not text[0].isalpha():
        return False
    for char in text:
        if not (char.isalpha() or char in "' -"):
            return False
    return True


def detect_bare_name(query_lower: str, query_original: str) -> Optional[str]:
    """
    Detect if query is just a bare name without any command words.

    Handles cases where users simply type a name they're looking for,
    without using command words like "find", "show", etc.

    Args:
        query_lower: Lowercase query string
        query_original: Original query with preserved case

    Returns:
        The name string formatted in Title Case, or None
    """
    query_indicators = {
        'find', 'show', 'list', 'get', 'search', 'display', 'give', 'fetch',
        'user', 'users', 'people', 'person', 'all', 'every',
        'with', 'without', 'who', 'whose', 'where', 'that', 'which',
        'the', 'and', 'or', 'not',
        'longest', 'shortest', 'oldest', 'newest', 'first', 'last',
        'name', 'named', 'called', 'username', 'picture', 'photo', 'profile',
        # Sorting words
        'alphabetical', 'alphabetically', 'sorted', 'sort', 'order', 'ordered',
        'a-z', 'z-a', 'ascending', 'descending',
        # Gender words
        'female', 'male', 'other', 'non-binary', 'nonbinary',
    }

    words = query_lower.split()

    # Special case: Single letter query
    if len(query_original) == 1 and query_original.isalpha():
        letter = query_original.upper()
        logger.info(f"Simple parse (single letter): '{letter}'")
        return letter

    if any(word in query_indicators for word in words):
        return None

    # Validation
    if not (1 <= len(words) <= 4):
        return None
    if not (2 <= len(query_original) <= 40):
        return None
    if not _is_valid_name_chars(query_original):
        return None

    name = query_original.title()
    logger.info(f"Simple parse (bare name): '{name}'")
    return name


# ==============================================================================
# COMPLEX QUERY DETECTION
# ==============================================================================


def is_complex_query(query_lower: str) -> bool:
    """
    Check if query contains complex words that require AI parsing.

    Args:
        query_lower: Lowercase query string

    Returns:
        bool: True if query needs AI parsing
    """
    complex_words = [
        'whose', 'rhyme', 'longer', 'shorter', 'exactly', 'more', 'less',
        'three', 'two', 'contains', 'ends', 'birthdate',
        'birthday', 'age', 'registered', 'password'
    ]
    return any(word in query_lower for word in complex_words)
