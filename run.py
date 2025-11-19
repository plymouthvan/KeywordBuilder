#!/usr/bin/env python3

import os
import sys
import csv
import re
import shlex
from collections import Counter
from typing import List, Optional, Tuple, Iterable, Dict

from keyword_builder import (
    load_core_keywords,
    load_secondary_rows,
    write_output,
    write_csv_output,
    generate_keywords_with_core,
    load_templates,
    load_secondary_dict_rows,
    generate_keywords_from_templates_list,
    is_multi_column_template,
    load_template_table,
    generate_rows_from_template_table_list_row_grouped,
    dedupe_rows_preserve_order,
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
    print("  - Template mode (optional): provide a template CSV that can be either:")
    print("      * Single-column: each row is a phrase pattern like '{core} in {city}, {state}'")
    print("      * Multi-column: a table whose cells may contain placeholders; outputs a CSV preserving the template's headers.")
    print("    Placeholders like {core}, {city}, {state}, {venue} are supported.")
    print("Steps:")
    print("  1) Introduction")
    print("  2) Select the first file with core keywords")
    print("  3) Select one or more secondary/component CSVs (you can add additional lists)")
    print("  4) Optionally select a template CSV to control which permutations are generated")
    print("  5) Preview the output using the first core and first row")
    print("  6) Choose grouping key and whether to split output into separate files")
    print("  7) Confirm task")
    print("  8) Check for and report on duplicates; offer cleanup")
    print("  9) Apply cleanup if you choose")
    print(" 10) Choose match type (broad, phrase, exact)")
    print(" 11) Choose an output destination")
    print(" 12) Save the file(s)")
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


def sanitize_component(s: str, fallback: Optional[str] = None) -> str:
    """
    Sanitize a filename component:
      - lowercase
      - allow a-z, 0-9, underscore, hyphen
      - convert other chars to '-'
      - collapse duplicate '-' and trim leading/trailing '-'
    If result is empty and fallback provided, return fallback.
    """
    s = (s or "").strip().lower()
    s = re.sub(r"[^a-z0-9_-]+", "-", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s if s or fallback is None else fallback


def slugify_for_filename(s: str) -> str:
    """Turn an arbitrary string into a safe filename segment."""
    out = sanitize_component(s, fallback=None)
    if not out:
        return "group"
    return out[:80]


def prompt_output_directory(prompt_text: str, default_dir: str = "output") -> str:
    while True:
        suffix = f" [{default_dir}]" if default_dir else ""
        val = input(f"{prompt_text}{suffix}: ").strip()
        if not val and default_dir:
            val = default_dir
        if not val:
            print("Please enter a folder path.")
            continue
        # Interpret shell-like escapes and quotes so that paths with spaces are accepted.
        try:
            tokens = shlex.split(val)
            val_parsed = " ".join(tokens) if tokens else val
        except ValueError:
            val_parsed = val
        path = os.path.expanduser(os.path.expandvars(val_parsed))
        if os.path.isfile(path):
            print(f"'{path}' is a file. Please provide a folder path.")
            continue
        # Don't require existence; we'll create later when writing.
        return path


def prompt_prefix(prompt_text: str, default_prefix: str = "") -> str:
    suffix = f" [{default_prefix}]" if default_prefix else ""
    val = input(f"{prompt_text}{suffix}: ").strip()
    if not val and default_prefix:
        val = default_prefix
    # Sanitize but allow empty result
    return sanitize_component(val, fallback=None) or ""


def prompt_file_suffix(prompt_text: str, default_suffix: str = "txt") -> str:
    while True:
        suffix = input(f"{prompt_text} [{default_suffix}]: ").strip().lower()
        if not suffix:
            suffix = default_suffix
        # Strip leading dot if present
        if suffix.startswith("."):
            suffix = suffix[1:]
        # Allow simple alphanum suffixes only
        if re.fullmatch(r"[a-z0-9]{1,10}", suffix):
            return suffix
        print("Please enter a simple extension like txt, csv, tsv (letters/numbers only, up to 10 chars).")


def prompt_grouping_key(use_template: bool, headers: Optional[List[str]]) -> str:
    """
    Prompt the user to choose a grouping key.
    Returns one of:
      - 'none' (no grouping)
      - 'core'
      - <header name> (template mode only)
    """
    options: List[str] = ["none", "core"]
    if use_template and headers:
        options.extend(headers)

    print("\n--- Grouping & Output Options ---")
    print("Choose a grouping key. If you later choose to split output, one file will be created per")
    print("distinct value of this key. Choose 'none' to disable grouping.")
    for i, name in enumerate(options, start=1):
        mark = " (default)" if i == 1 else ""
        print(f"  {i}. {name}{mark}")

    default_idx = 1
    while True:
        resp = input(f"Enter number 1-{len(options)} [{default_idx}]: ").strip()
        if not resp:
            return options[default_idx - 1]
        try:
            idx = int(resp)
            if 1 <= idx <= len(options):
                return options[idx - 1]
        except ValueError:
            pass
        print("Invalid selection.")


def derive_split_output_path(folder: str, prefix: str, group_key: str, group_value: str, suffix: str) -> str:
    """
    Build a split-mode output file path:
      <folder>/<prefix><sep?><group_key>-<group_value>.<suffix>
    Rules:
      - If prefix is present and ends with '-' or '_', do not insert an extra separator.
      - Otherwise, insert a single '-' between prefix and the key/value segment.
      - All parts are sanitized; no '=' or stray dots are introduced.
    """
    folder = os.path.expanduser(os.path.expandvars(folder)) or "."
    key_slug = slugify_for_filename(group_key or "group")
    val_slug = slugify_for_filename(group_value or "unknown")
    pre_slug = sanitize_component(prefix or "", fallback=None) or ""

    key_val = f"{key_slug}-{val_slug}"
    if pre_slug:
        if pre_slug.endswith(("-", "_")):
            name_base = f"{pre_slug}{key_val}"
        else:
            name_base = f"{pre_slug}-{key_val}"
    else:
        name_base = key_val

    name = f"{name_base}.{suffix.lower()}"
    return os.path.join(folder, name)


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


def extract_placeholders_from_cells(cells: List[str]) -> List[str]:
    """Extract placeholder names from a list of template cells (for multi-column templates)."""
    names: List[str] = []
    for c in cells:
        names.extend(extract_placeholders(c))
    return names


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
            "Path to TEMPLATE CSV",
            default_template or None,
            must_exist=True,
        )

    # Load data now so we can preview
    core_keywords = load_core_keywords(core_path, core_col)

    headers_union: List[str] = []
    if use_template:
        # Template mode supports multiple secondary CSVs; each must have headers.
        all_secondary_paths = [secondary_path] + additional_secondary_paths

        # Load each as dict rows and accumulate headers with collision checks
        rows_sets: List[List[dict]] = []
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

        # Detect template type and load accordingly
        table_template = is_multi_column_template(template_path)
        if table_template:
            tmpl_headers, tmpl_rows = load_template_table(template_path)

            # Validate placeholders across all cells
            allowed = set(['core'] + headers_union)
            unknown = set()
            for cells in tmpl_rows:
                for name in extract_placeholders_from_cells(cells):
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

            if not core_keywords or not secondary_dict_rows or not tmpl_rows:
                print(
                    "Error: Cannot generate rows. One or more input files are empty or invalid.",
                    file=sys.stderr,
                )
                sys.exit(1)
        else:
            templates = load_templates(template_path)

            # Validate that all placeholders used in templates are from headers or 'core'
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
        if table_template:
            print("Template mode: MULTI-COLUMN table. Placeholders must match secondary CSV column names and 'core'.")
            print("Available placeholders: " + ", ".join("{" + p + "}" for p in (['core'] + headers_union)))
            # preview: first core + first row across all template rows (limited)
            preview_rows: List[List[str]] = []
            if core_keywords and secondary_dict_rows and tmpl_rows:
                preview_rows = generate_rows_from_template_table_list_row_grouped(
                    core_keywords[:1], secondary_dict_rows[:1], tmpl_rows
                )[:8]
            if tmpl_headers:
                print("  " + " | ".join(tmpl_headers))
            if preview_rows:
                for r in preview_rows:
                    print("  " + " | ".join(r))
            else:
                print("  No preview available (inputs may be empty).")
            print("\nNote: Multi-column templates output CSV; duplicate rows will be removed (stable, first occurrence). Match-type wrapping and grouping/splitting are skipped.")
        else:
            print("Template mode: placeholders must match secondary CSV column names and 'core'.")
            print("Available placeholders: " + ", ".join("{" + p + "}" for p in (['core'] + headers_union)))
            example = preview_example_templates(core_keywords, secondary_dict_rows, templates)
            if example:
                for line in example:
                    print(f"  {line}")
            else:
                print("  No preview available (inputs may be empty).")
    else:
        example = preview_example(core_keywords, secondary_rows, include_reverse=False, min_fields=None)
        if example:
            for line in example:
                print(f"  {line}")
        else:
            print("  No preview available (inputs may be empty).")

    # Step 5 (new): Grouping & Output split preference
    if use_template:
        if table_template:
            group_key = "none"
            split_output = False
            print("\nGrouping is disabled for multi-column templates; output will be a single CSV file.")
        else:
            group_key = prompt_grouping_key(True, headers_union)
    else:
        group_key = prompt_grouping_key(False, None)

    split_output = False
    if group_key != "none":
        split_output = prompt_yes_no("Split output into separate files by this grouping key?", False)
    else:
        print("Grouping is 'none'; output will be saved as a single file.")

    # Step 6: Confirm task
    print("\n--- Confirm ---")
    print(f"Core file: {core_path} (column: {core_col})")
    if use_template:
        all_secondary_paths = [secondary_path] + additional_secondary_paths
        print(f"Secondary files: {', '.join(all_secondary_paths)} (template mode)")
        print(f"Template file: {template_path} ({'multi-column' if table_template else 'single-column'})")
    else:
        print(f"Secondary file: {secondary_path} (skip header: {skip_header})")
        if additional_secondary_paths:
            print(f"Note: {len(additional_secondary_paths)} additional secondary list(s) will be ignored in non-template mode.")
    print(f"Grouping key: {group_key}")
    print(f"Output mode: {'Split by key' if split_output else 'Single file'}")
    proceed = prompt_yes_no("Proceed with full generation?", True)
    if not proceed:
        print("Canceled.")
        sys.exit(0)

    # Special handling: multi-column template mode (CSV-to-CSV)
    if use_template and table_template:
        sec_count = len(secondary_dict_rows)
        raw_rows = generate_rows_from_template_table_list_row_grouped(
            core_keywords,
            secondary_dict_rows,
            tmpl_rows
        )
        # Stable de-duplication of rows (preserve first occurrence)
        unique_rows = dedupe_rows_preserve_order(raw_rows)
        output_path = prompt_save_path("keywords.csv")
        write_csv_output(output_path, tmpl_headers, unique_rows)

        # Summary for table mode
        print("\n--- Summary ---")
        print(f"Loaded {len(core_keywords)} core phrases.")
        print(f"Loaded {sec_count} secondary rows.")
        print(f"Used {len(tmpl_rows)} template rows across {len(tmpl_headers)} columns.")
        print(f"Generated {len(unique_rows)} unique rows.")
        print(f"Wrote CSV output to {output_path}")
        return

    # Generate all (row-grouped) and record first-occurrence grouping (string template or permutation modes)
    raw_keywords: List[str] = []
    kw_to_group: Dict[str, str] = {}
    if use_template:
        for row in secondary_dict_rows:
            for core in core_keywords:
                row_keywords = generate_keywords_from_templates_list([core], [row], templates)
                raw_keywords.extend(row_keywords)
                if group_key == "core":
                    gv = core
                elif group_key != "none":
                    gv = row.get(group_key, "") or "unknown"
                else:
                    gv = "all"
                for kw in row_keywords:
                    if kw not in kw_to_group:
                        kw_to_group[kw] = gv
        sec_count = len(secondary_dict_rows)
    else:
        for row in secondary_rows:
            for core in core_keywords:
                phrases = generate_keywords_with_core(core, row, min_fields=None)
                raw_keywords.extend(phrases)
                gv = core if group_key == "core" else "all"
                for kw in phrases:
                    if kw not in kw_to_group:
                        kw_to_group[kw] = gv
        sec_count = len(secondary_rows)

    # Step 7: Check for and report duplicates
    raw_count, uniq_count, dup_count, top_dups = summarize_duplicates(raw_keywords)
    print("\n--- Duplicate Analysis ---")
    print(f"Total generated (raw): {raw_count}")
    print(f"Unique after de-duplication: {uniq_count}")
    print(f"Duplicates found: {dup_count}")
    if dup_count > 0 and top_dups:
        print("Top duplicate entries:")
        for kw, c in top_dups:
            print(f"  ({c}x) {kw}")

    # Step 8: Offer to clean duplicates
    if dup_count > 0:
        clean = prompt_yes_no("Remove duplicates before saving?", True)
    else:
        clean = True  # Nothing to clean; proceed with unique list for consistency

    if clean:
        final_keywords_raw = dedupe_preserve_order(raw_keywords)
    else:
        final_keywords_raw = raw_keywords  # keep raw order (may contain duplicates)

    # Step 9: Choose match type formatting
    print("\n--- Match Type ---")
    print("Choose how to prepare keywords:")
    print("  0 = Broad match (no wrapping), e.g., keyword")
    print('  1 = Phrase match (wrap in double quotes), e.g., "keyword"')
    print("  2 = Exact match (wrap in square brackets), e.g., [keyword]")
    match_type = prompt_match_type(0)

    # Step 10/11: Ask for output destination and save
    if split_output and group_key != "none":
        # New split-mode prompts: folder, prefix, suffix
        out_folder = prompt_output_directory("Folder to save split files", "output")
        out_prefix = prompt_prefix("Filename prefix (optional, e.g., 'locales')", "")
        out_suffix = prompt_file_suffix("File extension for split files", "txt")

        # Group by first-occurrence mapping
        grouped: Dict[str, List[str]] = {}
        for kw in final_keywords_raw:
            gv = kw_to_group.get(kw, "all")
            grouped.setdefault(gv, []).append(kw)

        # Show a sample filename and allow the user to adjust the prefix before writing
        if grouped:
            sample_gv = next(iter(grouped.keys()))
            while True:
                sample_path = derive_split_output_path(out_folder, out_prefix, group_key, sample_gv, out_suffix)
                print(f"Sample filename preview: {os.path.basename(sample_path)}")
                if prompt_yes_no("Use this naming convention for all files?", True):
                    break
                out_prefix = prompt_prefix("Enter a new filename prefix (leave blank to remove prefix)", out_prefix)

        written_files: List[str] = []
        for gv, kws in grouped.items():
            formatted = format_keywords_for_match(kws, match_type)
            out_path = derive_split_output_path(out_folder, out_prefix, group_key, gv, out_suffix)
            write_output(out_path, formatted)
            written_files.append(out_path)

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
        print(f"Grouping key: {group_key}")
        print(f"Output mode: Split into {len(written_files)} file(s).")
        if written_files:
            preview_list = written_files[:5]
            for p in preview_list:
                print(f"  Wrote: {p}")
    else:
        output_path = prompt_save_path("keywords.txt")
        final_keywords_formatted = format_keywords_for_match(final_keywords_raw, match_type)
        write_output(output_path, final_keywords_formatted)

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