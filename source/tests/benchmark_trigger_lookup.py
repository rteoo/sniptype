"""Synthetic, keyboard-free lookup benchmark.

Run from source: python -m tests.benchmark_trigger_lookup
The reference is the previous longest-first bucket scan, not a live desktop.
"""

import json
import statistics
import time

from trigger_index import compile_trigger_index, find_direct_candidate


def reference_lookup(text, index):
    for target in index["direct_immediate_by_last_char"].get(text[-1:], ()):
        if text.endswith(target.effective_trigger):
            return target
    return None


def measure(lookup, text, index):
    samples = []
    for _ in range(5):
        started = time.perf_counter_ns()
        for _ in range(100):
            lookup(text, index)
        samples.append((time.perf_counter_ns() - started) / 100 / 1000)
    return statistics.median(samples)


def main():
    results = []
    for count in (100, 1000, 10000):
        snippets = {f"z{item:08d}x": "synthetic value" for item in range(count)}
        index = compile_trigger_index(snippets, set())
        for name, text in {
            "miss": "no-matching-triggerx",
            "last_hit": f"z{count - 1:08d}x",
            "first_hit": "z00000000x",
        }.items():
            assert reference_lookup(text, index) == find_direct_candidate(text, index)
            results.append({
                "triggers": count,
                "case": name,
                "reference_median_us": measure(reference_lookup, text, index),
                "current_median_us": measure(find_direct_candidate, text, index),
            })
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
