import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from solution import Sheet  # noqa: E402


def mk(**cells):
    s = Sheet()
    for k, v in cells.items():
        s.set(k, v)
    return s


# ---------------------------------------------------------------- step 1
def test_s1_int_float_text():
    s = mk(A1="5", A2="-7", A3="2.5", A4="-0.25", A5="hello", A6="+5", A7="1.", A8=".5", A9="1e3")
    assert s.get("A1") == 5 and type(s.get("A1")) is int
    assert s.get("A2") == -7 and type(s.get("A2")) is int
    assert s.get("A3") == 2.5 and type(s.get("A3")) is float
    assert s.get("A4") == -0.25
    assert s.get("A5") == "hello"
    for c, r in (("A6", "+5"), ("A7", "1."), ("A8", ".5"), ("A9", "1e3")):
        assert s.get(c) == r


def test_s1_empty_and_clear():
    s = Sheet()
    assert s.get("A1") is None
    assert s.raw("A1") == ""
    s.set("A1", "3")
    s.set("A1", "")
    assert s.get("A1") is None and s.raw("A1") == ""


def test_s1_raw_preserved():
    s = mk(A1="007", B1="= 1 +  2 ", C1="  x ")
    assert s.raw("A1") == "007" and s.get("A1") == 7
    assert s.raw("B1") == "= 1 +  2 "
    assert s.raw("C1") == "  x " and s.get("C1") == "  x "


def test_s1_text_looks_like_number_variants():
    s = mk(A1="1 2", A2="--1", A3="1,5")
    assert s.get("A1") == "1 2" and s.get("A2") == "--1" and s.get("A3") == "1,5"


def test_s1_overwrite():
    s = mk(A1="x")
    s.set("A1", "4")
    assert s.get("A1") == 4


# ---------------------------------------------------------------- step 2
def test_s2_example():
    s = mk(A1="2", A2="=A1*3+1")
    assert s.get("A2") == 7 and type(s.get("A2")) is int


def test_s2_precedence_assoc():
    s = mk(A1="=2+3*4", A2="=10-4-3", A3="=(2+3)*4", A4="=100/10/5", A5="=-2*-3", A6="=--4", A7="=2*(3+4)*5")
    assert s.get("A1") == 14
    assert s.get("A2") == 3
    assert s.get("A3") == 20
    assert s.get("A4") == 2.0
    assert s.get("A5") == 6
    assert s.get("A6") == 4
    assert s.get("A7") == 70


def test_s2_types():
    s = mk(A1="=1+2", A2="=1+2.0", A3="=2*2.5", A4="=6/3", A5="=3-1", A6="=1.5-0.5")
    assert type(s.get("A1")) is int
    assert type(s.get("A2")) is float and s.get("A2") == 3.0
    assert type(s.get("A3")) is float and s.get("A3") == 5.0
    assert s.get("A4") == 2.0 and type(s.get("A4")) is float
    assert type(s.get("A5")) is int
    assert type(s.get("A6")) is float


def test_s2_whitespace():
    s = mk(A1="2", A2="=  A1 *\t3  +   1 ", A3="= - A1", A4="=( A1 + 1 )*2")
    assert s.get("A2") == 7
    assert s.get("A3") == -2
    assert s.get("A4") == 6


def test_s2_empty_ref_is_zero():
    s = mk(A1="=B1+1", A2="=B1", A3="=B1*5", A4="=1/B1")
    assert s.get("A1") == 1
    assert s.get("A2") == 0
    assert s.get("A3") == 0
    assert s.get("A4") == "#DIV/0!"


def test_s2_refs_chain_and_float_literals():
    s = mk(A1="1.5", B1="=A1*2", C1="=B1+0.5")
    assert s.get("B1") == 3.0 and s.get("C1") == 3.5


def test_s2_unary_plus_not_supported():
    assert mk(A1="=+1").get("A1") == "#VALUE!"


