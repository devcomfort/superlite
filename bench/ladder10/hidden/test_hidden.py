"""Hidden behavioral tests for the ladder10 mini spreadsheet spec.

Tests are named test_sNN_<what>, where NN is the spec step.
"""
from solution import Sheet

DIV0 = "#DIV/0!"
VALUE = "#VALUE!"
REF = "#REF!"
CYCLE = "#CYCLE!"


def mk(**cells):
    """Build a sheet from keyword cells, e.g. mk(A1="1", B1="=A1+1")."""
    sh = Sheet()
    for name, raw in cells.items():
        sh.set(name, raw)
    return sh


def put(sh, mapping):
    for name, raw in mapping.items():
        sh.set(name, raw)


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_float(v):
    return isinstance(v, float)


def snap(sh):
    """Full observable state over A1:G16 (raw and value of every cell)."""
    out = {}
    for col in "ABCDEFG":
        for row in range(1, 17):
            name = f"{col}{row}"
            out[name] = (sh.raw(name), sh.get(name))
    return out


# ----------------------------------------------------------------------
# Step 1: storage
# ----------------------------------------------------------------------

def test_s01_int_storage():
    sh = Sheet()
    sh.set("A1", "42")
    sh.set("B2", "-7")
    sh.set("C3", "007")
    sh.set("D4", "0")
    assert sh.get("A1") == 42 and is_int(sh.get("A1"))
    assert sh.get("B2") == -7 and is_int(sh.get("B2"))
    assert sh.get("C3") == 7 and is_int(sh.get("C3"))
    assert sh.get("D4") == 0 and is_int(sh.get("D4"))
    assert sh.raw("A1") == "42"
    assert sh.raw("B2") == "-7"
    assert sh.raw("C3") == "007"
    assert sh.raw("D4") == "0"


def test_s01_float_storage():
    sh = Sheet()
    sh.set("A1", "3.14")
    sh.set("A2", "-0.5")
    sh.set("A3", "10.0")
    sh.set("A4", "2.50")
    assert is_float(sh.get("A1")) and sh.get("A1") == 3.14
    assert is_float(sh.get("A2")) and sh.get("A2") == -0.5
    assert is_float(sh.get("A3")) and sh.get("A3") == 10.0
    assert is_float(sh.get("A4")) and sh.get("A4") == 2.5
    assert sh.raw("A3") == "10.0"
    assert sh.raw("A4") == "2.50"


def test_s01_text_storage():
    sh = Sheet()
    texts = ["hello", "hello world", "12abc", "1.", ".5", "1,5", "+3",
             "--1", "1e5", "-", "1 2", "A1"]
    for i, t in enumerate(texts, start=1):
        sh.set(f"A{i}", t)
    for i, t in enumerate(texts, start=1):
        v = sh.get(f"A{i}")
        assert isinstance(v, str), t
        assert v == t, t
        assert sh.raw(f"A{i}") == t, t


def test_s01_empty_and_clear():
    sh = Sheet()
    assert sh.get("A1") is None
    assert sh.raw("A1") == ""
    assert sh.get("Z999") is None
    assert sh.raw("Z999") == ""
    sh.set("A1", "5")
    sh.set("B1", "x")
    sh.set("A1", "")
    assert sh.get("A1") is None
    assert sh.raw("A1") == ""
    assert sh.get("B1") == "x"
    sh.set("B1", "")
    assert sh.get("B1") is None
    assert sh.raw("B1") == ""


def test_s01_overwrite_changes_type():
    sh = Sheet()
    sh.set("A1", "5")
    assert sh.get("A1") == 5 and is_int(sh.get("A1"))
    sh.set("A1", "five")
    assert sh.get("A1") == "five"
    sh.set("A1", "2.5")
    assert sh.get("A1") == 2.5 and is_float(sh.get("A1"))
    sh.set("A1", "")
    assert sh.get("A1") is None
    sh.set("A1", "9")
    assert sh.get("A1") == 9 and is_int(sh.get("A1"))
    assert sh.raw("A1") == "9"


def test_s01_cells_independent_and_formula_raw_kept():
    sh = Sheet()
    sh.set("A1", "1")
    sh.set("B1", "2")
    sh.set("A2", "x")
    sh.set("Z999", "last")
    sh.set("B12", "=  1 +  2")
    sh.set("C1", "=A1+B1")
    assert sh.raw("A1") == "1"
    assert sh.raw("B1") == "2"
    assert sh.raw("A2") == "x"
    assert sh.raw("Z999") == "last"
    assert sh.get("Z999") == "last"
    assert sh.raw("B12") == "=  1 +  2"
    assert sh.raw("C1") == "=A1+B1"
    assert sh.get("A1") == 1 and sh.get("B1") == 2
    assert sh.get("B2") is None and sh.raw("B2") == ""


# ----------------------------------------------------------------------
# Step 2: formulas
# ----------------------------------------------------------------------

def test_s02_spec_example():
    sh = Sheet()
    sh.set("A1", "2")
    sh.set("A2", "=A1*3+1")
    assert sh.get("A2") == 7
    assert is_int(sh.get("A2"))


def test_s02_precedence_and_associativity():
    sh = Sheet()
    cases = {
        "=2+3*4": 14,
        "=10-3-2": 5,
        "=100/10/5": 2.0,
        "=(2+3)*4": 20,
        "=2*3+4*5": 26,
        "=20-2*3": 14,
        "=8/4/2": 1.0,
        "=2*(3+4)*5": 70,
        "=1-(2-3)": 2,
        "=24/(4/2)": 12.0,
    }
    for i, (raw, want) in enumerate(cases.items(), start=1):
        sh.set(f"A{i}", raw)
    for i, (raw, want) in enumerate(cases.items(), start=1):
        assert sh.get(f"A{i}") == want, raw


def test_s02_int_float_typing():
    sh = Sheet()
    sh.set("A1", "1")
    sh.set("B1", "1.5")
    sh.set("C1", "=A1+B1")
    sh.set("C2", "=2+3")
    sh.set("C3", "=2.5+2.5")
    sh.set("C4", "=1*2.0")
    sh.set("C5", "=6/3")
    sh.set("C6", "=7/2")
    sh.set("C7", "=3-1")
    sh.set("C8", "=2-2.0")
    sh.set("C9", "=4*5")
    assert sh.get("C1") == 2.5 and is_float(sh.get("C1"))
    assert sh.get("C2") == 5 and is_int(sh.get("C2"))
    assert sh.get("C3") == 5.0 and is_float(sh.get("C3"))
    assert sh.get("C4") == 2.0 and is_float(sh.get("C4"))
    assert sh.get("C5") == 2.0 and is_float(sh.get("C5"))
    assert sh.get("C6") == 3.5
    assert sh.get("C7") == 2 and is_int(sh.get("C7"))
    assert sh.get("C8") == 0.0 and is_float(sh.get("C8"))
    assert sh.get("C9") == 20 and is_int(sh.get("C9"))


