"""Independent AST check (reproduction verifier): where do the `.defects` leakage-scan hits in
caver11/agent_c.py lie, and do the policy classes reach them?

Usage: python3 reports/v011/repro/ast_scan_hits.py [path]   (default caver11/agent_c.py)
Prints JSON. Read-only.
"""
import ast
import json
import re
import sys
from pathlib import Path

POLICY_CLASSES = ('_DiversityMixin', 'PopBayesUCB', 'PopDivBUCB')
SUSPECT_ATTRS = {'defects'}


def scope_map(tree):
    """Map every node to its chain of enclosing class/function names."""
    out = {}

    def walk(node, chain):
        for child in ast.iter_child_nodes(node):
            c = chain
            if isinstance(child, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                c = chain + [(type(child).__name__, child.name, child.lineno, child.end_lineno)]
            out[id(child)] = c
            walk(child, c)
    walk(tree, [])
    return out


def main(path='caver11/agent_c.py'):
    src = Path(path).read_text(encoding='utf-8')
    tree = ast.parse(src)
    scopes = scope_map(tree)
    classes = {n.name: n for n in tree.body if isinstance(n, ast.ClassDef)}
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in SUSPECT_ATTRS:
            chain = scopes.get(id(node), [])
            hits.append({'line': node.lineno, 'attr': node.attr,
                         'enclosing': [f'{k}:{n} (lines {a}-{b})' for k, n, a, b in chain],
                         'top_level_scope': chain[0][1] if chain else '<module>',
                         'inside_policy_class': bool(chain) and chain[0][1] in POLICY_CLASSES})
    # regex hits too (what the leakage scan matches), to confirm the same lines
    regex_lines = [i + 1 for i, l in enumerate(src.splitlines()) if re.search(r'\.defects\b', l)]
    # names referenced inside the policy classes (do they call module-level helpers that touch .defects?)
    module_funcs = {n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
    refs = {}
    for cname in POLICY_CLASSES:
        c = classes[cname]
        names = {n.id for n in ast.walk(c) if isinstance(n, ast.Name)}
        attrs = sorted({n.attr for n in ast.walk(c) if isinstance(n, ast.Attribute)})
        refs[cname] = {'lines': [c.lineno, c.end_lineno],
                       'bases': [ast.unparse(b) for b in c.bases],
                       'module_level_defs_referenced': sorted(names & module_funcs),
                       'suspect_attrs_used': sorted(set(attrs) & (SUSPECT_ATTRS | {'case', 'cases', 'table'})),
                       'attributes_used': attrs}
    res = {'file': path, 'ast_hits': hits, 'regex_hit_lines': regex_lines,
           'all_hits_outside_policy_classes': all(not h['inside_policy_class'] for h in hits),
           'policy_classes': refs}
    print(json.dumps(res, indent=1))
    return 0 if res['all_hits_outside_policy_classes'] else 1


if __name__ == '__main__':
    sys.exit(main(*sys.argv[1:]))