# ---------------------------------------------------------------- step 3
def test_s3_text_in_arithmetic():
    s = mk(A1="hi", B1="=A1+1", B2="=1+A1", B3="=-A1", B4="=A1*A1", B5="=A1")
    for c in ("B1", "B2", "B3", "B4", "B5"):
        assert s.get(c) == "#VALUE!"


def test_s3_div0():
    s = mk(A1="=1/0", A2="=1/(2-2)", A3="=1/0.0", A4="=0/0")
    for c in ("A1", "A2", "A3", "A4"):
        assert s.get(c) == "#DIV/0!"


def test_s3_error_propagation_left_wins():
    s = mk(A1="=1/0", A2="x", B1="=A1+A2", B2="=A2+A1", C1="=A1", D1="=C1*2",
           E1="=A2+1", F1="=E1+A1", G1="=A1+E1", H1="=A1+#REF!", I1="=#REF!+A1")
    assert s.get("B1") == "#DIV/0!"
    assert s.get("B2") == "#DIV/0!"  # error operand beats text operand
    assert s.get("C1") == "#DIV/0!"
    assert s.get("D1") == "#DIV/0!"
    assert s.get("F1") == "#VALUE!"  # left (#VALUE!) wins
    assert s.get("G1") == "#DIV/0!"
    assert s.get("H1") == "#DIV/0!"
    assert s.get("I1") == "#REF!"


def test_s3_unparsable():
    bad = ["=", "=1+", "=*2", "=(1", "=1)", "=A1 A2", "=foo", "=a1", "=1.", "=.5", "=1 2", "=A0",
           "=FOO(1)", "=sum(1)", "=1+*2", "=$", "=A1:B2", "=(A1:B2)", "=SUM(1,)", "=SUM(,1)", "=SUM(1 2)",
           "=A", "=1 + 'x'", "=A1B1"]
    s = Sheet()
    for i, f in enumerate(bad):
        s.set(f"A{i + 1}", f)
    for i, f in enumerate(bad):
        assert s.get(f"A{i + 1}") == "#VALUE!", f
        assert s.raw(f"A{i + 1}") == f


def test_s3_error_in_dependent_of_unparsable():
    s = mk(A1="=1+", B1="=A1+1")
    assert s.get("B1") == "#VALUE!"


# ---------------------------------------------------------------- step 4
def test_s4_recalc():
    s = mk(A1="1", A2="=A1+1", A3="=A2+1", B1="=A3*2")
    assert s.get("B1") == 6
    s.set("A1", "10")
    assert s.get("A2") == 11 and s.get("A3") == 12 and s.get("B1") == 24
    s.set("A1", "")
    assert s.get("B1") == 4


def test_s4_forward_reference_defined_later():
    s = Sheet()
    s.set("A1", "=B1+1")
    assert s.get("A1") == 1
    s.set("B1", "5")
    assert s.get("A1") == 6
    s.set("B1", "x")
    assert s.get("A1") == "#VALUE!"
    s.set("B1", "=1/0")
    assert s.get("A1") == "#DIV/0!"


def test_s4_long_chain_no_recursion_error():
    s = Sheet()
    s.set("A1", "1")
    for r in range(2, 1000):
        s.set(f"A{r}", f"=A{r - 1}+1")
    assert s.get("A999") == 999


# ---------------------------------------------------------------- step 5
def test_s5_basic():
    s = mk(A1="1", A2="2", A3="3", B1="4", B2="5", B3="6", C1="10")
    s.set("D1", "=SUM(A1:B3, C1*2, 5)")
    assert s.get("D1") == 21 + 20 + 5
    s.set("D2", "=MIN(A1:B3)")
    s.set("D3", "=MAX(A1:B3)")
    s.set("D4", "=AVG(A1:B3)")
    s.set("D5", "=COUNT(A1:B3)")
    assert (s.get("D2"), s.get("D3"), s.get("D4"), s.get("D5")) == (1, 6, 3.5, 6)
    assert type(s.get("D4")) is float


def test_s5_reversed_corners():
    s = mk(A1="1", A2="2", B1="3", B2="4", C1="=SUM(B2:A1)", C2="=SUM(B1:A2)", C3="=SUM(A2:B1)")
    assert s.get("C1") == 10 and s.get("C2") == 10 and s.get("C3") == 10


