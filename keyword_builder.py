#!/usr/bin/env python3

import argparse
import csv
import itertools
import os
import re
import sys
from typing import List, Set, Iterable, Optional, Dict, Tuple

def load_core_keywords(path: str, core_column: str) -> List[str]:
    """Loads core phrases from a CSV file."""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            if core_column not in reader.fieldnames:
                raise ValueError(f"Core column '{core_column}' not found in {path}. "
                                 f"Available columns: {', '.join(reader.fieldnames)}")
            
            keywords = [
                line[core_column].strip()
                for line in reader
                if line.get(core_column) and line[core_column].strip()
            ]
            if not keywords:
                print(f"Warning: No core keywords found in '{path}' under column '{core_column}'.", file=sys.stderr)
            return keywords
    except FileNotFoundError:
        print(f"Error: Core file not found at '{path}'", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error reading core file '{path}': {e}", file=sys.stderr)
        sys.exit(1)

def load_secondary_rows(path: str, skip_header: bool) -> List[List[str]]:
    """Loads component rows from a secondary CSV file."""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            if skip_header:
                try:
                    next(reader)
                except StopIteration:
                    # File is empty
                    pass
            
            rows = [
                [cell.strip() for cell in row if cell and cell.strip()]
                for row in reader
            ]
            # Filter out empty rows that might result from the list comprehension
            usable_rows = [row for row in rows if row]
            if not usable_rows:
                print(f"Warning: No usable data rows found in '{path}'.", file=sys.stderr)
            return usable_rows
    except FileNotFoundError:
        print(f"Error: Secondary file not found at '{path}'", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error reading secondary file '{path}': {e}", file=sys.stderr)
        sys.exit(1)

def load_secondary_dict_rows(path: str) -> Tuple[List[Dict[str, str]], List[str]]:
    """Load secondary rows as dictionaries keyed by header names (required for template mode)."""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames:
                print(f"Error: Secondary file '{path}' must have a header row when using templates.", file=sys.stderr)
                sys.exit(1)
            headers = [h.strip() for h in reader.fieldnames]
            rows: List[Dict[str, str]] = []
            for row in reader:
                cleaned = {(k.strip() if k else ''): (v.strip() if v else '') for k, v in row.items()}
                # consider usable if any non-empty values across columns
                if any(cleaned.get(h, '') for h in headers):
                    rows.append(cleaned)
            if not rows:
                print(f"Warning: No usable data rows found in '{path}'.", file=sys.stderr)
            return rows, headers
    except FileNotFoundError:
        print(f"Error: Secondary file not found at '{path}'", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error reading secondary file '{path}': {e}", file=sys.stderr)
        sys.exit(1)

def load_templates(path: str) -> List[str]:
    """Load template strings from a single-column CSV file.

    Rules:
    - Ignore blank lines and lines starting with '#'
    - Only keep rows that contain at least one {placeholder}
      (prevents headers/labels like 'CORE + Locale' from being treated as templates)
    """
    try:
        with open(path, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            templates: List[str] = []
            skipped_no_placeholder = 0
            placeholder_re = re.compile(r'{[^{}]+}')
            for row in reader:
                if not row:
                    continue
                tmpl = (row[0] or '').strip()
                # Allow comments and blank lines
                if not tmpl or tmpl.startswith('#'):
                    continue
                # Keep only lines with at least one {placeholder}
                if not placeholder_re.search(tmpl):
                    skipped_no_placeholder += 1
                    continue
                templates.append(tmpl)
            if not templates:
                print(f"Warning: No templates with placeholders found in '{path}'.", file=sys.stderr)
            if skipped_no_placeholder:
                print(f"Note: Skipped {skipped_no_placeholder} non-template row(s) (no placeholders) in '{path}'.", file=sys.stderr)
            return templates
    except FileNotFoundError:
        print(f"Error: Template file not found at '{path}'", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error reading template file '{path}': {e}", file=sys.stderr)
        sys.exit(1)

def _extract_placeholders(tmpl: str) -> List[str]:
    """Extract placeholder names like {core}, {city} from a template string."""
    return re.findall(r'{([^{}]+)}', tmpl)

def render_template(tmpl: str, mapping: Dict[str, str]) -> Optional[str]:
    """
    Render a template by replacing {placeholders} with values from mapping.
    - All placeholders must exist in mapping and be non-empty.
    - Collapses repeated spaces and trims the result.
    Returns None if any placeholder is missing or empty.
    """
    placeholders = _extract_placeholders(tmpl)
    for name in placeholders:
        if name not in mapping:
            return None
        if not mapping[name]:
            return None
    result = tmpl
    for name in placeholders:
        result = result.replace('{' + name + '}', mapping[name])
    result = " ".join(result.split()).strip()
    return result if result else None

def generate_keywords_from_templates_list(
    core_keywords: List[str],
    secondary_rows: List[Dict[str, str]],
    templates: List[str],
) -> List[str]:
    """Generate all phrases (with potential duplicates) using provided templates."""
    out: List[str] = []
    for core_phrase in core_keywords:
        for row in secondary_rows:
            mapping: Dict[str, str] = dict(row)
            mapping['core'] = core_phrase
            for tmpl in templates:
                rendered = render_template(tmpl, mapping)
                if rendered:
                    out.append(rendered)
    return out

def build_keywords_from_templates(
    core_keywords: List[str],
    secondary_rows: List[Dict[str, str]],
    templates: List[str],
) -> Set[str]:
    """Generate a unique set of phrases using provided templates."""
    return set(generate_keywords_from_templates_list(core_keywords, secondary_rows, templates))

# Row-grouped generation helpers
def generate_keywords_from_templates_list_row_grouped(
    core_keywords: List[str],
    secondary_rows: List[Dict[str, str]],
    templates: List[str],
) -> List[str]:
    """
    Generate phrases in a stable order grouped by secondary rows, then by core.
    Order:
      for each secondary row:
        for each core phrase:
          for each template:
            render -> append
    """
    out: List[str] = []
    for row in secondary_rows:
        for core_phrase in core_keywords:
            mapping: Dict[str, str] = dict(row)
            mapping['core'] = core_phrase
            for tmpl in templates:
                rendered = render_template(tmpl, mapping)
                if rendered:
                    out.append(rendered)
    return out

def generate_all_keywords_list_row_grouped(
    core_keywords: List[str],
    secondary_rows: List[List[str]],
    min_fields: Optional[int],
) -> List[str]:
    """
    Generate phrases in a stable order grouped by secondary rows, then by core.
    Uses generate_keywords_with_core for each (row, core) pair.
    """
    out: List[str] = []
    for row in secondary_rows:
        for core_phrase in core_keywords:
            phrases = generate_keywords_with_core(core_phrase, row, min_fields)
            out.extend(phrases)
    return out

def dedupe_preserve_order(keywords: Iterable[str]) -> List[str]:
    """Stable de-duplication that preserves the first occurrence order."""
    seen: Set[str] = set()
    out: List[str] = []
    for kw in keywords:
        if kw not in seen:
            seen.add(kw)
            out.append(kw)
    return out

def generate_permutations_for_row(fields: List[str], min_fields: int) -> List[str]:
    """Generates all specified permutations for a single row's fields."""
    if not fields:
        return []

    max_len = len(fields)
    start_len = min(min_fields, max_len) if min_fields is not None else max_len

    all_perms: List[str] = []
    for length in range(start_len, max_len + 1):
        perms = itertools.permutations(fields, length)
        all_perms.extend(" ".join(p) for p in perms)
        
    return all_perms


def generate_keywords_with_core(core_phrase: str, fields: List[str], min_fields: Optional[int]) -> List[str]:
    """
    Generate phrases that include the core phrase and a permutation of a subset of the row's fields,
    placing the core in every possible position.

    Semantics:
      - If min_fields is None, only permutations that use all fields from the row are generated (original default).
      - If min_fields is an integer k (0 <= k <= len(fields)), generate permutations for all subset lengths
        from k up to len(fields), inserting the core phrase at every possible position.
    """
    max_len = len(fields)
    start_len = min(min_fields, max_len) if min_fields is not None else max_len

    results: List[str] = []
    for length in range(start_len, max_len + 1):
        for combo in itertools.combinations(fields, length):
            for perm in itertools.permutations(combo, length):
                for pos in range(length + 1):
                    parts = list(perm[:pos]) + [core_phrase] + list(perm[pos:])
                    results.append(" ".join(parts))
    return results

def build_keywords(
    core_keywords: List[str],
    secondary_rows: List[List[str]],
    include_reverse: bool,
    min_fields: int
) -> Set[str]:
    """Build the final set of unique keywords.

    The core phrase is inserted at every possible position relative to the selected row fields.
    The 'include_reverse' flag is now a no-op (kept for CLI compatibility); all positions are generated.
    """
    keywords: Set[str] = set()

    for core_phrase in core_keywords:
        for row in secondary_rows:
            phrases = generate_keywords_with_core(core_phrase, row, min_fields)
            keywords.update(phrases)

    return keywords

def write_output(path: str, keywords: Iterable[str]):
    """Writes keywords to the specified output file, creating dirs if needed."""
    try:
        # Ensure the output directory exists
        output_dir = os.path.dirname(path)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
            
        with open(path, 'w', encoding='utf-8') as f:
            for keyword in keywords:
                f.write(keyword + '\n')
    except IOError as e:
        print(f"Error: Could not write to output file '{path}': {e}", file=sys.stderr)
        sys.exit(1)

def main():
    """Main function to parse arguments and run the keyword builder."""
    parser = argparse.ArgumentParser(
        description="Generate keyword permutations from core and secondary CSV files.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        '--core',
        required=True,
        help="Path to the core keyword CSV file."
    )
    parser.add_argument(
        '--secondary',
        required=True,
        help="Path to the secondary/components CSV file."
    )
    parser.add_argument(
        '--template',
        required=False,
        help=("Optional path to a template CSV (single column) with rows containing placeholders like "
              "{core} and {column_name}. When provided, generation uses these templates and the "
              "secondary CSV MUST have a header row with the referenced column names.")
    )
    parser.add_argument(
        '--output',
        required=True,
        help="Path to the output text file."
    )
    parser.add_argument(
        '--core-column',
        default='core',
        help='Name of the column to use in the core CSV (default: "core").'
    )
    parser.add_argument(
        '--skip-header',
        action='store_true',
        help="If set, treat the first row of the secondary CSV as a header."
    )
    parser.add_argument(
        '--include-reverse',
        action='store_true',
        help="Deprecated/no-op: all outputs include the core at every position; this flag is ignored."
    )
    parser.add_argument(
        '--min-fields',
        type=int,
        default=None,
        help="Minimum number of fields for secondary permutations.\n"
             "Generates permutations for all lengths from min_fields up to the total number of fields."
    )

    args = parser.parse_args()

    core_keywords = load_core_keywords(args.core, args.core_column)

    if args.template:
        secondary_dict_rows, headers = load_secondary_dict_rows(args.secondary)
        templates = load_templates(args.template)

        # Validate that all placeholders used in templates are from headers or 'core'
        allowed = set(['core'] + headers)
        unknown: Set[str] = set()
        for tmpl in templates:
            for name in _extract_placeholders(tmpl):
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
                ", ".join("{" + n + "}" for n in (['core'] + headers)),
                file=sys.stderr,
            )
            sys.exit(1)

        if not core_keywords or not secondary_dict_rows or not templates:
            print("Error: Cannot generate keywords. One or more inputs are empty or contain no usable data.", file=sys.stderr)
            sys.exit(1)

        # Row-grouped order: secondary row -> core -> templates
        raw_keywords = generate_keywords_from_templates_list_row_grouped(
            core_keywords,
            secondary_dict_rows,
            templates
        )
        sec_count = len(secondary_dict_rows)
    else:
        secondary_rows = load_secondary_rows(args.secondary, args.skip_header)

        if not core_keywords or not secondary_rows:
            print("Error: Cannot generate keywords. One or both input files are empty or contain no usable data.", file=sys.stderr)
            sys.exit(1)

        # Row-grouped order: secondary row -> core -> permutations
        raw_keywords = generate_all_keywords_list_row_grouped(
            core_keywords,
            secondary_rows,
            args.min_fields
        )
        sec_count = len(secondary_rows)

    # Stable de-duplication while preserving grouping order
    unique_keywords = dedupe_preserve_order(raw_keywords)

    write_output(args.output, unique_keywords)

    print("--- Summary ---")
    print(f"Loaded {len(core_keywords)} core phrases.")
    print(f"Loaded {sec_count} secondary rows.")
    if args.template:
        print(f"Used {len(templates)} templates.")
    print(f"Generated {len(unique_keywords)} unique keywords.")
    print(f"Wrote output to {args.output}")

if __name__ == "__main__":
    main()