def test_s02_empty_reference_is_zero():
    sh = Sheet()
    sh.set("B1", "=A1+5")
    sh.set("B2", "=C1*3")
    sh.set("B3", "=A1-C1")
    sh.set("B4", "=A1/4")
    sh.set("B5", "=10-A1")
    assert sh.get("B1") == 5 and is_int(sh.get("B1"))
    assert sh.get("B2") == 0
    assert sh.get("B3") == 0
    assert sh.get("B4") == 0.0 and is_float(sh.get("B4"))
    assert sh.get("B5") == 10


def test_s02_unary_minus_and_parens():
    sh = Sheet()
    sh.set("A1", "5")
    sh.set("B1", "=-A1")
    sh.set("B2", "=-(2+3)*2")
    sh.set("B3", "=-A1+10")
    sh.set("B4", "=-3*2")
    sh.set("B5", "=-(1.5)")
    sh.set("B6", "=-2+5")
    sh.set("B7", "=((A1))")
    assert sh.get("B1") == -5 and is_int(sh.get("B1"))
    assert sh.get("B2") == -10
    assert sh.get("B3") == 5
    assert sh.get("B4") == -6
    assert sh.get("B5") == -1.5
    assert sh.get("B6") == 3
    assert sh.get("B7") == 5


def test_s02_whitespace_and_references():
    sh = Sheet()
    sh.set("A1", "4")
    sh.set("A2", "6")
    sh.set("B1", "=  A1 +  2 * ( 3 )  ")
    sh.set("B2", "=A1+A2*2")
    sh.set("B3", "=  7 ")
    sh.set("B4", "= ( A1 + A2 ) / 4 ")
    sh.set("B5", "=B1+B2*B3")
    assert sh.get("B1") == 10
    assert sh.get("B2") == 16
    assert sh.get("B3") == 7
    assert sh.get("B4") == 2.5
    assert sh.get("B5") == 10 + 16 * 7
    assert sh.raw("B1") == "=  A1 +  2 * ( 3 )  "


# ----------------------------------------------------------------------
# Step 3: error values
# ----------------------------------------------------------------------

def test_s03_division_by_zero():
    sh = Sheet()
    sh.set("B1", "0")
    sh.set("C1", "=1/0")
    sh.set("C2", "=0/0")
    sh.set("C3", "=5/(3-3)")
    sh.set("C4", "=A1/B1")
    sh.set("C5", "=1/0.0")
    sh.set("C6", "=4/D9")
    assert sh.get("C1") == DIV0
    assert sh.get("C2") == DIV0
    assert sh.get("C3") == DIV0
    assert sh.get("C4") == DIV0
    assert sh.get("C5") == DIV0
    assert sh.get("C6") == DIV0
    assert isinstance(sh.get("C1"), str)


def test_s03_text_in_arithmetic():
    sh = Sheet()
    sh.set("A1", "abc")
    sh.set("B1", "=A1+1")
    sh.set("B2", "=1*A1")
    sh.set("B3", "=A1/2")
    sh.set("B4", "=2/A1")
    sh.set("B5", "=3-A1")
    sh.set("B6", "=(A1)+(2*3)")
    for c in ["B1", "B2", "B3", "B4", "B5", "B6"]:
        assert sh.get(c) == VALUE, c


def test_s03_error_propagation_through_references():
    sh = Sheet()
    sh.set("A1", "=1/0")
    sh.set("B1", "=A1+1")
    sh.set("C1", "=B1*2")
    sh.set("D1", "=1+A1*B1")
    sh.set("E1", "=A1")
    sh.set("F1", "=0*A1")
    sh.set("G1", "=A1-A1")
    assert sh.get("A1") == DIV0
    assert sh.get("B1") == DIV0
    assert sh.get("C1") == DIV0
    assert sh.get("D1") == DIV0
    assert sh.get("E1") == DIV0
    assert sh.get("F1") == DIV0
    assert sh.get("G1") == DIV0


def test_s03_left_error_wins():
    sh = Sheet()
    sh.set("T1", "abc")
    sh.set("A1", "=1/0")        # #DIV/0!
    sh.set("B1", "=T1+1")       # #VALUE!
    sh.set("C1", "=A1+B1")
    sh.set("C2", "=B1+A1")
    sh.set("C3", "=A1*B1")
    sh.set("C4", "=B1-A1")
    sh.set("C5", "=A1/B1")
    sh.set("C6", "=B1/A1")
    sh.set("C7", "=B1/0")
    sh.set("C8", "=(1/0)+(T1+1)")
    sh.set("C9", "=(T1+1)+(1/0)")
    sh.set("D1", "=T1+A1")
    assert sh.get("C1") == DIV0
    assert sh.get("C2") == VALUE
    assert sh.get("C3") == DIV0
    assert sh.get("C4") == VALUE
    assert sh.get("C5") == DIV0
    assert sh.get("C6") == VALUE
    assert sh.get("C7") == VALUE
    assert sh.get("C8") == DIV0
    assert sh.get("C9") == VALUE
    assert sh.get("D1") == DIV0


def test_s03_unparsable_formulas():
    sh = Sheet()
    bad = ["=1+", "=(1+2", "=1 2", "=*3", "=2**3", "=A", "=1+@", "=()", "=1+2)"]
    for i, raw in enumerate(bad, start=1):
        sh.set(f"A{i}", raw)
    sh.set("B1", "=A1+1")
    for i, raw in enumerate(bad, start=1):
        assert sh.raw(f"A{i}") == raw
        assert sh.get(f"A{i}") == VALUE, raw
    assert sh.get("B1") == VALUE
    sh.set("C1", "=1+1")
    assert sh.get("C1") == 2


def test_s03_error_values_are_strings_and_neighbours_unaffected():
    sh = Sheet()
    sh.set("A1", "10")
    sh.set("A2", "=A1/0")
    sh.set("A3", "=A1*2")
    sh.set("A4", "=A3+A2")
    sh.set("A5", "=A3+A1")
    assert isinstance(sh.get("A2"), str)
    assert sh.get("A2") == DIV0
    assert sh.get("A3") == 20
    assert sh.get("A4") == DIV0
    assert sh.get("A5") == 30
    assert sh.raw("A2") == "=A1/0"


# ----------------------------------------------------------------------
# Step 4: recalculation
# ----------------------------------------------------------------------

def test_s04_basic_chain():
    sh = mk(A1="1", B1="=A1+1", C1="=B1*2", D1="=C1+A1")
    assert [sh.get(c) for c in ("B1", "C1", "D1")] == [2, 4, 5]
    sh.set("A1", "5")
    assert [sh.get(c) for c in ("B1", "C1", "D1")] == [6, 12, 17]


def test_s04_diamond():
    sh = mk(A1="2", B1="=A1+1", C1="=A1*2", D1="=B1+C1")
    assert sh.get("D1") == 7
    sh.set("A1", "10")
    assert sh.get("B1") == 11
    assert sh.get("C1") == 20
    assert sh.get("D1") == 31
    sh.set("C1", "0")
    assert sh.get("D1") == 11


