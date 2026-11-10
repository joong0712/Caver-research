import os
S = os.path.dirname(os.path.abspath(__file__)) + '/chain_'  # inputs: chain_parents.txt (git rev-list --topo-order --parents 7aaa4a3), chain_dates.txt (git log --all --format='%h|%ci|%s')
par = {}
for l in open(S + 'parents.txt'):
    p = l.split()
    par[p[0][:7]] = [x[:7] for x in p[1:]]


def anc(a, b):
    st = [b]
    seen = set()
    while st:
        x = st.pop()
        if x == a:
            return True
        if x in seen:
            continue
        seen.add(x)
        st += par.get(x, [])
    return False


dates = {l.split('|')[0][:7]: l.split('|')[1] for l in open(S + 'dates.txt')}
pairs = [('021dfbd', '8bf9b8f'), ('8bf9b8f', '7ddeb23'), ('7ddeb23', 'c7b3c0d'), ('c7b3c0d', 'de59112'),
         ('de59112', 'ae948ef'), ('ae948ef', '7aaa4a3'),
         ('8bf9b8f', '7d023da'), ('7d023da', '6de2378'), ('7d023da', 'b630363'), ('7d023da', 'cc4283f'),
         ('8bf9b8f', 'a2ac39e'), ('a2ac39e', '7c1d85f'), ('a2ac39e', '6ebbd34'), ('a2ac39e', 'd827667'),
         ('8bf9b8f', '2f6f10e'), ('2f6f10e', '81baacc'),
         ('7d023da', 'ae948ef'), ('a2ac39e', 'ae948ef'), ('2f6f10e', 'ae948ef'), ('7ddeb23', '3be27ee')]
for a, b in pairs:
    print(a, '<', b, anc(a, b), dates.get(a), dates.get(b))