def test_s5_skips_empty_and_text_in_ranges():
    s = mk(A1="1", A2="text", A4="3", B1="=SUM(A1:A5)", B2="=COUNT(A1:A5)", B3="=AVG(A1:A5)",
           B4="=MIN(A1:A5)", B5="=MAX(A1:A5)")
    assert s.get("B1") == 4 and s.get("B2") == 2 and s.get("B3") == 2.0
    assert s.get("B4") == 1 and s.get("B5") == 3


def test_s5_errors():
    s = mk(A1="1", A2="=1/0", A3="=1/0", A4="=B9+hello", B1="=SUM(A1:A3)")
    s.set("A3", "=A9+x")  # #VALUE!
    assert s.get("B1") == "#DIV/0!"  # first in row-major (A2)
    s.set("C1", "=SUM(A3, A2)")
    assert s.get("C1") == "#VALUE!"  # first argument wins
    s.set("C2", "=SUM(A2:A3)")
    assert s.get("C2") == "#DIV/0!"
    s.set("D1", "=1")
    s.set("D2", "=#REF!")
    s.set("E1", "=SUM(D1:D2)")
    assert s.get("E1") == "#REF!"
    s.set("E2", "=COUNT(A1:A3)")
    assert s.get("E2") == "#DIV/0!"


def test_s5_row_major_first_error():
    s = mk(A1="1", B1="=1/0", A2="=#REF!", C1="=SUM(A1:B2)", C2="=SUM(B2:A1)")
    # row-major: A1, B1(#DIV/0!), A2(#REF!) -> B1 first
    assert s.get("C1") == "#DIV/0!"
    assert s.get("C2") == "#DIV/0!"
    s2 = mk(A2="=1/0", B1="=#REF!", C1="=SUM(A1:B2)")
    assert s2.get("C1") == "#REF!"  # B1 precedes A2 in row-major


def test_s5_empty_results():
    s = mk(A1="x", B1="=SUM(A1:A3)", B2="=MIN(A1:A3)", B3="=MAX(A1:A3)", B4="=AVG(A1:A3)", B5="=COUNT(A1:A3)",
           B6="=SUM()", B7="=AVG()", B8="=COUNT()")
    assert s.get("B1") == 0 and type(s.get("B1")) is int
    assert s.get("B2") == 0 and s.get("B3") == 0
    assert s.get("B4") == "#DIV/0!"
    assert s.get("B5") == 0
    assert s.get("B6") == 0 and s.get("B7") == "#DIV/0!" and s.get("B8") == 0


def test_s5_types():
    s = mk(A1="1", A2="2", A3="2.5", B1="=SUM(A1:A2)", B2="=SUM(A1:A3)", B3="=MIN(A1:A2)", B4="=MAX(A1:A3)",
           B5="=MIN(A1:A3)", B6="=AVG(A1:A2)", B7="=SUM(1,2)", B8="=MAX(A1:A2)")
    assert type(s.get("B1")) is int and s.get("B1") == 3
    assert type(s.get("B2")) is float and s.get("B2") == 5.5
    assert type(s.get("B3")) is int and s.get("B3") == 1
    assert type(s.get("B4")) is float and s.get("B4") == 2.5
    assert type(s.get("B5")) is float and s.get("B5") == 1.0
    assert type(s.get("B6")) is float and s.get("B6") == 1.5
    assert type(s.get("B7")) is int
    assert type(s.get("B8")) is int and s.get("B8") == 2


def test_s5_nesting_and_in_expressions():
    s = mk(A1="1", A2="5", A3="3", B1="=1+MAX(A1:A3)*2", B2="=SUM(MAX(A1:A2), MIN(A2:A3), 1)",
           B3="=-SUM(A1:A3)", B4="=(SUM(A1:A3))/3", B5="=MAX( A1 : A3 )", B6="=SUM ( A1:A3 )")
    assert s.get("B1") == 11
    assert s.get("B2") == 5 + 3 + 1
    assert s.get("B3") == -9
    assert s.get("B4") == 3.0
    assert s.get("B5") == 5 and s.get("B6") == 9