def test_s04_dependent_defined_before_precedent():
    sh = Sheet()
    sh.set("B1", "=A1*10")
    assert sh.get("B1") == 0
    sh.set("A1", "4")
    assert sh.get("B1") == 40
    sh.set("A1", "")
    assert sh.get("B1") == 0
    sh.set("A1", "x")
    assert sh.get("B1") == VALUE
    sh.set("A1", "2.5")
    assert sh.get("B1") == 25.0


def test_s04_replacing_a_cell_kind():
    sh = mk(A1="3", B1="=A1+1", C1="=B1+1")
    assert sh.get("C1") == 5
    sh.set("B1", "100")
    assert sh.get("C1") == 101
    sh.set("B1", "=A1*2")
    assert sh.get("C1") == 7
    sh.set("B1", "text")
    assert sh.get("C1") == VALUE
    sh.set("B1", "")
    assert sh.get("C1") == 1
    sh.set("A1", "50")
    assert sh.get("C1") == 1


def test_s04_long_chain():
    sh = Sheet()
    sh.set("A1", "1")
    for i in range(2, 61):
        sh.set(f"A{i}", f"=A{i-1}+1")
    assert sh.get("A60") == 60
    sh.set("A1", "101")
    assert sh.get("A30") == 130
    assert sh.get("A60") == 160
    sh.set("A30", "0")
    assert sh.get("A31") == 1
    assert sh.get("A60") == 30
    assert sh.get("A29") == 129


def test_s04_error_recovery_and_fan_in():
    sh = mk(A1="0", B1="=10/A1", C1="=B1+1")
    assert sh.get("B1") == DIV0 and sh.get("C1") == DIV0
    sh.set("A1", "4")
    assert sh.get("B1") == 2.5
    assert sh.get("C1") == 3.5
    sh.set("A1", "0")
    assert sh.get("C1") == DIV0
    # fan-in over a column
    sh2 = Sheet()
    for i, v in enumerate([1, 2, 3, 4, 5], start=1):
        sh2.set(f"A{i}", str(v))
        sh2.set(f"B{i}", f"=A{i}*A{i}")
    sh2.set("C1", "=B1+B2+B3+B4+B5")
    assert sh2.get("C1") == 55
    sh2.set("A3", "10")
    assert sh2.get("B3") == 100
    assert sh2.get("C1") == 146


# ----------------------------------------------------------------------
# Step 5: functions
# ----------------------------------------------------------------------

def test_s05_spec_example_and_corner_order():
    sh = mk(A1="1", B1="2", A2="3", B2="4", A3="5", B3="6", C1="10")
    sh.set("D1", "=SUM(A1:B3, C1*2, 5)")
    assert sh.get("D1") == 21 + 20 + 5
    sh.set("D2", "=SUM(B3:A1)")
    sh.set("D3", "=SUM(A3:B1)")
    sh.set("D4", "=SUM(B1:A3)")
    assert sh.get("D2") == 21
    assert sh.get("D3") == 21
    assert sh.get("D4") == 21
    sh.set("D5", "=SUM(A1, 5)")
    assert sh.get("D5") == 6
    sh.set("A1", "100")
    assert sh.get("D1") == 120 + 20 + 5


def test_s05_empty_and_text_skipped_in_ranges():
    sh = mk(A1="1", A2="x", A4="=2+2", A5="2.5")  # A3 empty
    sh.set("B1", "=SUM(A1:A5)")
    sh.set("B2", "=COUNT(A1:A5)")
    sh.set("B3", "=MIN(A1:A5)")
    sh.set("B4", "=MAX(A1:A5)")
    sh.set("B5", "=AVG(A1:A5)")
    sh.set("B6", "=COUNT(A1:A5, 7, 2*3)")
    assert sh.get("B1") == 7.5
    assert sh.get("B2") == 3
    assert sh.get("B3") == 1
    assert sh.get("B4") == 4
    assert sh.get("B5") == 2.5
    assert sh.get("B6") == 5


def test_s05_functions_of_nothing():
    sh = mk(A2="text", A3="more text")
    sh.set("B1", "=SUM(A1:A3)")
    sh.set("B2", "=MIN(A1:A3)")
    sh.set("B3", "=MAX(A1:A3)")
    sh.set("B4", "=AVG(A1:A3)")
    sh.set("B5", "=COUNT(A1:A3)")
    sh.set("B6", "=AVG(A1:A3)+1")
    sh.set("B7", "=SUM(E1:F9)")
    assert sh.get("B1") == 0
    assert sh.get("B2") == 0
    assert sh.get("B3") == 0
    assert sh.get("B4") == DIV0
    assert sh.get("B5") == 0
    assert sh.get("B6") == DIV0
    assert sh.get("B7") == 0


def test_s05_result_types():
    sh = mk(A1="1", A2="2", A3="3")
    sh.set("B1", "=SUM(A1:A3)")
    sh.set("B2", "=MIN(A1:A3)")
    sh.set("B3", "=MAX(A1:A3)")
    sh.set("B4", "=AVG(A1:A3)")
    sh.set("B5", "=AVG(2,4)")
    sh.set("B6", "=AVG(1,2)")
    sh.set("B7", "=SUM(1,2.5)")
    sh.set("C1", "=SUM(1.5,1.5)")
    sh.set("C2", "=MAX(2.5,1)")
    sh.set("C3", "=MIN(2.5,3)")
    sh.set("C4", "=COUNT(A1:A3)")
    assert sh.get("B1") == 6 and is_int(sh.get("B1"))
    assert sh.get("B2") == 1 and is_int(sh.get("B2"))
    assert sh.get("B3") == 3 and is_int(sh.get("B3"))
    assert sh.get("B4") == 2.0 and is_float(sh.get("B4"))
    assert sh.get("B5") == 3.0 and is_float(sh.get("B5"))
    assert sh.get("B6") == 1.5
    assert sh.get("B7") == 3.5
    assert sh.get("C1") == 3.0 and is_float(sh.get("C1"))
    assert sh.get("C2") == 2.5
    assert sh.get("C3") == 2.5
    assert sh.get("C4") == 3 and is_int(sh.get("C4"))


def test_s05_error_ordering():
    sh = mk(A1="1", B1="=1/0", C1="x", B2="5")
    sh.set("A2", "=C1+1")         # #VALUE!
    # range A1:B2 row-major: A1, B1(DIV0), A2(VALUE), B2
    sh.set("E1", "=SUM(A1:B2)")
    sh.set("E2", "=MIN(A1:B2)")
    sh.set("E3", "=MAX(A1:B2)")
    sh.set("E4", "=AVG(A1:B2)")
    sh.set("E5", "=COUNT(A1:B2)")
    for c in ("E1", "E2", "E3", "E4", "E5"):
        assert sh.get(c) == DIV0, c
    # argument order
    sh.set("F1", "=SUM(A2, B1)")
    sh.set("F2", "=SUM(B1, A2)")
    sh.set("F3", "=SUM(A1:A2, B1)")
    sh.set("F4", "=SUM(B1, A1:A2)")
    sh.set("F5", "=SUM(5, 1/0, A2)")
    sh.set("F6", "=SUM(5, A2, 1/0)")
    sh.set("F7", "=AVG(B1:B2, A2)")
    assert sh.get("F1") == VALUE
    assert sh.get("F2") == DIV0
    assert sh.get("F3") == VALUE
    assert sh.get("F4") == DIV0
    assert sh.get("F5") == DIV0
    assert sh.get("F6") == VALUE
    assert sh.get("F7") == DIV0
    # a range that only has the errors in other order
    sh.set("G1", "=SUM(A2:B2)")   # A2 VALUE then B2 5
    sh.set("G2", "=SUM(B1:B2, A2)")
    assert sh.get("G1") == VALUE
    assert sh.get("G2") == DIV0


