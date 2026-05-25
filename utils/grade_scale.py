# Grade scale mapping for 0–16 scores.
# Adapted from the original GradesScale.py (MarkBook Project, ~2024).
# Removed pandas dependency — plain Python dict lookup.
#
# Aligns with the 5-band descriptor system used throughout the app:
#   Limited (1–3) | Working Towards (4–6) | At Standard (7–9)
#   Above Standard (10–12) | Well Above Standard (13–15) | Beyond Stage (16)

GRADE_MAP = {
    0:  ('—',    None,                    'band-none'),
    1:  ('E',    'Limited',               'band-limited'),
    2:  ('E+',   'Limited',               'band-limited'),
    3:  ('D-',   'Limited',               'band-limited'),
    4:  ('D',    'Working Towards',       'band-working'),
    5:  ('D+',   'Working Towards',       'band-working'),
    6:  ('C-',   'Working Towards',       'band-working'),
    7:  ('C',    'At Standard',           'band-standard'),
    8:  ('C+',   'At Standard',           'band-standard'),
    9:  ('B-',   'At Standard',           'band-standard'),
    10: ('B',    'Above Standard',        'band-above'),
    11: ('B+',   'Above Standard',        'band-above'),
    12: ('A-',   'Above Standard',        'band-above'),
    13: ('A',    'Well Above Standard',   'band-well-above'),
    14: ('A+',   'Well Above Standard',   'band-well-above'),
    15: ('A++',  'Well Above Standard',   'band-well-above'),
    16: ('A*',   'Beyond Stage',          'band-beyond'),
}


def get_grade(score):
    """
    Return (letter_grade, band_label, band_css) for a score of 0–16.

    Uses floor-matching: if a score somehow falls outside the map
    (shouldn't happen with validated inputs) it returns the nearest
    entry below it.
    """
    score = max(0, min(16, int(score)))
    if score in GRADE_MAP:
        return GRADE_MAP[score]
    # Fallback: walk down to nearest defined entry
    for s in range(score, -1, -1):
        if s in GRADE_MAP:
            return GRADE_MAP[s]
    return ('—', None, 'band-none')


def grade_letter(score):
    """Convenience — return just the letter grade string."""
    return get_grade(score)[0]


def band_label(score):
    """Convenience — return just the band label string."""
    return get_grade(score)[1]


if __name__ == '__main__':
    print(f"{'Score':>6}  {'Grade':>5}  Band")
    print('-' * 40)
    for s in range(0, 17):
        letter, band, _ = get_grade(s)
        print(f"{s:>6}  {letter:>5}  {band or '—'}")