def test_s5_expression_args():
    s = mk(A1="x", A2="4", B1="=SUM(A1)", B2="=SUM(A1*2)", B3="=SUM(A2, A2)", B4="=COUNT(A2, 3, 1+1)",
           B5="=COUNT(C1)", B6="=MIN(C1, 5)", B7="=SUM(1/0, #REF!)")
    assert s.get("B1") == "#VALUE!" and s.get("B2") == "#VALUE!"
    assert s.get("B3") == 8 and s.get("B4") == 3
    assert s.get("B5") == 1  # empty ref in expression counts as 0
    assert s.get("B6") == 0
    assert s.get("B7") == "#DIV/0!"


def test_s5_functions_uppercase_only():
    s = mk(A1="1", B1="=sum(A1:A1)", B2="=Sum(A1:A1)")
    assert s.get("B1") == "#VALUE!" and s.get("B2") == "#VALUE!"


def test_s5_range_recalc():
    s = mk(A1="1", A2="2", B1="=SUM(A1:A3)")
    assert s.get("B1") == 3
    s.set("A3", "10")
    assert s.get("B1") == 13


# ---------------------------------------------------------------- step 6
def test_s6_self_ref():
    s = mk(A1="=A1")
    assert s.get("A1") == "#CYCLE!"
    s.set("A2", "=A2+1")
    assert s.get("A2") == "#CYCLE!"


def test_s6_two_cycle_and_dependents_and_break():
    s = mk(A1="=B1", B1="=A1", C1="=A1+1", D1="=C1*2", E1="5")
    for c in ("A1", "B1", "C1", "D1"):
        assert s.get(c) == "#CYCLE!"
    assert s.get("E1") == 5
    s.set("B1", "7")
    assert s.get("A1") == 7 and s.get("C1") == 8 and s.get("D1") == 16


def test_s6_range_containing_self():
    s = mk(A1="1", A2="=SUM(A1:A3)", A3="2")
    assert s.get("A2") == "#CYCLE!"
    s.set("B1", "=SUM(A1:A3)")
    assert s.get("B1") == "#CYCLE!"  # depends on cycle cell
    s.set("A2", "5")
    assert s.get("B1") == 8


def test_s6_long_cycle():
    s = Sheet()
    n = 50
    for r in range(1, n + 1):
        s.set(f"A{r}", f"=A{r % n + 1}")
    s.set("B1", "=A1")
    assert all(s.get(f"A{r}") == "#CYCLE!" for r in range(1, n + 1))
    assert s.get("B1") == "#CYCLE!"
    s.set("A25", "9")
    assert all(s.get(f"A{r}") == 9 for r in range(1, n + 1))
    assert s.get("B1") == 9


def test_s6_cycle_beats_error_ordering_left_wins():
    s = mk(A1="=A1", B1="=1/0", C1="=B1+A1", D1="=A1+B1")
    assert s.get("C1") == "#DIV/0!"
    assert s.get("D1") == "#CYCLE!"


def test_s6_not_cycle_diamond():
    s = mk(A1="1", B1="=A1", C1="=A1", D1="=B1+C1")
    assert s.get("D1") == 2


def test_s6_cycle_through_function_arg_even_if_error_first():
    s = mk(A1="=SUM(1/0, B1)", B1="=A1")
    assert s.get("A1") == "#CYCLE!" and s.get("B1") == "#CYCLE!"


# ---------------------------------------------------------------- step 7
def test_s7_abs_eval():
    s = mk(A1="5", B1="=$A$1+A$1+$A1+A1", C1="= $A$1*2")
    assert s.get("B1") == 20 and s.get("C1") == 10
    s.set("D1", "=SUM($A$1:$A$1, A$1:$A1)")
    assert s.get("D1") == 10


