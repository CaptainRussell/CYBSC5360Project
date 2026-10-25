"""Guard: the eight first-look checks are frozen for the Project 2 proof of function.

Checks C1-C7 and F1, their scoring, and the file-type sniffing were written for
Project 1 and committed on 2026-10-20 (b38fec5), before Project 2 was examined.
Project 2 is a fair, held-out test only while that code is unchanged. If this
test fails, the checks were edited: either undo the edit, or report every result
produced after it as a post-hoc (tuned) result, separately from the frozen run.
"""

import ast
import hashlib
import os
import unittest

ADS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ads")
FUNCS = ["_prepare", "c1", "c2", "c3", "c4", "c5", "c6", "c7", "f1", "run", "_add", "leads"]
TOP = ["_noise_reason", "_password_token", "_rar4_members"]
CONSTS = ["RULES", "STRONG", "PHRASE", "NAME_TOKEN", "MAX_READ", "JAVA_LIKE"]
FROZEN_CHECKS = "b49115686d7888551ece6443dc42de707dc62d174cda97a229f0f491ee38780a"
FROZEN_SNIFF = "15a50098f6d1524c7bb31614f118f753e30fc8f08d4544647ae3080970952762"


def check_segments(src):
    tree, out = ast.parse(src), {}
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "Triage":
            for f in node.body:
                if isinstance(f, ast.FunctionDef) and f.name in FUNCS:
                    out["Triage." + f.name] = ast.get_source_segment(src, f)
        elif isinstance(node, ast.FunctionDef) and node.name in TOP:
            out[node.name] = ast.get_source_segment(src, node)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                names = [t.id] if isinstance(t, ast.Name) else \
                    [e.id for e in getattr(t, "elts", []) if isinstance(e, ast.Name)]
                if any(n in CONSTS for n in names):
                    out["=" + ",".join(names)] = ast.get_source_segment(src, node)
    return out


class TestChecksFrozenForProjectTwo(unittest.TestCase):
    def test_check_code_unchanged_since_project_one(self):
        with open(os.path.join(ADS, "triage.py"), encoding="utf-8") as fh:
            seg = check_segments(fh.read())
        self.assertEqual(len(seg), 21)
        h = hashlib.sha256("\n\n".join(seg[k] for k in sorted(seg)).encode()).hexdigest()
        self.assertEqual(h, FROZEN_CHECKS, "first-look checks changed after the Project 2 freeze (see docstring)")

    def test_file_type_sniffing_unchanged(self):
        # Text mode, so a Windows checkout with CRLF line endings hashes the same as the repository.
        with open(os.path.join(ADS, "sniff.py"), encoding="utf-8") as fh:
            self.assertEqual(hashlib.sha256(fh.read().encode("utf-8")).hexdigest(), FROZEN_SNIFF)


if __name__ == "__main__":
    unittest.main()
