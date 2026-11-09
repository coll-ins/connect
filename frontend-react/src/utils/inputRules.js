// Same rules as backend connect/validation.py, so a form can say what is
// wrong while the person types. The server still checks everything.
// Each check returns '' when the value is fine, else a plain message.

export const PHONE_HINT = 'Kenyan mobile that can take calls: 07XX XXX XXX, 01XX XXX XXX or +254 7XX XXX XXX.';
export const NAME_HINT = 'First and last name, letters only, e.g. Collins Otieno.';

const LETTER = /\p{L}/gu;
const WORD = /\p{L}+(?:['’]\p{L}+)*/gu;
const NAME_PART = /^\p{L}+(?:['’-]\p{L}+)*$/u;
const PLACE_CHARS = /^[\p{L}\p{N}\s,.'’()/&#→–-]+$/u;
const VOWELS = new Set('aeiouyáàâäéèêëíìîïóòôöúùûü');
const MASH = ['qwer', 'asdf', 'sdfg', 'dfgh', 'fghj', 'ghjk', 'hjkl', 'zxcv', 'xcvb', 'cvbn', 'vbnm', 'jklm', 'wxyz'];
const PLACEHOLDERS = new Set([
  'test', 'testing', 'tester', 'asdf', 'qwerty', 'xxx', 'xx', 'abc', 'abcd', 'none', 'nil', 'null',
  'na', 'n/a', 'unknown', 'nowhere', 'anywhere', 'somewhere', 'lorem', 'ipsum', 'dummy', 'sample',
  'hello', 'hi', 'foo', 'bar', 'blah', 'aaa', 'nothing', 'something', 'whatever', 'idk', 'random',
]);

const clean = (v) => String(v ?? '').trim().split(/\s+/).filter(Boolean).join(' ');
const count = (re, s) => (s.match(re) || []).length;

export function gibberishWord(word) {
  const w = word.toLowerCase();
  if (w.length < 4) return false;
  if (/(.)\1\1/u.test(w)) return true;
  if (MASH.some((m) => w.includes(m))) return true;
  if (![...w].some((c) => VOWELS.has(c))) return w.length >= 5;
  let run = 0;
  for (const c of w) {
    run = VOWELS.has(c) ? 0 : run + 1;
    if (run >= 6) return true;
  }
  return false;
}

function wordsProblem(text, label) {
  const words = text.match(WORD) || [];
  const bad = words.find(gibberishWord);
  if (bad) return `"${bad}" in ${label} does not look like a real word. Please write it in plain words.`;
  if (words.length >= 3 && new Set(words.map((w) => w.toLowerCase())).size === 1) {
    return `${label[0].toUpperCase()}${label.slice(1)} repeats one word. Please write it properly.`;
  }
  return '';
}

export function checkPhone(value, { required = true } = {}) {
  const raw = clean(value);
  if (!raw) return required ? PHONE_HINT : '';
  if (/[^\d\s+()-]/.test(raw)) return `A phone number has digits only. ${PHONE_HINT}`;
  let d = raw.replace(/\D/g, '');
  if (d.startsWith('2540')) d = `254${d.slice(4)}`;
  const canon = d.startsWith('254') ? `+${d}` : d.startsWith('0') ? `+254${d.slice(1)}` : `+254${d}`;
  if (!/^\+254[17]\d{8}$/.test(canon)) return PHONE_HINT;
  if (new Set(canon.slice(-8)).size === 1) return `That number is not a real line. ${PHONE_HINT}`;
  return '';
}

export function checkPlace(value, label = 'the place', {
  required = true, maxLength = 100, example = 'e.g. Westlands, Kencom or Moi Avenue',
} = {}) {
  const text = clean(value);
  if (!text) return required ? `Enter ${label}, ${example}.` : '';
  if (text.length > maxLength) return `Keep ${label} under ${maxLength} characters.`;
  if (!PLACE_CHARS.test(text)) return `Use letters, numbers, spaces and , . - ' / & ( ) only for ${label}, ${example}.`;
  const letters = count(LETTER, text);
  if (letters < 2 || count(/\d/g, text) > letters) return `Write ${label} in words, ${example}.`;
  if (PLACEHOLDERS.has(text.toLowerCase())) return `"${text}" is not a real name. Enter ${label}, ${example}.`;
  return wordsProblem(text, label);
}

export function checkName(value, label = 'the name', { parts = 2, maxLength = 100 } = {}) {
  const text = clean(value);
  const example = 'e.g. Collins Otieno';
  const words = text ? text.split(' ') : [];
  if (text.length > maxLength) return `Keep ${label} under ${maxLength} characters.`;
  if (words.length < parts) return `Enter the ${parts === 2 ? 'first and last name' : 'name'} for ${label}, ${example}.`;
  if (words.some((w) => w.length < 2 || !NAME_PART.test(w))) {
    return `Each name in ${label} needs 2 or more letters (no numbers or symbols), ${example}.`;
  }
  if (PLACEHOLDERS.has(text.toLowerCase()) || words.some((w) => PLACEHOLDERS.has(w.toLowerCase()))) {
    return `Enter a real name for ${label}, ${example}.`;
  }
  return wordsProblem(text, label);
}

export function checkText(value, label = 'this field', {
  required = true, minLetters = 3, maxLength = 1000,
} = {}) {
  const text = String(value ?? '').trim();
  if (!text) return required ? `Please fill in ${label}.` : '';
  if (text.length > maxLength) return `Keep ${label} under ${maxLength} characters.`;
  if (count(LETTER, text) < minLetters) return `Describe ${label} in words (at least ${minLetters} letters).`;
  if (PLACEHOLDERS.has(text.toLowerCase().replace(/[.!?]+$/, ''))) {
    return `"${text}" does not describe anything. Please fill in ${label}.`;
  }
  return wordsProblem(text, label);
}
