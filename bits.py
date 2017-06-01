#!/usr/bin/python

import sys
import argparse

class Loop:
    def __init__(self, is_vertical, is_reversed, amount):
        self.is_vertical = is_vertical
        self.is_reversed = is_reversed
        self.amount = amount

def make_loop_action(is_vertical, is_reversed):
    class LoopAction(argparse.Action):
        def __init__(self, option_strings, dest, nargs=None, **kwargs):
            super(LoopAction, self).__init__(option_strings, dest, **kwargs)
        def __call__(self, parser, namespace, values, option_strings=None):
            my_loop = Loop(is_vertical, is_reversed, values)
            curr_list = getattr(namespace, self.dest)
            if curr_list is None:
                curr_list = []
            setattr(namespace, self.dest, curr_list + [my_loop])
    return LoopAction

def loop_length(string):
    try:
        value = int(string)
    except:
        # We do this because otherwise argparse will emit the
        # error message "invalid loop_length value: 'foo'", which
        # is not consistent with the other messages.
        raise argparse.ArgumentTypeError(
            "{} is not an integer".format(string))
    if value <= 0:
        raise argparse.ArgumentTypeError(
            "{} is not positive".format(string))
    if value & (value - 1):
        raise argparse.ArgumentTypeError(
            "{} is not a power of two".format(string))
    return value

epilog = """
Note that the order of the looping options is significant,
and they can be repeated any number of times. For example,
using the command
    %(prog)s -h8 -v32 -h16
displays the 8 bits of each byte horizontally, LSB on the
left, in 16 columns each of height 32 bits (8 characters),
and going from top to bottom within each column.

Also note that due to alignment, the actual block size may
not be equal to the product of the repeat amounts. For
example, using the command
    %(prog)s -h8
results in a block size of 32 bits or 4 characters, due to
aligning the data to 4-row boundaries.
"""

parser = argparse.ArgumentParser(
    description="Visualize bits of a file using braille characters",
    conflict_handler="resolve",
    formatter_class=argparse.RawDescriptionHelpFormatter,
    epilog=epilog,
)
parser.set_defaults(bit_order="small", loops=[], separate=False,
    show_offset=False, line_nums=None)
parser.add_argument("-h", metavar="num", dest="loops", type=loop_length,
    action=make_loop_action(False, False),
    help="Loop (h)orizontally num times, from left to right (opposite of -H)")
parser.add_argument("-H", metavar="num", dest="loops", type=loop_length,
    action=make_loop_action(False, True),
    help="Loop (H)orizontally num times, from right to left (opposite of -h)")
parser.add_argument("-v", metavar="num", dest="loops", type=loop_length,
    action=make_loop_action(True, False),
    help="Loop (v)ertically num times, from top to bottom (opposite of -V)")
parser.add_argument("-V", metavar="num", dest="loops", type=loop_length,
    action=make_loop_action(True, True),
    help="Loop (V)ertically num times, from bottom to top (opposite of -v)")
parser.add_argument("infile", metavar="file", nargs="?",
    type=argparse.FileType('rb'), default=sys.stdin,
    help="The file to use, or stdin if omitted")
bit_order_group = parser.add_mutually_exclusive_group()
bit_order_group.add_argument("-b", dest="bit_order",
    action="store_const", const="small",
    help="Write each byte from LSB to MSB (default)")
bit_order_group.add_argument("-B", dest="bit_order",
    action="store_const", const="large",
    help="Write each byte from MSB to LSB")
parser.add_argument("-s", dest="separate",
    action="store_const", const=True,
    help="Separate each block of dots with an extra newline")
parser.add_argument("-o", dest="show_offset",
    action="store_const", const=True,
    help="Print the offset in the file before each block")
line_num_group = parser.add_mutually_exclusive_group()
line_num_group.add_argument("-l", dest="line_nums",
    action="store_const", const="relative",
    help="Add hexadecimal line numbers, relative to current block")
line_num_group.add_argument("-L", dest="line_nums",
    action="store_const", const="absolute",
    help="Add hexadecimal line numbers, relative to start of output")

args = parser.parse_args()

horiz_size = 1
vert_size = 1
for loop in args.loops:
    if loop.is_vertical:
        vert_size *= loop.amount
    else:
        horiz_size *= loop.amount
block_size_bits = horiz_size * vert_size

def add_vert(num):
    args.loops.append(Loop(True, False, num))
    global vert_size
    vert_size *= num
    global block_size_bits
    block_size_bits *= num
# Braille characters have 4 rows of dots per character, so
# we can't output a number of rows that isn't a multiple of 4.
# Here, we just add extra repeats until the dots align with the
# character boundaries.
[
    lambda: None,        lambda: add_vert(4),
    lambda: add_vert(2), lambda: add_vert(4),
][vert_size % 4]()

if block_size_bits % 8:
    # Also, we need to make sure that the number of bits is a
    # multiple of 8. Since we previously aligned the vertical size
    # to a multiple of 4, and the total number of bits must be a multiple
    # of the vertical size, we just add a vertical repeat if there is
    # a problem.
    # Currently only happens if the vertical size is 1, 2, or 4, since we
    # only have repeats that are powers of two.
    add_vert(2)