def test_s7_example():
    s = mk(A1="1", B1="=A1+$A$1")
    s.copy("B1", "C2")
    assert s.raw("C2") == "=B2+$A$1"


def test_s7_copy_variants():
    s = mk(B2="=A1+$A1+A$1+$A$1")
    s.copy("B2", "D5")  # +2 cols, +3 rows
    assert s.raw("D5") == "=C4+$A4+C$1+$A$1"
    s.copy("B2", "C2")  # +1 col, 0 rows
    assert s.raw("C2") == "=B1+$A1+B$1+$A$1"
    s.copy("B2", "A2")  # -1 col: A1 and A$1 fall off the left edge
    assert s.raw("A2") == "=#REF!+$A1+#REF!+$A$1"
    assert s.get("A2") == "#REF!"


def test_s7_copy_out_of_bounds_exact():
    s = mk(B2="=A1")
    s.copy("B2", "A2")
    assert s.raw("A2") == "=#REF!" and s.get("A2") == "#REF!"
    s.copy("B2", "B1")
    assert s.raw("B1") == "=#REF!" and s.get("B1") == "#REF!"
    s.set("Y1", "=Z1+1")
    s.copy("Y1", "Z1")
    assert s.raw("Z1") == "=#REF!+1"
    assert s.get("Z1") == "#REF!"


def test_s7_copy_abs_oob_not_shifted():
    s = mk(B2="=$A$1+$A1+A$1")
    s.copy("B2", "A2")
    # $A$1 fixed; $A1 col fixed row 1 -> row 1 stays? row relative: 1+0 -> 1; A$1: col 0-1 -> out
    assert s.raw("A2") == "=$A$1+$A1+#REF!"
    s.copy("B2", "B1")
    # $A$1 fixed; $A1 -> row 0 out; A$1 -> A$1 (col shift 0)
    assert s.raw("B1") == "=$A$1+#REF!+A$1"


def test_s7_range_oob_whole():
    s = mk(C3="=SUM(B2:C3)+1")
    s.copy("C3", "B3")  # B2:C3 -> A2:B3 fine
    assert s.raw("B3") == "=SUM(A2:B3)+1"
    s.copy("C3", "A3")  # B2:C3 -> col -1.. out
    assert s.raw("A3") == "=SUM(#REF!)+1"
    assert s.get("A3") == "#REF!"
    s.set("C2", "=SUM(A1:B1, 3)")
    s.copy("C2", "C1")  # A1:B1 -> row 0
    assert s.raw("C1") == "=SUM(#REF!, 3)"
    s.set("B2", "=SUM(A1:B5)")
    s.copy("B2", "B3")  # corner 1 fine; both rows shift fine -> A2:B6
    assert s.raw("B3") == "=SUM(A2:B6)"
    s.set("C5", "=SUM($A$1:B1)")
    s.copy("C5", "C4")  # second corner row 0 -> out
    assert s.raw("C4") == "=SUM(#REF!)"


def test_s7_preserves_text_exactly():
    s = mk(A1="1", B1="=  SUM( A1 : A2 ,  3.50 ) +   A1  * 2 ")
    s.copy("B1", "C1")
    assert s.raw("C1") == "=  SUM( B1 : B2 ,  3.50 ) +   B1  * 2 "
    s.copy("B1", "B2")
    assert s.raw("B2") == "=  SUM( A2 : A3 ,  3.50 ) +   A2  * 2 "


def test_s7_copy_nonformula_and_empty():
    s = mk(A1="hello", A2="5", A3="=1+1")
    s.copy("A1", "B1")
    s.copy("A2", "B2")
    s.copy("A3", "B3")
    assert s.raw("B1") == "hello" and s.raw("B2") == "5" and s.raw("B3") == "=1+1"
    s.copy("C9", "B1")
    assert s.raw("B1") == "" and s.get("B1") is None


def test_s7_copy_evaluates():
    s = mk(A1="1", A2="2", A3="3", B1="=A1*10")
    s.copy("B1", "B2")
    s.copy("B1", "B3")
    assert s.get("B2") == 20 and s.get("B3") == 30