def test_s05_nesting_and_expressions():
    sh = mk(A1="3", A2="7", A3="5")
    cases = {
        "=1+MAX(A1:A3)*2": 15,
        "=SUM(MAX(A1:A3), MIN(A1:A3))": 10,
        "=MAX(SUM(A1:A2), A3)": 10,
        "=AVG(MAX(A1:A3), MIN(A1:A3), 5)": 5.0,
        "=SUM(A1:A3)/COUNT(A1:A3)": 5.0,
        "=-SUM(A1:A3)": -15,
        "=SUM(A1:A3, SUM(A1:A3))": 30,
        "=SUM( A1:A3 , 5 )": 20,
        "=(MAX(A1:A3)-MIN(A1:A3))*2": 8,
        "=MIN(MAX(A1:A2), MAX(A2:A3), 100)": 7,
    }
    for i, raw in enumerate(cases, start=1):
        sh.set(f"C{i}", raw)
    for i, (raw, want) in enumerate(cases.items(), start=1):
        assert sh.get(f"C{i}") == want, raw


def test_s05_ranges_recalculate_with_formula_cells():
    sh = Sheet()
    put(sh, {"A1": "1", "A2": "=A1*2", "A3": "=A2*2",
             "B1": "=SUM(A1:A3)", "B2": "=MAX(A1:A3)",
             "B3": "=COUNT(A1:A3)", "B4": "=MIN(A1:A3)"})
    assert [sh.get(c) for c in ("B1", "B2", "B3", "B4")] == [7, 4, 3, 1]
    sh.set("A1", "3")
    assert [sh.get(c) for c in ("B1", "B2", "B3", "B4")] == [21, 12, 3, 3]
    sh.set("A2", "")          # A3 becomes 0*... = 0
    assert [sh.get(c) for c in ("B1", "B2", "B3", "B4")] == [3, 3, 2, 0]
    sh.set("A2", "x")          # A3 = x*2 -> #VALUE!
    assert sh.get("A3") == VALUE
    assert sh.get("B1") == VALUE
    assert sh.get("B3") == VALUE
    sh.set("A3", "10")
    assert [sh.get(c) for c in ("B1", "B2", "B3", "B4")] == [13, 10, 2, 3]


# ----------------------------------------------------------------------
# Step 6: cycles
# ----------------------------------------------------------------------

def test_s06_self_reference_and_range_containing_itself():
    sh = Sheet()
    sh.set("A1", "=A1+1")
    sh.set("B1", "=B1")
    sh.set("C1", "5")
    sh.set("C2", "=SUM(C1:C3)")
    sh.set("D1", "=COUNT(C1:C3)")
    assert sh.get("A1") == CYCLE
    assert sh.get("B1") == CYCLE
    assert sh.get("C1") == 5
    assert sh.get("C2") == CYCLE
    assert sh.get("D1") == CYCLE      # depends on cycle cell C2 via range


def test_s06_cycle_and_propagation():
    sh = mk(A1="=B1", B1="=A1", C1="=A1+1", D1="=C1*2", E1="=5", F1="=1+E1")
    assert sh.get("A1") == CYCLE
    assert sh.get("B1") == CYCLE
    assert sh.get("C1") == CYCLE
    assert sh.get("D1") == CYCLE
    assert sh.get("E1") == 5
    assert sh.get("F1") == 6


def test_s06_breaking_and_recreating_cycle():
    sh = mk(A1="=B1", B1="=A1", C1="=A1+1", D1="=C1*2")
    assert sh.get("D1") == CYCLE
    sh.set("B1", "7")
    assert sh.get("A1") == 7
    assert sh.get("B1") == 7
    assert sh.get("C1") == 8
    assert sh.get("D1") == 16
    # now a longer cycle A1 -> B1 -> D1 -> C1 -> A1
    sh.set("B1", "=D1")
    for c in ("A1", "B1", "C1", "D1"):
        assert sh.get(c) == CYCLE, c
    sh.set("C1", "3")
    assert sh.get("D1") == 6
    assert sh.get("B1") == 6
    assert sh.get("A1") == 6
    assert sh.get("C1") == 3
    # break by clearing instead
    sh.set("C1", "=A1+1")
    assert sh.get("A1") == CYCLE
    sh.set("A1", "")
    assert sh.get("C1") == 1
    assert sh.get("D1") == 2
    assert sh.get("B1") == 2


def test_s06_cycle_through_range_leaves_other_cells_alone():
    sh = mk(A1="=SUM(B1:B3)", B1="5", B2="=A1*2", B3="7",
            C1="=A1+1", D1="=B1+B3")
    assert sh.get("A1") == CYCLE
    assert sh.get("B2") == CYCLE
    assert sh.get("C1") == CYCLE
    assert sh.get("B1") == 5
    assert sh.get("B3") == 7
    assert sh.get("D1") == 12
    sh.set("B2", "10")
    assert sh.get("A1") == 22
    assert sh.get("B2") == 10
    assert sh.get("C1") == 23
    assert sh.get("D1") == 12


def test_s06_cycle_vs_other_errors_left_wins():
    sh = Sheet()
    put(sh, {"A1": "=B1+1", "B1": "=A1/0"})
    put(sh, {"C1": "=1/0+A1", "D1": "=A1+1/0",
             "E1": "=SUM(A1, 1/0)", "F1": "=SUM(1/0, A1)"})
    assert sh.get("A1") == CYCLE      # part of the cycle, whatever it computes
    assert sh.get("B1") == CYCLE
    assert sh.get("C1") == DIV0
    assert sh.get("D1") == CYCLE
    assert sh.get("E1") == CYCLE
    assert sh.get("F1") == DIV0
    sh.set("B1", "4")
    assert sh.get("A1") == 5
    assert sh.get("C1") == DIV0
    assert sh.get("D1") == DIV0
    assert sh.get("E1") == DIV0


