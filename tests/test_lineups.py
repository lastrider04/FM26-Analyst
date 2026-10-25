"""Line-up vectors are read from their own begin/end, never from neighbouring pointers."""
from reader.matches import MIN_PLAYED, vector_records

BEGIN = 0x10_000


def setup(n=20, stray_before=True, neighbour_after=20):
    """Holder slots: an optional stray pointer just before our vector, ours, and another team's vector right after."""
    holders = {}
    if stray_before:
        holders[BEGIN - 8] = 0xDEAD                                 # e.g. an unrelated pointer to another club's record
    for i in range(n):
        holders[BEGIN + 8 * i] = 0xA000 + i                         # our players' match records
    for i in range(neighbour_after):
        holders[BEGIN + 8 * (n + i)] = 0xB000 + i                   # the opponent's vector, contiguous with ours
    return holders


def header(begin, end, cap):
    mem = {0x500: begin, 0x508: end, 0x510: cap}
    return lambda a: mem.get(a, 0)


def test_only_records_between_begin_and_end():
    recs = vector_records(header(BEGIN, BEGIN + 20 * 8, BEGIN + 24 * 8), setup(), 0x500)
    assert recs == [0xA000 + i for i in range(20)]                  # no stray before, no opponent after


def test_implausible_headers_are_ignored():
    h = setup()
    assert vector_records(header(BEGIN - 8, BEGIN + 20 * 8, 0), h, 0x500) is None             # no capacity
    assert vector_records(header(BEGIN, BEGIN - 8, BEGIN + 8), h, 0x500) is None              # end before begin
    assert vector_records(header(BEGIN, BEGIN + (MIN_PLAYED - 1) * 8, BEGIN + 400), h, 0x500) is None   # too short
    assert vector_records(header(BEGIN, BEGIN + 20 * 8 + 4, BEGIN + 400), h, 0x500) is None   # not whole slots


def test_gap_inside_the_vector_rejects_it():
    h = setup()
    del h[BEGIN + 5 * 8]
    assert vector_records(header(BEGIN, BEGIN + 20 * 8, BEGIN + 24 * 8), h, 0x500) is None