# While it seems like adding all these extra vertical repeats
# will slow down the rest of the program (for example, -v2 turns into
# -v2 -v2 -v2), after preprocessing the loops, the rest of the code
# runs in the same time as if we had just used -v8.

def concat_horiz(xss, yss):
    return [xs + ys for xs, ys in zip(xss, yss)]
def concat_vert(xss, yss):
    # deep copy the nested lists, to avoid weird aliasing issues
    return [list(xs) for xs in xss] + [list(ys) for ys in yss]
def add_all(xss, val):
    return [[x + val for x in xs] for xs in xss]

def pad_horiz_multiple_of_two(xss, val):
    # Braille characters have width 2, so we need to avoid issues when
    # the number of columns is odd. This actually does not occur
    # unless the width is 1, but it will be useful if we extend this
    # to include repeats that are not powers of two.
    if len(xss[0]) % 2:
        return [xs + [None] for xs in xss]
    else:
        return xss

def gen_indices(loops):
    # Finds, for each bit in the output, the index of the corresponding
    # bit in the data.
    step = 1
    block = [[0]]
    for loop in loops:
        block_accum = block
        concat = concat_vert if loop.is_vertical else concat_horiz
        for i in range(1, loop.amount):
            new_block = add_all(block, i * step)
            if loop.is_reversed:
                xss = new_block
                yss = block_accum
            else:
                xss = block_accum
                yss = new_block
            block_accum = concat(xss, yss)
        step *= loop.amount
        block = block_accum
    block = pad_horiz_multiple_of_two(block, None)
    return block

indices = gen_indices(args.loops)

# The bits in braille characters may appear to be ordered strangely,
# because the lowest two dots were added later. See for example
# https://en.wikipedia.org/wiki/Braille_Patterns
# The following is a diagram of the bit orders (note: 1 is LSB, 8 is MSB)
#       1 4
#       2 5
#       3 6
#       7 8
# We store their order in this list. Once we reorder our actual bits
# into the braille order, we can convert them to a character directly.
braille_bits = [
    (3, 1), (3, 0), (2, 1), (1, 1), (0, 1), (2, 0), (1, 0), (0, 0)
]
# note that these offsets are stored as (row offset, column offset),
# with MSB first

def group_indices(indices):
    # Finds, for each character, the 8 indices/bits that make up
    # that character.
    assert len(indices) % 4 == 0
    assert len(indices[0]) % 2 == 0
    # first make sure our groups will make sense
    groups = []
    for r in range(0, len(indices), 4):
        line = []
        for c in range(0, len(indices[0]), 2):
            char_bit_indices = []
            for dr, dc in braille_bits:
                char_bit_indices.append(indices[r+dr][c+dc])
            line.append(char_bit_indices)
        groups.append(line)
    return groups

grouped_indices = group_indices(indices)

bits_range = range(8) # small first
if args.bit_order == "large":
    # reverse the order
    bits_range = bits_range[::-1]

int_to_bits = [[(x >> i) & 1 for i in bits_range] for x in range(256)]
# Note that the efficiency of all the above code is not that important
# since we only run it once.

# The rest of the code should be relatively efficient, as it is run
# over all of the data, which is why we perform the preprocessing
# steps above. Of course, Python isn't exactly the fastest language ever,
# so maybe we shouldn't care that much?

def to_bits(chars):
    bits = []
    for c in chars:
        bits.extend(int_to_bits[ord(c)])
    return bits

assert block_size_bits % 8 == 0
block_size_bytes = block_size_bits / 8

offset = 0
abs_line_num = 0
if args.line_nums:
    if args.line_nums == "relative":
        line_num_format = "0{}x".format(len(format(vert_size / 4 - 1, "0x")))
    else:
        line_num_format = "08x"

go = True
while go:
    data = args.infile.read(block_size_bytes)
    if len(data) == 0:
        # don't try to output extra, empty blocks
        break
    if len(data) < block_size_bytes:
        # can't break because we need to finish printing this block
        go = False
        data += "\x00" * (block_size_bytes - len(data))
    data_bits = to_bits(data)
    if args.show_offset:
        sys.stdout.write("offset=0x{}\n".format(format(offset, "08x")))
    rel_line_num = 0
    for line in grouped_indices:
        str_out = ""
        for char in line:
            accum = 0
            for ind in char:
                if ind is None:
                    accum = accum * 2 # treat as 0
                else:
                    accum = accum * 2 + data_bits[ind]
            str_out += unichr(0x2800 + accum)
            # 0x2800 is the "base" for the Unicode braille characters
        actual_str_out = str_out.encode("utf-8") + '\n'
        if args.line_nums:
            if args.line_nums == "relative":
                line_num = rel_line_num
            else:
                line_num = abs_line_num
            line_num_str = "0x{}: ".format(format(line_num, line_num_format))
            actual_str_out = line_num_str + actual_str_out
        sys.stdout.write(actual_str_out)
        abs_line_num += 1
        rel_line_num += 1
    if args.separate:
        sys.stdout.write('\n')
    offset += block_size_bytes
