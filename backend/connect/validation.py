"""
Checks for everything a person types. Each raises django ValidationError with
a message that says what is expected and gives an example, so the person can
fix it without guessing. DRF serializers turn these into field errors.
"""
import re

from django.core.exceptions import ValidationError

from users.phone import KENYA_MOBILE, canonical_phone

PHONE_HELP = (
    'Enter a Kenyan mobile number that can take calls, '
    'e.g. 0712 345 678, 0112 345 678 or +254 712 345 678.'
)

# Unicode letters only (no digits or underscore).
_LETTER = r'[^\W\d_]'
_WORD = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)*")
_PLACE_CHARS = re.compile(r"^[\w\s,.'’()/&#→–-]+$")
_NAME_PART = re.compile(rf"^{_LETTER}+(?:['’-]{_LETTER}+)*$")
_VOWELS = set('aeiouyáàâäéèêëíìîïóòôöúùûü')
# Keyboard runs people mash when they want a form to just go through.
_MASH = (
    'qwer', 'asdf', 'sdfg', 'dfgh', 'fghj', 'ghjk', 'hjkl', 'zxcv', 'xcvb',
    'cvbn', 'vbnm', 'jklm', 'wxyz',
)
_PLACEHOLDERS = {
    'test', 'testing', 'tester', 'asdf', 'qwerty', 'xxx', 'xx', 'abc', 'abcd',
    'none', 'nil', 'null', 'na', 'n/a', 'unknown', 'nowhere', 'anywhere',
    'somewhere', 'lorem', 'ipsum', 'dummy', 'sample', 'hello', 'hi', 'foo',
    'bar', 'blah', 'aaa', 'nothing', 'something', 'whatever', 'idk', 'random',
}


def _text(value, label):
    if value is not None and not isinstance(value, str):
        raise ValidationError(f'Type {label} as words.')
    return value


def _clean(value):
    return ' '.join(str(value or '').split())


def gibberish_word(word):
    """True if a word looks typed at random rather than written."""
    w = word.lower()
    if len(w) < 4:
        return False
    if re.search(r'(.)\1\1', w):                # "aaa", "kkkk"
        return True
    if any(m in w for m in _MASH):
        return True
    if not (set(w) & _VOWELS):
        # Short all-consonant words are real acronyms: CBD, KICC, JKIA, KNH.
        return len(w) >= 5
    run = 0
    for ch in w:
        run = 0 if ch in _VOWELS else run + 1
        if run >= 6:                             # "xkcdvbn"; English tops out at 5 ("strengths")
            return True
    return False


def _check_words(text, label):
    words = _WORD.findall(text)
    for w in words:
        if gibberish_word(w):
            raise ValidationError(
                f'"{w}" in {label} does not look like a real word. '
                'Please write it in plain words.'
            )
    if len(words) >= 3 and len({w.lower() for w in words}) == 1:
        raise ValidationError(f'{label.capitalize()} repeats one word. Please write it properly.')
    return words


def kenyan_mobile(value):
    """Canonical +2547XXXXXXXX / +2541XXXXXXXX, or a ValidationError."""
    raw = _clean(value)
    if not raw:
        raise ValidationError(PHONE_HELP)
    if re.search(r'[^\d\s+()-]', raw):
        raise ValidationError('A phone number has digits only. ' + PHONE_HELP)
    phone = canonical_phone(raw)
    if not KENYA_MOBILE.match(phone or ''):
        raise ValidationError(PHONE_HELP)
    if len(set(phone[-8:])) == 1:               # +254700000000, +254711111111
        raise ValidationError('That number is not a real line. ' + PHONE_HELP)
    return phone


def place(value, label='the place', required=True, max_length=100,
          example='e.g. Westlands, Kencom or Moi Avenue'):
    """A real place name: 'Westlands', 'Kencom, Moi Avenue', '4th Ngong Road'.
    Also used for other short proper names (companies, routes): `example`
    shows the person what fits."""
    text = _clean(_text(value, label))
    if not text:
        if required:
            raise ValidationError(f'Enter {label}, {example}.')
        return ''
    if len(text) > max_length:
        raise ValidationError(f'Keep {label} under {max_length} characters.')
    if not _PLACE_CHARS.match(text) or '_' in text:
        raise ValidationError(
            f'Use letters, numbers, spaces and , . - \' / & ( ) only for {label}, {example}.'
        )
    letters = len(re.findall(_LETTER, text))
    digits = len(re.findall(r'\d', text))
    if letters < 2 or digits > letters:
        raise ValidationError(f'Write {label} in words, {example}.')
    if text.lower() in _PLACEHOLDERS:
        raise ValidationError(f'"{text}" is not a real name. Enter {label}, {example}.')
    _check_words(text, label)
    return text


def person_name(value, label='the name', parts=2, max_length=100):
    """'Collins Otieno'. Letters, apostrophes and hyphens; `parts` names at least."""
    text = _clean(_text(value, label))
    example = 'e.g. Collins Otieno'
    words = text.split(' ') if text else []
    if len(text) > max_length:
        raise ValidationError(f'Keep {label} under {max_length} characters.')
    if len(words) < parts:
        need = 'first and last name' if parts == 2 else 'name'
        raise ValidationError(f'Enter the {need} for {label}, {example}.')
    for w in words:
        if len(w) < 2 or not _NAME_PART.match(w):
            raise ValidationError(
                f'Each name in {label} needs 2 or more letters (no numbers or symbols), {example}.'
            )
    if text.lower() in _PLACEHOLDERS or any(w.lower() in _PLACEHOLDERS for w in words):
        raise ValidationError(f'Enter a real name for {label}, {example}.')
    _check_words(text, label)
    return text


def free_text(value, label='this field', required=True, min_letters=3, max_length=1000):
    """Written sentences: must contain real words, not keyboard mashing."""
    text = str(_text(value, label) or '').strip()
    if not text:
        if required:
            raise ValidationError(f'Please fill in {label}.')
        return ''
    if len(text) > max_length:
        raise ValidationError(f'Keep {label} under {max_length} characters.')
    letters = len(re.findall(_LETTER, text))
    if letters < min_letters:
        raise ValidationError(
            f'Describe {label} in words (at least {min_letters} letters).'
        )
    if text.lower().strip('.!?') in _PLACEHOLDERS:
        raise ValidationError(f'"{text}" does not describe anything. Please fill in {label}.')
    _check_words(text, label)
    return text
