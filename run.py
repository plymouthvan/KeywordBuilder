#!/usr/bin/env python3

import os
import sys
import csv
import re
import shlex
from collections import Counter
from typing import List, Optional, Tuple, Iterable

from keyword_builder import (
    load_core_keywords,
    load_secondary_rows,
    write_output,
    generate_keywords_with_core,
    load_templates,
    load_secondary_dict_rows,
    generate_keywords_from_templates_list,
)

BANNER = "=" * 64


def print_header():
    print(BANNER)
    print("Keyword Combiner - Guided CLI")
    print(BANNER)


def print_introduction():
    print("This guided flow will help you generate keyword permutations.")
    print("You can run in two modes:")
    print("  - Full-permutation mode (default): uses all columns from the secondary CSV, inserting the core in every position.")
    print("  - Template mode (optional): provide a single-column template CSV where each row defines a phrase pattern")
    print("    with placeholders like {core}, {city}, {state}, {venue}. Only those patterns are generated.")
    print("Steps:")
    print("  1) Introduction")
    print("  2) Select the first file with core keywords")
    print("  3) Select one or more secondary/component CSVs (you can add additional lists)")
    print("  4) Optionally select a template CSV to control which permutations are generated")
    print("  5) Preview the output using the first core and first row")
    print("  6) Confirm task")
    print("  7) Check for and report on duplicates; offer cleanup")
    print("  8) Apply cleanup if you choose")
    print("  9) Choose match type (broad, phrase, exact)")
    print(" 10) Choose an output file name")
    print(" 11) Save the file")
    print("")


def list_csv_candidates() -> List[str]:
    files = [f for f in os.listdir(".") if f.lower().endswith(".csv")]
    files.sort()
    return files


def sniff_has_header(path: str) -> bool:
    try:
        with open(path, "r", encoding="utf-8", newline="") as f:
            sample = f.read(2048)
            f.seek(0)
            return csv.Sniffer().has_header(sample)
    except Exception:
        return False


def get_fieldnames(path: str) -> List[str]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            return reader.fieldnames or []
    except Exception:
        return []


def prompt_path(prompt: str, default: Optional[str] = None, must_exist: bool = True) -> str:
    while True:
        suffix = f" [{default}]" if default else ""
        val = input(f"{prompt}{suffix}: ").strip()
        if not val and default:
            val = default
        if not val:
            print("Please enter a value.")
            continue
        if must_exist and not os.path.isfile(val):
            print(f"File not found: {val}")
            continue
        return val

def prompt_paths(prompt: str, default: Optional[List[str]] = None, must_exist: bool = True) -> List[str]:
    """
    Prompt for one or more file paths in a single input.
    Accepts comma-separated and/or space-separated values. Quotes are supported for paths with spaces.
    """
    def parse_multi_input(s: str) -> List[str]:
        parts: List[str] = []
        for chunk in s.split(','):
            for tok in shlex.split(chunk):
                if tok:
                    parts.append(tok)
        return parts

    while True:
        default_str = ", ".join(default) if default else ""
        suffix = f" [{default_str}]" if default_str else ""
        val = input(f"{prompt}{suffix}: ").strip()

        paths: List[str]
        if not val and default:
            paths = default
        else:
            paths = parse_multi_input(val)

        if not paths:
            print("Please enter one or more file paths.")
            continue

        # Normalize and validate
        normalized: List[str] = []
        missing: List[str] = []
        for p in paths:
            p_expanded = os.path.expanduser(os.path.expandvars(p))
            if must_exist and not os.path.isfile(p_expanded):
                missing.append(p)
            else:
                normalized.append(p_expanded)

        if missing:
            for m in missing:
                print(f"File not found: {m}")
            continue

        # De-duplicate while preserving order
        seen = set()
        unique_paths: List[str] = []
        for p in normalized:
            if p not in seen:
                seen.add(p)
                unique_paths.append(p)

        return unique_paths


def prompt_yes_no(prompt: str, default: bool) -> bool:
    d = "Y/n" if default else "y/N"
    while True:
        val = input(f"{prompt} [{d}]: ").strip().lower()
        if not val:
            return default
        if val in ("y", "yes"):
            return True
        if val in ("n", "no"):
            return False
        print("Please answer y or n.")