def test_s06_independent_cycles_broken_separately():
    sh = mk(A1="=B1", B1="=C1", C1="=A1", E1="=E1", F1="=A1+E1", G1="=3")
    for c in ("A1", "B1", "C1", "E1", "F1"):
        assert sh.get(c) == CYCLE, c
    assert sh.get("G1") == 3
    sh.set("C1", "2")
    assert sh.get("A1") == 2
    assert sh.get("B1") == 2
    assert sh.get("E1") == CYCLE
    assert sh.get("F1") == CYCLE
    sh.set("E1", "3")
    assert sh.get("F1") == 5
    sh.set("A1", "=F1")        # A1 -> F1 -> A1 : new cycle through a tail cell
    assert sh.get("A1") == CYCLE
    assert sh.get("F1") == CYCLE
    assert sh.get("B1") == 2
    assert sh.get("G1") == 3


# ----------------------------------------------------------------------
# Step 7: absolute references and copy
# ----------------------------------------------------------------------

def test_s07_dollar_refs_evaluate_like_plain():
    sh = mk(A1="10", A2="1", A3="2")
    sh.set("B1", "=$A$1+A$1+$A1+A1")
    sh.set("B2", "=$A$1*2")
    sh.set("B3", "=SUM($A$1:$A$3)")
    sh.set("B4", "=SUM($A1:A$3)+SUM(A$2:$A3)")
    assert sh.get("B1") == 40
    assert sh.get("B2") == 20
    assert sh.get("B3") == 13
    assert sh.get("B4") == 13 + 3
    assert sh.raw("B1") == "=$A$1+A$1+$A1+A1"
    sh.set("A1", "1")
    assert sh.get("B1") == 4


def test_s07_spec_example():
    sh = mk(A1="1", B1="=A1+$A$1")
    sh.copy("B1", "C2")
    assert sh.raw("C2") == "=B2+$A$1"
    assert sh.get("C2") == 1          # B2 empty = 0, plus A1 = 1
    sh.set("B2", "5")
    assert sh.get("C2") == 6
    assert sh.raw("B1") == "=A1+$A$1"
    assert sh.get("B1") == 2


    # mixed references shifting under copy
    sh = mk(A1="1", C3="=$A1+A$1+$A$1+A1")
    sh.copy("C3", "D5")        # +1 column, +2 rows
    assert sh.raw("D5") == "=$A3+B$1+$A$1+B3"
    sh.copy("C3", "C4")        # +1 row only
    assert sh.raw("C4") == "=$A2+A$1+$A$1+A2"
    sh.copy("C3", "A3")        # -2 columns: A$1 and A1 fall off
    assert sh.raw("A3") == "=$A1+#REF!+$A$1+#REF!"
    assert sh.get("A3") == REF
    assert sh.raw("C3") == "=$A1+A$1+$A$1+A1"


def test_s07_copy_preserves_text_outside_references():
    sh = Sheet()
    sh.set("E5", "=  SUM( A1:B2 ,  $C1*1.50 )  +  2")
    sh.copy("E5", "F7")
    assert sh.raw("F7") == "=  SUM( B3:C4 ,  $C3*1.50 )  +  2"
    sh.set("A1", "=MAX(A2:B3)*2.0/ 4")
    sh.copy("A1", "B2")
    assert sh.raw("B2") == "=MAX(B3:C4)*2.0/ 4"
    sh.set("A9", "=SUM($A$1:A3)")
    sh.copy("A9", "A8")
    assert sh.raw("A8") == "=SUM($A$1:A2)"
    sh.copy("A9", "C9")
    assert sh.raw("C9") == "=SUM($A$1:C3)"


def test_s07_out_of_bounds_becomes_ref():
    sh = Sheet()
    sh.set("B2", "=A1")
    sh.copy("B2", "A2")                   # column 0
    assert sh.raw("A2") == "=#REF!"
    assert sh.get("A2") == REF
    sh.set("B3", "=B2")
    sh.copy("B3", "B1")                   # -2 rows: B2 -> B0
    assert sh.raw("B1") == "=#REF!"
    assert sh.get("B1") == REF
    sh.set("A5", "=Y1+1")
    sh.copy("A5", "C5")                   # Y + 2 columns > Z
    assert sh.raw("C5") == "=#REF!+1"
    assert sh.get("C5") == REF
    sh.set("A6", "=Z1")
    sh.copy("A6", "B6")
    assert sh.raw("B6") == "=#REF!"
    sh.set("B7", "=A1+B1")
    sh.copy("B7", "B6")                   # -1 row: row 0 for both
    assert sh.raw("B6") == "=#REF!+#REF!"
    assert sh.get("B6") == REF


    # ranges
    sh.set("C3", "=SUM(A1:B2)")
    sh.copy("C3", "C2")                   # A1 -> A0: whole range is #REF!
    assert sh.raw("C2") == "=SUM(#REF!)"
    assert sh.get("C2") == REF
    sh.set("D4", "=SUM(B2:C3)")
    sh.copy("D4", "B4")                   # one corner falls off, other ok
    assert sh.raw("B4") == "=SUM(#REF!)"
    assert sh.get("B4") == REF
    sh.copy("D4", "C4")                   # both corners fine
    assert sh.raw("C4") == "=SUM(A2:B3)"
    sh.set("C4", "=1+MAX(A1:B2, 3)")
    sh.copy("C4", "C3")
    assert sh.raw("C3") == "=1+MAX(#REF!, 3)"
    assert sh.get("C3") == REF


def test_s07_copy_non_formulas_and_empty():
    sh = mk(A1="5", A2="hello", A3="2.50", B3="old", B4="=A1+1")
    sh.copy("A1", "C1")
    sh.copy("A2", "C2")
    sh.copy("A3", "C3")
    assert sh.raw("C1") == "5" and sh.get("C1") == 5
    assert sh.raw("C2") == "hello" and sh.get("C2") == "hello"
    assert sh.raw("C3") == "2.50" and sh.get("C3") == 2.5
    sh.copy("A1", "B3")                   # overwrite
    assert sh.get("B3") == 5
    sh.copy("Z9", "B3")                   # copying an empty cell clears
    assert sh.raw("B3") == ""
    assert sh.get("B3") is None
    sh.copy("B4", "B5")
    assert sh.raw("B5") == "=A2+1"        # A2 is text
    assert sh.get("B5") == VALUE


def test_s07_fill_down_and_running_total():
    sh = Sheet()
    for i in range(1, 5):
        sh.set(f"A{i}", str(i))
    sh.set("D1", "10")
    sh.set("B1", "=A1*$D$1")
    for i in range(2, 5):
        sh.copy("B1", f"B{i}")
    assert [sh.raw(f"B{i}") for i in range(1, 5)] == [
        "=A1*$D$1", "=A2*$D$1", "=A3*$D$1", "=A4*$D$1"]
    assert [sh.get(f"B{i}") for i in range(1, 5)] == [10, 20, 30, 40]
    sh.set("D1", "2")
    assert [sh.get(f"B{i}") for i in range(1, 5)] == [2, 4, 6, 8]
    sh.set("C1", "=A1")
    sh.set("C2", "=C1+A2")
    sh.copy("C2", "C3")
    sh.copy("C2", "C4")
    assert sh.raw("C3") == "=C2+A3"
    assert sh.raw("C4") == "=C3+A4"
    assert [sh.get(f"C{i}") for i in range(1, 5)] == [1, 3, 6, 10]
    sh.set("A1", "11")
    assert [sh.get(f"C{i}") for i in range(1, 5)] == [11, 13, 16, 20]