def test_s7_copy_onto_self_and_overwrite():
    s = mk(A1="=B1", B1="3")
    s.copy("A1", "A1")
    assert s.raw("A1") == "=B1"
    s.set("C1", "old")
    s.copy("A1", "C1")
    assert s.raw("C1") == "=D1"


def test_s7_copy_keeps_unparsable_and_refs_in_unparsable():
    s = mk(A1="=B1+")
    s.copy("A1", "A2")
    assert s.raw("A2") == "=B2+" and s.get("A2") == "#VALUE!"


def test_s7_copy_already_ref_text():
    s = mk(A1="=#REF!+B1")
    s.copy("A1", "A2")
    assert s.raw("A2") == "=#REF!+B2"


def test_s7_copy_does_not_touch_function_names_or_numbers():
    s = mk(B1="=MAX(A1:A2)+COUNT(A1)+12+3.5")
    s.copy("B1", "C1")
    assert s.raw("C1") == "=MAX(B1:B2)+COUNT(B1)+12+3.5"


# ---------------------------------------------------------------- step 8
def test_s8_example():
    s = mk(A1="1", A2="2", A3="=SUM(A1:A2)")
    s.insert_rows(2, 1)
    assert s.raw("A4") == "=SUM(A1:A3)"
    assert s.get("A4") == 3
    assert s.raw("A3") == "2" and s.raw("A2") == "" and s.get("A2") is None


def test_s8_all_refs_incremented_including_absolute():
    s = mk(A1="1", A2="2", A3="3", B1="=A2+$A$3+A$1+$A1", C5="=A3+A1")
    s.insert_rows(2, 2)
    assert s.raw("B1") == "=A4+$A$5+A$1+$A1"
    assert s.raw("C7") == "=A5+A1"
    assert s.raw("A1") == "1" and s.raw("A4") == "2" and s.raw("A5") == "3"
    assert s.get("B1") == 2 + 3 + 1 + 1


def test_s8_ref_at_boundary():
    s = mk(A1="1", A2="2", B1="=A1", B2="=A2")
    s.insert_rows(2, 3)
    assert s.raw("B1") == "=A1"
    assert s.raw("B5") == "=A5"
    s.insert_rows(1, 1)
    assert s.raw("B2") == "=A2"
    assert s.raw("B6") == "=A6"


def test_s8_ranges():
    s = mk(A1="=SUM(A2:A4)", B1="=SUM(A5:A6)", C1="=SUM(A1:A2)", D1="=SUM(A4:A3)", E1="=SUM($A$1:$A$9)")
    s.insert_rows(3, 2)
    # A2:A4 spans (top 2 < 3 <= 4): grows -> A2:A6
    assert s.raw("A1") == "=SUM(A2:A6)"
    assert s.raw("B1") == "=SUM(A7:A8)"
    assert s.raw("C1") == "=SUM(A1:A2)"
    assert s.raw("D1") == "=SUM(A6:A5)"  # reversed corners, both >= at, both move
    assert s.raw("E1") == "=SUM($A$1:$A$11)"


def test_s8_range_top_at_at():
    s = mk(A1="=SUM(A2:A3)")
    s.insert_rows(2, 1)  # top == at -> moves
    assert s.raw("A1") == "=SUM(A3:A4)"


def test_s8_values_recompute_and_text_kept():
    s = mk(A1="1", A2="2", A3="=A1+A2", A4="txt")
    s.insert_rows(2, 1)
    s.set("A2", "10")
    assert s.raw("A4") == "=A1+A3" and s.get("A4") == 3
    s.set("A3", "5")
    assert s.get("A4") == 6
    assert s.get("A5") == "txt"


def test_s8_unparsable_and_ref_text_untouched():
    s = mk(A1="=A2+", A2="=#REF!+A3")
    s.insert_rows(2, 1)
    assert s.raw("A1") == "=A3+"
    assert s.raw("A3") == "=#REF!+A4"


