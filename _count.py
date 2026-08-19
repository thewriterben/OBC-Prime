import re, subprocess
# Cargo's "Doc-tests"/"Running" banners go to stderr; harness "test result"
# lines go to stdout. Interleave them by asking for one stream.
out = subprocess.run(["cargo", "test", "--workspace"],
                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                     text=True, cwd=".")
unit = doc = ignored = 0
cur_doc = False
for ln in out.stdout.splitlines():
    s = ln.strip()
    if s.startswith("Doc-tests"):
        cur_doc = True
    elif s.startswith("Running "):
        cur_doc = False
    m = re.match(r"test result: ok\. (\d+) passed; (\d+) failed; (\d+) ignored", s)
    if m:
        n, f, ig = int(m.group(1)), int(m.group(2)), int(m.group(3))
        assert f == 0, ln
        ignored += ig
        if cur_doc:
            doc += n
        else:
            unit += n
print("unit", unit, "doc", doc, "total", unit + doc, "ignored", ignored)