def test_s07_copy_creating_a_cycle():
    sh = mk(A1="=$B$2")
    sh.copy("A1", "B2")
    assert sh.raw("B2") == "=$B$2"
    assert sh.get("B2") == CYCLE
    assert sh.get("A1") == CYCLE
    assert sh.raw("A1") == "=$B$2"
    sh.set("B2", "4")
    assert sh.get("A1") == 4


# ----------------------------------------------------------------------
# Step 8: insert rows
# ----------------------------------------------------------------------

def test_s08_spec_example():
    sh = mk(A1="1", A2="2", A3="=SUM(A1:A2)")
    sh.insert_rows(2, 1)
    assert sh.raw("A4") == "=SUM(A1:A3)"
    assert sh.get("A4") == 3
    assert sh.raw("A1") == "1"
    assert sh.get("A2") is None and sh.raw("A2") == ""
    assert sh.raw("A3") == "2"
    assert sh.get("A3") == 2
    assert sh.get("A5") is None


def test_s08_absolute_and_relative_refs_all_shift():
    sh = mk(A1="1", A2="3", A3="7",
            B1="=$A$3+A3+A$3+$A3", B2="=A1+A2+A3", C1="=A1+A3")
    assert sh.get("B1") == 28
    sh.insert_rows(3, 2)
    assert sh.raw("B1") == "=$A$5+A5+A$5+$A5"
    assert sh.raw("B2") == "=A1+A2+A5"
    assert sh.raw("C1") == "=A1+A5"
    assert sh.raw("A5") == "7"
    assert sh.get("A3") is None and sh.get("A4") is None
    assert sh.get("B1") == 28
    assert sh.get("B2") == 11
    assert sh.get("C1") == 8
    sh.set("A3", "100")                 # new cell in the gap, not referenced
    assert sh.get("B1") == 28
    assert sh.get("B2") == 11


def test_s08_range_endpoints_cases():
    sh = mk(C1="=SUM(A1:A3)", C2="=SUM(A1:A8)", C3="=SUM(A5:A8)",
            C4="=SUM(A6:A9)")
    sh.insert_rows(5, 2)
    assert sh.raw("C1") == "=SUM(A1:A3)"       # entirely above
    assert sh.raw("C2") == "=SUM(A1:A10)"      # spans the insert point
    assert sh.raw("C3") == "=SUM(A7:A10)"      # top == at: whole range moves
    assert sh.raw("C4") == "=SUM(A8:A11)"      # entirely below
    sh2 = mk(C1="=SUM(A1:A3)", C2="=SUM(A2:A3)", D1="=SUM(A3:A4)")
    sh2.insert_rows(3, 2)
    assert sh2.raw("C1") == "=SUM(A1:A5)"      # bottom == at: grows
    assert sh2.raw("C2") == "=SUM(A2:A5)"
    assert sh2.raw("D1") == "=SUM(A5:A6)"      # top == at: moves


def test_s08_grown_range_picks_up_new_cells():
    sh = mk(A1="1", A2="2", A3="=SUM(A1:A2)")
    sh.insert_rows(2, 2)
    assert sh.raw("A5") == "=SUM(A1:A4)"
    assert sh.get("A5") == 3
    sh.set("A2", "10")
    sh.set("A3", "100")
    assert sh.get("A5") == 113
    sh2 = mk(A1="1", A2="2", A3="=SUM(A1:A2)")
    sh2.insert_rows(1, 1)
    assert sh2.get("A1") is None
    assert sh2.raw("A4") == "=SUM(A2:A3)"
    assert sh2.get("A4") == 3
    sh2.set("A1", "50")                       # outside the shifted range
    assert sh2.get("A4") == 3


def test_s08_contents_move_with_cells():
    sh = Sheet()
    put(sh, {"A1": "1", "A2": "5", "B2": "=A2*2", "C1": "=B2+A1",
             "A3": "txt", "A4": "1.5", "B4": "=A4+A2"})
    sh.insert_rows(2, 3)
    assert sh.get("A2") is None and sh.get("A3") is None
    assert sh.get("A4") is None and sh.get("B2") is None
    assert sh.raw("A5") == "5"
    assert sh.raw("B5") == "=A5*2"
    assert sh.get("B5") == 10
    assert sh.raw("C1") == "=B5+A1"
    assert sh.get("C1") == 11
    assert sh.raw("A6") == "txt" and sh.get("A6") == "txt"
    assert sh.get("A7") == 1.5
    assert sh.raw("B7") == "=A7+A5"
    assert sh.get("B7") == 6.5
    sh.set("A5", "6")
    assert sh.get("C1") == 13


def test_s08_repeated_inserts_and_far_insert():
    sh = mk(A1="1", A2="=A1+1", A3="=SUM(A1:A2)")
    sh.insert_rows(2, 1)
    assert sh.raw("A3") == "=A1+1"
    assert sh.raw("A4") == "=SUM(A1:A3)"
    assert sh.get("A3") == 2
    assert sh.get("A4") == 3
    sh.insert_rows(4, 2)
    assert sh.raw("A6") == "=SUM(A1:A3)"      # bottom 3 < 4: no growth
    assert sh.get("A6") == 3
    sh.insert_rows(1, 1)
    assert sh.raw("A4") == "=A2+1"
    assert sh.raw("A7") == "=SUM(A2:A4)"
    assert sh.get("A4") == 2
    assert sh.get("A7") == 3
    sh.insert_rows(50, 3)                     # beyond all data: nothing moves
    assert sh.raw("A7") == "=SUM(A2:A4)"
    assert sh.raw("A4") == "=A2+1"
    assert sh.get("A7") == 3


# ----------------------------------------------------------------------
# Step 9: delete rows
# ----------------------------------------------------------------------

def test_s09_spec_example():
    sh = Sheet()
    for i in range(1, 6):
        sh.set(f"A{i}", str(i))
    sh.set("B1", "=SUM(A1:A5)")
    sh.delete_rows(2, 2)
    assert sh.raw("B1") == "=SUM(A1:A3)"
    assert sh.get("B1") == 1 + 4 + 5
    assert [sh.get(f"A{i}") for i in range(1, 6)] == [1, 4, 5, None, None]


def test_s09_deleted_refs_become_ref_and_below_shifts():
    sh = Sheet()
    for i in range(1, 6):
        sh.set(f"A{i}", str(i))
    put(sh, {"B1": "=A1+A2+A5", "C1": "=A3+1", "D1": "=A1+A3+A4+A5",
             "E1": "=$A$5+A$5+$A5", "F1": "=A2*10"})
    sh.delete_rows(3, 2)
    assert sh.raw("B1") == "=A1+A2+A3"
    assert sh.get("B1") == 1 + 2 + 5
    assert sh.raw("C1") == "=#REF!+1"
    assert sh.get("C1") == REF
    assert sh.raw("D1") == "=A1+#REF!+#REF!+A3"
    assert sh.get("D1") == REF
    assert sh.raw("E1") == "=$A$3+A$3+$A3"
    assert sh.get("E1") == 15
    assert sh.raw("F1") == "=A2*10"
    assert sh.get("F1") == 20