def test_s8_preserves_spacing():
    s = mk(A5="=  SUM( A1 : A5 )  +  A2")
    s.insert_rows(2, 1)
    assert s.raw("A6") == "=  SUM( A1 : A6 )  +  A3"


def test_s8_insert_beyond_content():
    s = mk(A1="1", B1="=A1")
    s.insert_rows(50, 3)
    assert s.raw("B1") == "=A1" and s.get("B1") == 1


def test_s8_cycle_values_after_insert():
    s = mk(A1="=A2", A2="=A1")
    s.insert_rows(2, 1)
    assert s.raw("A1") == "=A3" and s.raw("A3") == "=A1"
    assert s.get("A1") == "#CYCLE!"


# ---------------------------------------------------------------- step 9
def test_s9_example():
    s = Sheet()
    for i in range(1, 6):
        s.set(f"A{i}", str(i))
    s.set("B1", "=SUM(A1:A5)")
    s.delete_rows(2, 2)
    assert s.raw("B1") == "=SUM(A1:A3)"
    assert s.get("B1") == 1 + 4 + 5
    assert [s.raw(f"A{i}") for i in range(1, 5)] == ["1", "4", "5", ""]


def test_s9_single_refs():
    s = mk(A1="1", A2="2", A3="3", A4="4", B1="=A1+A2+A3+A4+$A$4+A$3+$A3")
    s.delete_rows(2, 1)
    assert s.raw("B1") == "=A1+#REF!+A2+A3+$A$3+A$2+$A2"
    assert s.get("B1") == "#REF!"


def test_s9_deleted_cells_dropped_and_refs_to_them_in_other_cells():
    s = mk(A1="=B2", B2="=1", A3="=B3", B3="5")
    s.delete_rows(2, 1)
    assert s.raw("A1") == "=#REF!" and s.get("A1") == "#REF!"
    assert s.raw("A2") == "=B2" and s.get("A2") == 5
    assert s.raw("B2") == "5"
    assert s.raw("B3") == ""


def test_s9_range_shrink_each():
    def run(formula, at, n):
        s = mk(Z20=formula)
        s.delete_rows(at, n)
        return s.raw("Z20" if at > 20 or at + n - 1 < 20 and False else _pos(20, at, n))

    def _pos(r, at, n):
        return "Z%d" % (r - n if r >= at + n else r)

    assert run("=SUM(A3:A8)", 4, 2) == "=SUM(A3:A6)"      # middle deleted
    assert run("=SUM(A3:A8)", 1, 4) == "=SUM(A1:A4)"      # top part deleted -> remaining rows 5..8 -> 1..4
    assert run("=SUM(A3:A8)", 7, 5) == "=SUM(A3:A6)"      # bottom part deleted -> remaining 3..6
    assert run("=SUM(A3:A8)", 3, 6) == "=SUM(#REF!)"      # all deleted
    assert run("=SUM(A3:A8)", 1, 3) == "=SUM(A1:A5)"      # top rows 3 deleted, top moves to at=1, bottom 8-3=5
    assert run("=SUM(A3:A8)", 8, 1) == "=SUM(A3:A7)"
    assert run("=SUM(A3:A8)", 3, 1) == "=SUM(A3:A7)"
    assert run("=SUM(A3:A3)", 3, 1) == "=SUM(#REF!)"
    assert run("=SUM(A3:A8)", 2, 1) == "=SUM(A2:A7)"
    assert run("=SUM(A3:A8)", 9, 2) == "=SUM(A3:A8)"
    assert run("=SUM(A8:A3)", 4, 2) == "=SUM(A6:A3)"       # reversed corners preserved


def test_s9_range_abs_and_spacing():
    s = mk(Z20="=SUM( $A$3 : B$8 ) + A9")
    s.delete_rows(4, 2)
    assert s.raw("Z18") == "=SUM( $A$3 : B$6 ) + A7"


def test_s9_values_recompute():
    s = mk(A1="1", A2="2", A3="3", B1="=SUM(A1:A3)", B3="=A3")
    s.delete_rows(3, 1)
    assert s.raw("B1") == "=SUM(A1:A2)" and s.get("B1") == 3
    assert s.raw("B3") == ""