def choose_column(path: str, default_name: Optional[str] = "core") -> str:
    fields = get_fieldnames(path)
    if not fields:
        print(f"Error: '{path}' does not appear to have a header row. The core file must have headers.")
        sys.exit(1)
    default_idx = fields.index(default_name) if default_name in fields else 0
    print("Select the core column from the options below:")
    for i, name in enumerate(fields, start=1):
        mark = " (default)" if i - 1 == default_idx else ""
        print(f"  {i}. {name}{mark}")
    while True:
        resp = input(f"Enter number 1-{len(fields)} [{default_idx + 1}]: ").strip()
        if not resp:
            return fields[default_idx]
        try:
            idx = int(resp)
            if 1 <= idx <= len(fields):
                return fields[idx - 1]
        except ValueError:
            pass
        print("Invalid selection.")


def preview_example(
    core_keywords: List[str],
    secondary_rows: List[List[str]],
    include_reverse: bool = False,
    min_fields: Optional[int] = None,
) -> List[str]:
    out: List[str] = []
    if not core_keywords or not secondary_rows:
        return out
    core = core_keywords[0]
    row = secondary_rows[0]
    phrases = generate_keywords_with_core(core, row, min_fields)
    return phrases[:12]


def generate_all_keywords_list(
    core_keywords: List[str],
    secondary_rows: List[List[str]],
    include_reverse: bool = False,
    min_fields: Optional[int] = None,
) -> List[str]:
    """Generate ALL keywords (including potential duplicates), preserving order.

    'include_reverse' is ignored; the core is inserted at every possible position.
    """
    out: List[str] = []
    for core_phrase in core_keywords:
        for row in secondary_rows:
            phrases = generate_keywords_with_core(core_phrase, row, min_fields)
            out.extend(phrases)
    return out


def preview_example_templates(
    core_keywords: List[str],
    secondary_dict_rows: List[dict],
    templates: List[str],
) -> List[str]:
    """Preview for template mode using first core + first secondary row across templates."""
    if not core_keywords or not secondary_dict_rows or not templates:
        return []
    core = core_keywords[0]
    row = secondary_dict_rows[0]
    phrases = generate_keywords_from_templates_list([core], [row], templates)
    return phrases[:12]


def generate_all_keywords_list_templates(
    core_keywords: List[str],
    secondary_dict_rows: List[dict],
    templates: List[str],
) -> List[str]:
    """Generate ALL keywords for template mode (may include duplicates), preserving order."""
    return generate_keywords_from_templates_list(core_keywords, secondary_dict_rows, templates)


def dedupe_preserve_order(keywords: Iterable[str]) -> List[str]:
    """Stable de-duplication that preserves the first occurrence order."""
    seen = set()
    out: List[str] = []
    for kw in keywords:
        if kw not in seen:
            seen.add(kw)
            out.append(kw)
    return out


def extract_placeholders(tmpl: str) -> List[str]:
    """Extract placeholder names like {core}, {city} from a template string."""
    return re.findall(r'{([^{}]+)}', tmpl)


def summarize_duplicates(keywords: List[str]) -> Tuple[int, int, int, List[Tuple[str, int]]]:
    """Return (raw_count, unique_count, dup_count, top_duplicates[ (kw, count), ... ])."""
    raw_count = len(keywords)
    uniq_count = len(set(keywords))
    dup_count = raw_count - uniq_count
    top_dups: List[Tuple[str, int]] = []
    if dup_count > 0:
        counts = Counter(keywords)
        # Keep only entries with count > 1 and show top 10
        top_dups = [(kw, c) for kw, c in counts.most_common(10) if c > 1]
    return raw_count, uniq_count, dup_count, top_dups


def prompt_save_path(default_output: str = "keywords.txt") -> str:
    while True:
        path = prompt_path("Name the output file", default_output, must_exist=False)
        if os.path.isdir(path):
            print(f"'{path}' is a directory. Please provide a file name or path to a file.")
            continue
        if os.path.exists(path):
            if prompt_yes_no(f"'{path}' already exists. Overwrite?", False):
                return path
            else:
                # Loop back to ask for a different name
                continue
        return path


def prompt_match_type(default: int = 0) -> int:
    mapping = {
        "0": 0, "b": 0, "broad": 0,
        "1": 1, "p": 1, "phrase": 1,
        "2": 2, "e": 2, "exact": 2,
    }
    while True:
        val = input(f"Select match type [0=broad, 1=phrase, 2=exact] [{default}]: ").strip().lower()
        if not val:
            return default
        if val in mapping:
            return mapping[val]
        print("Please enter 0, 1, or 2 (broad/phrase/exact).")

def format_keywords_for_match(keywords: Iterable[str], match_type: int) -> List[str]:
    if match_type == 1:
        return [f'"{kw}"' for kw in keywords]
    if match_type == 2:
        return [f'[{kw}]' for kw in keywords]
    return list(keywords)