def test_s09_range_shrink_cases():
    # data A1..A9 = 1..9, formula far below so it is never deleted
    cases = [
        # (range, at, n, expected range text or None for #REF!, expected sum)
        ("A1:A5", 2, 2, "A1:A3", 1 + 4 + 5),
        ("A2:A5", 1, 2, "A1:A3", 3 + 4 + 5),
        ("A1:A4", 3, 5, "A1:A2", 3),
        ("A3:A6", 1, 2, "A1:A4", 3 + 4 + 5 + 6),
        ("A1:A3", 5, 2, "A1:A3", 6),
        ("A1:A9", 4, 3, "A1:A6", 1 + 2 + 3 + 7 + 8 + 9),
        ("A4:A8", 2, 3, "A2:A5", 5 + 6 + 7 + 8),
        ("A2:A8", 5, 2, "A2:A6", 2 + 3 + 4 + 7 + 8),
        ("A2:A4", 2, 3, None, None),
        ("A3:A4", 1, 5, None, None),
    ]
    for rng, at, n, want_rng, want_sum in cases:
        sh = Sheet()
        for i in range(1, 10):
            sh.set(f"A{i}", str(i))
        sh.set("C20", f"=SUM({rng})")
        sh.delete_rows(at, n)
        new = f"C{20 - n}"
        if want_rng is None:
            assert sh.raw(new) == "=SUM(#REF!)", (rng, at, n)
            assert sh.get(new) == REF, (rng, at, n)
        else:
            assert sh.raw(new) == f"=SUM({want_rng})", (rng, at, n)
            assert sh.get(new) == want_sum, (rng, at, n)
        assert sh.get("C20") is None


def test_s09_cells_vanish_and_rows_move_up():
    sh = Sheet()
    put(sh, {"A1": "one", "A2": "two", "A3": "three", "A4": "four",
             "A5": "5", "A6": "6", "B3": "=A3+1", "B5": "=A5+A1",
             "B6": "=A6*2"})
    sh.delete_rows(2, 2)
    assert sh.get("A1") == "one"
    assert sh.get("A2") == "four"
    assert sh.get("A3") == 5
    assert sh.get("A4") == 6
    assert sh.get("A5") is None and sh.raw("A5") == ""
    assert sh.get("A6") is None
    assert sh.raw("B3") == "=A3+A1"       # old B5 moved up, A5 -> A3
    assert sh.get("B3") == VALUE          # A1 is text
    assert sh.raw("B4") == "=A4*2"
    assert sh.get("B4") == 12
    assert sh.get("B5") is None
    assert sh.get("B6") is None


def test_s09_nested_function_ranges():
    sh = Sheet()
    for i in range(1, 7):
        sh.set(f"A{i}", str(i))
    sh.set("B1", "=MAX(1,SUM(A1:A6)*2)")
    sh.set("C1", "=AVG(A2:A5)+MIN(A1:A6)")
    sh.set("D1", "=SUM(A3:A4)")
    sh.set("E1", "=COUNT(A5:A6)*10")
    sh.delete_rows(3, 2)
    assert sh.raw("B1") == "=MAX(1,SUM(A1:A4)*2)"
    assert sh.get("B1") == (1 + 2 + 5 + 6) * 2
    assert sh.raw("C1") == "=AVG(A2:A3)+MIN(A1:A4)"
    assert sh.get("C1") == 3.5 + 1
    assert sh.raw("D1") == "=SUM(#REF!)"
    assert sh.get("D1") == REF
    assert sh.raw("E1") == "=COUNT(A3:A4)*10"
    assert sh.get("E1") == 20


def test_s09_cycle_broken_or_kept_by_deletion():
    # 3-cycle; deleting a member removes the cycle (refs become #REF!)
    sh = mk(A1="=A2", A2="=A3", A3="=A1")
    assert sh.get("A1") == CYCLE and sh.get("A3") == CYCLE
    sh.delete_rows(2, 1)
    assert sh.raw("A1") == "=#REF!"
    assert sh.raw("A2") == "=A1"
    assert sh.get("A1") == REF
    assert sh.get("A2") == REF
    # cycle through a range is broken when the cycling cell is deleted
    sh = mk(A1="=SUM(B1:B3)", B1="2", B2="3", B3="=A1+1", C1="=A1*2")
    assert sh.get("A1") == CYCLE and sh.get("C1") == CYCLE
    sh.delete_rows(3, 1)
    assert sh.raw("A1") == "=SUM(B1:B2)"
    assert sh.get("A1") == 5
    assert sh.get("C1") == 10
    # a cycle that survives deletion still reports CYCLE
    sh = mk(A1="=A5", A5="=A1", B1="=A1+1", A3="9")
    sh.delete_rows(2, 2)
    assert sh.raw("A1") == "=A3"
    assert sh.raw("A3") == "=A1"
    assert sh.get("A1") == CYCLE and sh.get("A3") == CYCLE
    assert sh.get("B1") == CYCLE


def test_s09_insert_then_delete_round_trip():
    sh = mk(A1="1", A2="2", A3="=SUM(A1:A2)", B1="=A3*2")
    sh.insert_rows(2, 1)
    assert sh.raw("A4") == "=SUM(A1:A3)"
    assert sh.raw("B1") == "=A4*2"
    sh.set("A2", "40")
    assert sh.get("A4") == 43
    assert sh.get("B1") == 86
    sh.delete_rows(2, 1)                       # removes the inserted row
    assert sh.raw("A3") == "=SUM(A1:A2)"
    assert sh.raw("B1") == "=A3*2"
    assert sh.get("A3") == 3
    assert sh.get("B1") == 6
    sh.delete_rows(3, 1)                       # removes the SUM cell itself
    assert sh.get("A3") is None
    assert sh.raw("B1") == "=#REF!*2"
    assert sh.get("B1") == REF
    assert sh.get("A2") == 2


# ----------------------------------------------------------------------
# Step 10: undo and redo
# ----------------------------------------------------------------------

def test_s10_empty_history_and_basic_set_undo():
    sh = Sheet()
    assert sh.undo() is False
    assert sh.redo() is False
    sh.set("A1", "1")
    sh.set("A1", "2")
    assert sh.undo() is True
    assert sh.get("A1") == 1 and sh.raw("A1") == "1"
    assert sh.undo() is True
    assert sh.get("A1") is None and sh.raw("A1") == ""
    assert sh.undo() is False
    assert sh.redo() is True
    assert sh.get("A1") == 1
    assert sh.redo() is True
    assert sh.get("A1") == 2
    assert sh.redo() is False
    assert sh.get("A1") == 2