def test_s9_ref_text_and_unparsable():
    s = mk(A5="=#REF!+A6+", A6="x")
    s.delete_rows(1, 2)
    assert s.raw("A3") == "=#REF!+A4+"


def test_s9_delete_beyond_content():
    s = mk(A1="1", B1="=A1")
    s.delete_rows(50, 3)
    assert s.raw("B1") == "=A1" and s.get("B1") == 1


# --------------------------------------------------------------- step 10
def test_s10_undo_set():
    s = Sheet()
    assert s.undo() is False and s.redo() is False
    s.set("A1", "1")
    s.set("A2", "=A1+1")
    s.set("A1", "5")
    assert s.get("A2") == 6
    assert s.undo() is True
    assert s.get("A1") == 1 and s.get("A2") == 2
    assert s.undo() is True
    assert s.get("A2") is None and s.raw("A2") == ""
    assert s.undo() is True
    assert s.get("A1") is None
    assert s.undo() is False


def test_s10_redo():
    s = mk(A1="1")
    s.set("A1", "2")
    s.undo()
    assert s.get("A1") == 1
    assert s.redo() is True
    assert s.get("A1") == 2
    assert s.redo() is False
    s.undo()
    s.undo()
    assert s.get("A1") is None
    assert s.redo() is True and s.get("A1") == 1
    assert s.redo() is True and s.get("A1") == 2


def test_s10_new_action_clears_redo():
    s = mk(A1="1")
    s.set("A1", "2")
    s.undo()
    s.set("B1", "x")
    assert s.redo() is False
    assert s.get("A1") == 1 and s.get("B1") == "x"
    s.undo()
    s.copy("A1", "C1")
    assert s.redo() is False


def test_s10_copy_insert_delete_undo_redo():
    s = Sheet()
    for c, r in (("A1", "1"), ("A2", "2"), ("A3", "=SUM(A1:A2)"), ("B1", "=A1+$A$1")):
        s.set(c, r)
    base_actions = 4
    before = {c: s.raw(c) for c in ("A1", "A2", "A3", "A4", "B1", "B2", "C2")}

    def snap():
        return {c: s.raw(c) for c in before}

    s.copy("B1", "C2")
    assert s.raw("C2") == "=B2+$A$1"
    s1 = snap()
    s.insert_rows(2, 1)
    assert s.raw("A4") == "=SUM(A1:A3)"
    s2 = snap()
    s.delete_rows(1, 1)
    s3 = snap()
    assert s.undo() and snap() == s2
    assert s.undo() and snap() == s1
    assert s.undo() and snap() == before
    for _ in range(base_actions):
        assert s.undo()
    assert not s.undo()
    for _ in range(base_actions):
        assert s.redo()
    assert s.redo() and snap() == s1
    assert s.redo() and snap() == s2
    assert s.redo() and snap() == s3
    assert not s.redo()


def test_s10_values_restored():
    s = mk(A1="1", A2="=A1+1")
    s.delete_rows(1, 1)
    assert s.get("A1") == "#REF!"
    s.undo()
    assert s.get("A2") == 2 and s.raw("A2") == "=A1+1"


def test_s10_undo_cycle_state_and_clear():
    s = mk(A1="=B1", B1="3")
    s.set("B1", "=A1")
    assert s.get("A1") == "#CYCLE!"
    s.undo()
    assert s.get("A1") == 3
    s.set("A1", "")
    assert s.get("A1") is None
    s.undo()
    assert s.raw("A1") == "=B1"


def test_s10_snapshot_independent():
    s = mk(A1="1")
    s.set("A1", "2")
    s.undo()
    s.redo()
    s.undo()
    s.set("A1", "3")
    assert s.undo() and s.get("A1") == 1


# --------------------------------------------------------------- misc
def test_invalid_name():
    s = Sheet()
    for bad in ("a1", "A0", "AA1", "1A", ""):
        with pytest.raises(ValueError):
            s.set(bad, "1")