def guided_flow():
    # Step 1: Introduction
    print_header()
    print_introduction()

    # Detect CSVs for convenience defaults
    csvs = list_csv_candidates()
    default_core = "core.csv" if "core.csv" in csvs else (csvs[0] if csvs else "")
    default_secondary = (
        "venues.csv"
        if "venues.csv" in csvs
        else (csvs[1] if len(csvs) > 1 else (csvs[0] if csvs else ""))
    )
    default_template = "template.csv" if "template.csv" in csvs else ""

    if csvs:
        print(f"Detected CSV files: {', '.join(csvs)}")
    else:
        print("No CSV files detected in current directory.")
    print("")

    # Step 2: Select the core keywords file
    core_path = prompt_path("Path to CORE CSV", default_core or None, must_exist=True)
    core_col = choose_column(core_path, default_name="core")

    # Step 3: Select the permutation keywords file(s)
    initial_paths = prompt_paths(
        "Path(s) to SECONDARY/COMPONENTS CSV(s) (comma or space separated)",
        [default_secondary] if default_secondary else None,
        must_exist=True,
    )

    # Choose primary secondary file (first). Additional files are optional and may be ignored in non-template mode.
    secondary_path = initial_paths[0]
    additional_secondary_paths: List[str] = list(dict.fromkeys(initial_paths[1:]))

    # Allow adding additional lists (multi-add supported)
    while prompt_yes_no("Add more SECONDARY/COMPONENTS CSVs?", False):
        more_paths = prompt_paths("Path(s) to additional SECONDARY/COMPONENTS CSV(s)", None, must_exist=True)
        for p in more_paths:
            if p not in [secondary_path] + additional_secondary_paths:
                additional_secondary_paths.append(p)

    # Optional: Template mode
    use_template = prompt_yes_no(
        "Use a template CSV to control which permutations are generated?",
        bool(default_template),
    )
    template_path: Optional[str] = None
    if use_template:
        template_path = prompt_path(
            "Path to TEMPLATE CSV (single-column)",
            default_template or None,
            must_exist=True,
        )

    # Load data now so we can preview
    core_keywords = load_core_keywords(core_path, core_col)

    if use_template:
        # Template mode supports multiple secondary CSVs; each must have headers.
        all_secondary_paths = [secondary_path] + additional_secondary_paths

        # Load each as dict rows and accumulate headers with collision checks
        rows_sets: List[List[dict]] = []
        headers_union: List[str] = []
        seen_headers = set()
        dup_headers = set()

        for p in all_secondary_paths:
            rows_i, headers_i = load_secondary_dict_rows(p)
            rows_sets.append(rows_i)
            for h in headers_i:
                if h in seen_headers:
                    dup_headers.add(h)
                else:
                    seen_headers.add(h)
                    headers_union.append(h)

        if dup_headers:
            print(
                "Error: Duplicate column names across provided secondary CSVs: " +
                ", ".join("{" + h + "}" for h in sorted(dup_headers)) + ". " +
                "Please rename columns to be unique across files.",
                file=sys.stderr,
            )
            sys.exit(1)

        # Cartesian product of all secondary rows, merging dictionaries
        secondary_dict_rows: List[dict] = [{}]
        for rows_i in rows_sets:
            new_accum: List[dict] = []
            for a in secondary_dict_rows:
                for b in rows_i:
                    merged = dict(a)
                    merged.update(b)
                    new_accum.append(merged)
            secondary_dict_rows = new_accum

        templates = load_templates(template_path)

        # Validate that all placeholders used in templates are from headers or 'core'
        headers = headers_union
        allowed = set(['core'] + headers_union)
        unknown = set()
        for tmpl in templates:
            for name in extract_placeholders(tmpl):
                if name not in allowed:
                    unknown.add(name)
        if unknown:
            print(
                "Error: Template contains unknown placeholders: " +
                ", ".join("{" + n + "}" for n in sorted(unknown)),
                file=sys.stderr,
            )
            print(
                "Allowed placeholders are: " +
                ", ".join("{" + n + "}" for n in (['core'] + headers_union)),
                file=sys.stderr,
            )
            sys.exit(1)

        if not core_keywords or not secondary_dict_rows or not templates:
            print(
                "Error: Cannot generate keywords. One or more input files are empty or invalid.",
                file=sys.stderr,
            )
            sys.exit(1)
    else:
        detected_has_header = sniff_has_header(secondary_path)
        skip_header = prompt_yes_no("Does the secondary file have a header row to skip?", detected_has_header)
        secondary_rows = load_secondary_rows(secondary_path, skip_header)
        if not core_keywords or not secondary_rows:
            print(
                "Error: Cannot generate keywords. One or both input files are empty or contain no usable data.",
                file=sys.stderr,
            )
            sys.exit(1)

    # Step 4: Preview (using first core and first row)
    print("\n--- Preview (first few from first row) ---")
    if use_template:
        print("Template mode: placeholders must match secondary CSV column names and 'core'.")
        print("Available placeholders: " + ", ".join("{" + p + "}" for p in (['core'] + headers)))
        example = preview_example_templates(core_keywords, secondary_dict_rows, templates)
    else:
        example = preview_example(core_keywords, secondary_rows, include_reverse=False, min_fields=None)
    if example:
        for line in example:
            print(f"  {line}")
    else:
        print("  No preview available (inputs may be empty).")

    # Step 5: Confirm task
    print("\n--- Confirm ---")
    print(f"Core file: {core_path} (column: {core_col})")
    if use_template:
        all_secondary_paths = [secondary_path] + additional_secondary_paths
        print(f"Secondary files: {', '.join(all_secondary_paths)} (template mode)")
        print(f"Template file: {template_path}")
    else:
        print(f"Secondary file: {secondary_path} (skip header: {skip_header})")
        if additional_secondary_paths:
            print(f"Note: {len(additional_secondary_paths)} additional secondary list(s) will be ignored in non-template mode.")
    proceed = prompt_yes_no("Proceed with full generation?", True)
    if not proceed:
        print("Canceled.")
        sys.exit(0)

    # Generate all (row-grouped)
    if use_template:
        # Row-grouped generation: by secondary row -> core -> templates
        raw_keywords: List[str] = []
        for row in secondary_dict_rows:
            row_keywords = generate_keywords_from_templates_list(core_keywords, [row], templates)
            raw_keywords.extend(row_keywords)
        sec_count = len(secondary_dict_rows)
    else:
        # Row-grouped generation: by secondary row -> core -> permutations
        raw_keywords: List[str] = []
        for row in secondary_rows:
            for core in core_keywords:
                raw_keywords.extend(generate_keywords_with_core(core, row, min_fields=None))
        sec_count = len(secondary_rows)

    # Step 6: Check for and report duplicates
    raw_count, uniq_count, dup_count, top_dups = summarize_duplicates(raw_keywords)
    print("\n--- Duplicate Analysis ---")
    print(f"Total generated (raw): {raw_count}")
    print(f"Unique after de-duplication: {uniq_count}")
    print(f"Duplicates found: {dup_count}")
    if dup_count > 0 and top_dups:
        print("Top duplicate entries:")
        for kw, c in top_dups:
            print(f"  ({c}x) {kw}")

    # Step 7: Offer to clean duplicates
    if dup_count > 0:
        clean = prompt_yes_no("Remove duplicates before saving?", True)
    else:
        clean = True  # Nothing to clean; proceed with unique list for consistency

    if clean:
        final_keywords = dedupe_preserve_order(raw_keywords)
    else:
        final_keywords = raw_keywords  # keep raw order (may contain duplicates)

    # Step 8: Choose match type formatting
    print("\n--- Match Type ---")
    print("Choose how to prepare keywords:")
    print("  0 = Broad match (no wrapping), e.g., keyword")
    print('  1 = Phrase match (wrap in double quotes), e.g., "keyword"')
    print("  2 = Exact match (wrap in square brackets), e.g., [keyword]")
    match_type = prompt_match_type(0)
    final_keywords = format_keywords_for_match(final_keywords, match_type)

    # Step 9: Ask for output file name
    output_path = prompt_save_path("keywords.txt")

    # Step 10: Save the file
    write_output(output_path, final_keywords)

    # Summary
    print("\n--- Summary ---")
    print(f"Loaded {len(core_keywords)} core phrases.")
    print(f"Loaded {sec_count} secondary rows.")
    if use_template:
        print(f"Used {len(templates)} templates.")
    labels = {0: "Broad", 1: "Phrase", 2: "Exact"}
    print(f"Match type: {labels.get(match_type, 'Broad')} match")
    if clean:
        print(f"Generated {uniq_count} unique keywords (duplicates removed).")
    else:
        print(f"Generated {raw_count} keywords (duplicates kept).")
    print(f"Wrote output to {output_path}")


def main():
    guided_flow()


if __name__ == "__main__":
    main()