def test_s10_undo_redo_recompute_dependents():
    sh = mk(A1="2", B1="=A1*3", C1="=B1+A1")
    assert sh.get("C1") == 8
    sh.set("A1", "5")
    assert sh.get("B1") == 15 and sh.get("C1") == 20
    assert sh.undo() is True
    assert sh.raw("A1") == "2"
    assert sh.get("B1") == 6 and sh.get("C1") == 8
    assert sh.redo() is True
    assert sh.get("B1") == 15 and sh.get("C1") == 20
    assert sh.redo() is False
    sh.set("B1", "text")
    assert sh.get("C1") == VALUE
    assert sh.undo() is True
    assert sh.raw("B1") == "=A1*3"
    assert sh.get("C1") == 20
    assert sh.undo() is True
    assert sh.get("A1") == 2 and sh.get("C1") == 8


def test_s10_undo_copy():
    sh = mk(A1="1", B1="=A1+$A$1", C2="old")
    before = snap(sh)
    sh.copy("B1", "C2")
    assert sh.raw("C2") == "=B2+$A$1"
    assert sh.get("C2") == 1
    assert sh.undo() is True
    assert snap(sh) == before
    assert sh.get("C2") == "old"
    sh.copy("B1", "D5")                     # onto an empty cell
    assert sh.raw("D5") == "=C5+$A$1"
    assert sh.undo() is True
    assert sh.get("D5") is None and sh.raw("D5") == ""
    assert snap(sh) == before
    assert sh.redo() is True
    assert sh.raw("D5") == "=C5+$A$1"
    assert sh.redo() is False
    assert sh.undo() is True                # the second copy
    assert sh.undo() is True                # the earlier set of C2
    assert sh.get("C2") is None


def test_s10_undo_insert_and_delete_restore_raws_and_values():
    sh = Sheet()
    for i in range(1, 6):
        sh.set(f"A{i}", str(i))
    put(sh, {"B1": "=SUM(A1:A5)", "B2": "=A3*2", "B5": "=A2+A4", "C1": "=B1+B2"})
    s0 = snap(sh)
    sh.insert_rows(2, 2)
    s1 = snap(sh)
    assert s1 != s0
    assert sh.raw("B1") == "=SUM(A1:A7)"
    sh.delete_rows(3, 4)
    s2 = snap(sh)
    assert s2 != s1
    assert sh.raw("B1") == "=SUM(A1:A3)"
    assert sh.get("B1") == 1 + 5
    assert sh.undo() is True
    assert snap(sh) == s1
    assert sh.undo() is True
    assert snap(sh) == s0
    assert sh.get("B1") == 15 and sh.get("C1") == 21
    assert sh.redo() is True
    assert snap(sh) == s1
    assert sh.redo() is True
    assert snap(sh) == s2
    assert sh.redo() is False


def test_s10_new_action_clears_redo():
    sh = Sheet()
    sh.set("A1", "1")
    sh.set("A1", "2")
    assert sh.undo() is True
    assert sh.get("A1") == 1
    sh.set("B1", "9")                       # new action: redo history gone
    assert sh.redo() is False
    assert sh.get("A1") == 1 and sh.get("B1") == 9
    assert sh.undo() is True
    assert sh.get("B1") is None
    assert sh.undo() is True
    assert sh.get("A1") is None
    assert sh.undo() is False
    assert sh.redo() is True
    assert sh.get("A1") == 1
    assert sh.redo() is True
    assert sh.get("B1") == 9
    assert sh.redo() is False
    # other action kinds also clear redo
    sh2 = Sheet()
    sh2.set("A1", "1")
    assert sh2.undo() is True
    sh2.insert_rows(1, 1)
    assert sh2.redo() is False
    assert sh2.get("A1") is None and sh2.get("A2") is None
    sh3 = mk(A1="1", A2="2")
    sh3.set("A3", "3")
    assert sh3.undo() is True
    sh3.copy("A1", "B1")
    assert sh3.redo() is False
    assert sh3.get("A3") is None
    assert sh3.get("B1") == 1
    sh4 = mk(A1="1", A2="2")
    sh4.set("A3", "3")
    assert sh4.undo() is True
    sh4.delete_rows(1, 1)
    assert sh4.redo() is False
    assert sh4.get("A1") == 2


def test_s10_cycle_created_and_undone():
    sh = mk(A1="1", A2="=A1+1", A3="=A2*2")
    assert [sh.get(c) for c in ("A1", "A2", "A3")] == [1, 2, 4]
    sh.set("A1", "=A3")
    assert [sh.get(c) for c in ("A1", "A2", "A3")] == [CYCLE] * 3
    assert sh.undo() is True
    assert sh.raw("A1") == "1"
    assert [sh.get(c) for c in ("A1", "A2", "A3")] == [1, 2, 4]
    assert sh.redo() is True
    assert [sh.get(c) for c in ("A1", "A2", "A3")] == [CYCLE] * 3
    # break the cycle by deleting a row, then undo brings the cycle back
    sh.delete_rows(2, 1)
    assert sh.raw("A1") == "=A2"
    assert sh.raw("A2") == "=#REF!*2"
    assert sh.get("A1") == REF
    assert sh.get("A2") == REF
    assert sh.undo() is True
    assert sh.raw("A1") == "=A3"
    assert sh.raw("A2") == "=A1+1"
    assert sh.raw("A3") == "=A2*2"
    assert [sh.get(c) for c in ("A1", "A2", "A3")] == [CYCLE] * 3
    assert sh.undo() is True
    assert [sh.get(c) for c in ("A1", "A2", "A3")] == [1, 2, 4]


def test_s10_interleaved_history_full_roundtrip():
    sh = Sheet()
    states = [snap(sh)]
    actions = [
        lambda: sh.set("A1", "1"),
        lambda: sh.set("A2", "2"),
        lambda: sh.set("A3", "=SUM(A1:A2)"),
        lambda: sh.set("B1", "=A1+$A$3"),
        lambda: sh.copy("B1", "C2"),
        lambda: sh.insert_rows(2, 2),
        lambda: sh.set("A2", "10"),
        lambda: sh.delete_rows(1, 1),
        lambda: sh.set("D1", "=SUM(A1:C9)"),
    ]
    for act in actions:
        act()
        states.append(snap(sh))
    final = states[-1]
    assert sh.redo() is False
    # walk all the way back, checking every intermediate state
    for k in range(len(actions) - 1, -1, -1):
        assert sh.undo() is True
        assert snap(sh) == states[k], f"after undoing action {k}"
    assert sh.undo() is False
    # and all the way forward again
    for k in range(len(actions)):
        assert sh.redo() is True
        assert snap(sh) == states[k + 1], f"after redoing action {k}"
    assert sh.redo() is False
    assert snap(sh) == final
    # partial undo then a new action diverges the history
    assert sh.undo() is True
    assert sh.undo() is True
    sh.set("G1", "7")
    assert sh.redo() is False
    assert sh.get("G1") == 7
    assert sh.undo() is True
    assert snap(sh) == states[-3]
