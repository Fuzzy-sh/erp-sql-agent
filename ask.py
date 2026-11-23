"""Ask the ERP a question from the terminal.

  python ask.py "Which parts are below their reorder point?"
  python ask.py --version B "How many open sales orders are there?"
  python ask.py --trace "..."      # also show every tool call
"""

import argparse

from erp_agent.versions import VERSIONS


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("question")
    p.add_argument("--version", choices=list(VERSIONS), default="C")
    p.add_argument("--model", default=None)
    p.add_argument("--trace", action="store_true")
    a = p.parse_args()

    r = VERSIONS[a.version](a.question, a.model)
    if a.trace:
        print("\n".join(r.trace), "\n")
    print(f"[{r.version}] {r.seconds:.1f}s, {r.tokens} tokens, "
          f"{r.queries_tried} queries ({r.rejected} rejected)")
    print("SQL:", r.sql)
    print("Answer:", r.error or r.answer)


if __name__ == "__main__":
    main()
