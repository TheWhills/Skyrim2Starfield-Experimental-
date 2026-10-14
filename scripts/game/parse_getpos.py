"""Parse OCR'd console text for the most recent GetPos X/Y/Z values. Prints 'x y z' or 'fail'.
OCR quirks handled: 'Get Pos', '> >', number on the next line, '.' read as space ('-4 81'), and the OCR engine
listing a column of labels first and the column of numbers after (then the last three bare numbers are X, Y, Z)."""
import re
import sys

raw = open(sys.argv[1], encoding="utf-8-sig", errors="replace").read()
text = " ".join(raw.split())
vals = {}
for m in re.finditer(r"Pos\W*([XYZ])\W*>\s*>\s*(-?\s?\d+)(?:\s*[\.,]\s*|\s)(\d{1,3})\b", text, re.I):
    vals[m.group(1).upper()] = float(m.group(2).replace(" ", "") + "." + m.group(3))
if len(vals) < 3 and len(re.findall(r"Get\s?Pos", raw, re.I)) >= 3:
    bare = []
    for line in raw.splitlines():
        m = re.fullmatch(r"\s*(-?\d+)\s*[\.,\s]\s*(\d{1,3})\s*", line)
        if m:
            bare.append(float(m.group(1) + "." + m.group(2)))
    if len(bare) >= 3:
        vals = dict(zip("XYZ", bare[-3:]))
print(" ".join(f"{vals[k]:.2f}" for k in "XYZ") if len(vals) == 3 else "fail")
