"""Offline knowledge base — downloadable task libraries, evaluation patterns,
and correction templates for working without internet.

The knowledge base is stored as JSON files on disk. It can be:
1. Populated from built-in seed data (ships with the application).
2. Exported as a single archive for transfer to air-gapped machines.
3. Imported from a previously exported archive.

Directory layout under ``data/knowledge_base/``:
    tasks/          — task definition JSON files
    patterns/       — evaluation & correction pattern files
    prompts/        — reusable system/correction prompt templates
    manifest.json   — catalog of all items with metadata
"""

from __future__ import annotations

import json
import shutil
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from training_interface.training_engine import Task

# ---------------------------------------------------------------------------
# Seed data — ships with the application so it works offline from day one
# ---------------------------------------------------------------------------

_SEED_TASKS: list[dict[str, Any]] = [
    {
        "title": "FizzBuzz Implementation",
        "instruction": (
            "Write a Python function called fizzbuzz(n) that returns a list of "
            "strings for numbers 1 to n. For multiples of 3 use 'Fizz', for "
            "multiples of 5 use 'Buzz', for multiples of both use 'FizzBuzz', "
            "otherwise use the string representation of the number."
        ),
        "expected_behavior": (
            "A correct Python function that handles all cases including edge "
            "cases like n=0 and n=1."
        ),
        "evaluation_criteria": [
            "Function is named fizzbuzz and accepts one integer argument",
            "Returns a list of strings",
            "Correctly handles multiples of 3 (Fizz)",
            "Correctly handles multiples of 5 (Buzz)",
            "Correctly handles multiples of 15 (FizzBuzz)",
            "Handles edge case n=0 (returns empty list)",
        ],
        "difficulty": "easy",
        "tags": ["python", "basics", "algorithms"],
    },
    {
        "title": "Binary Search",
        "instruction": (
            "Implement a binary search function in Python: "
            "binary_search(arr, target) that returns the index of target in a "
            "sorted list arr, or -1 if not found. Do not use built-in bisect."
        ),
        "expected_behavior": (
            "An iterative or recursive binary search with O(log n) complexity "
            "that correctly handles empty arrays and single-element arrays."
        ),
        "evaluation_criteria": [
            "Function signature is binary_search(arr, target)",
            "Uses binary search algorithm (not linear scan)",
            "Returns correct index when target is found",
            "Returns -1 when target is not found",
            "Handles empty list correctly",
            "Handles single-element list correctly",
        ],
        "difficulty": "easy",
        "tags": ["python", "algorithms", "search"],
    },
    {
        "title": "REST API Error Handler",
        "instruction": (
            "Write a Python decorator called handle_errors that wraps a Flask "
            "or FastAPI route handler. It should catch exceptions and return "
            "a JSON response with 'error' and 'status_code' fields. Map "
            "ValueError to 400, KeyError to 404, and all others to 500."
        ),
        "expected_behavior": (
            "A decorator that catches specific exceptions and returns "
            "structured JSON error responses with appropriate HTTP status codes."
        ),
        "evaluation_criteria": [
            "Implements a decorator named handle_errors",
            "Catches ValueError and returns 400",
            "Catches KeyError and returns 404",
            "Catches generic Exception and returns 500",
            "Returns JSON with 'error' and 'status_code' fields",
            "Preserves the original function's behavior on success",
        ],
        "difficulty": "medium",
        "tags": ["python", "web", "error-handling"],
    },
    {
        "title": "Linked List Reversal",
        "instruction": (
            "Implement a singly linked list in Python with a Node class "
            "(val, next) and a function reverse_list(head) that reverses "
            "the list in-place and returns the new head. Also implement "
            "a to_list(head) helper that converts the linked list to a "
            "Python list for easy verification."
        ),
        "expected_behavior": (
            "Correct in-place reversal using iterative pointer manipulation. "
            "Handles None head and single-node lists."
        ),
        "evaluation_criteria": [
            "Node class has val and next attributes",
            "reverse_list reverses the list in-place",
            "Returns the new head node",
            "Handles empty list (None head)",
            "Handles single-node list",
            "to_list helper works correctly",
        ],
        "difficulty": "medium",
        "tags": ["python", "data-structures", "linked-list"],
    },
    {
        "title": "LRU Cache Implementation",
        "instruction": (
            "Implement an LRU (Least Recently Used) cache in Python as a class "
            "LRUCache(capacity). It should support get(key) and put(key, value) "
            "operations, both in O(1) average time. When the cache exceeds "
            "capacity, evict the least recently used item."
        ),
        "expected_behavior": (
            "A class using OrderedDict or a doubly-linked list + hash map "
            "that provides O(1) get and put with correct LRU eviction."
        ),
        "evaluation_criteria": [
            "Class is named LRUCache with capacity parameter",
            "get(key) returns value or -1 if not found",
            "put(key, value) inserts or updates",
            "Evicts least recently used item when over capacity",
            "get() marks item as recently used",
            "put() on existing key marks it as recently used",
            "Operations are O(1) average time",
        ],
        "difficulty": "hard",
        "tags": ["python", "data-structures", "cache", "design"],
    },
    {
        "title": "Bash Log Analyzer",
        "instruction": (
            "Write a bash script that reads an nginx access log from stdin "
            "and outputs the top 10 IP addresses by request count, formatted "
            "as 'COUNT IP' per line, sorted descending. Assume standard "
            "combined log format where IP is the first field."
        ),
        "expected_behavior": (
            "A concise bash one-liner or short script using awk, sort, uniq, "
            "and head to extract and rank IPs."
        ),
        "evaluation_criteria": [
            "Reads from stdin (not a hardcoded file)",
            "Extracts the first field (IP address)",
            "Counts occurrences of each IP",
            "Sorts by count in descending order",
            "Limits output to top 10",
            "Output format is 'COUNT IP' per line",
        ],
        "difficulty": "medium",
        "tags": ["bash", "linux", "log-analysis"],
    },
    {
        "title": "SQL Query Optimization",
        "instruction": (
            "Given a PostgreSQL table 'orders' with columns (id, user_id, "
            "amount, created_at, status), write an optimized query that finds "
            "the total amount and order count per user for the last 30 days, "
            "but only for users who have placed more than 5 orders in that "
            "period. Include appropriate index suggestions as SQL comments."
        ),
        "expected_behavior": (
            "A query using GROUP BY with HAVING clause, date filtering with "
            "appropriate functions, and index recommendations."
        ),
        "evaluation_criteria": [
            "Filters orders from the last 30 days",
            "Groups by user_id",
            "Calculates SUM(amount) and COUNT(*)",
            "Uses HAVING to filter users with > 5 orders",
            "Suggests at least one relevant index",
            "Query is syntactically valid PostgreSQL",
        ],
        "difficulty": "medium",
        "tags": ["sql", "postgresql", "optimization"],
    },
    {
        "title": "Concurrent Web Scraper",
        "instruction": (
            "Write a Python async function scrape_urls(urls: list[str]) -> "
            "list[dict] that concurrently fetches a list of URLs using aiohttp "
            "and returns a list of dicts with keys 'url', 'status', 'length' "
            "(content length), and 'error' (None on success, error message on "
            "failure). Limit concurrency to 10 simultaneous requests. Handle "
            "timeouts (5 second limit per request) and connection errors."
        ),
        "expected_behavior": (
            "An async function using aiohttp with a semaphore for concurrency "
            "limiting, proper error handling, and timeout configuration."
        ),
        "evaluation_criteria": [
            "Function is async and named scrape_urls",
            "Uses aiohttp for HTTP requests",
            "Limits concurrency to 10 with a semaphore",
            "Sets 5-second timeout per request",
            "Returns list of dicts with url, status, length, error",
            "Handles connection errors gracefully",
            "Handles timeout errors gracefully",
        ],
        "difficulty": "hard",
        "tags": ["python", "async", "networking", "concurrency"],
    },
]

_SEED_PATTERNS: list[dict[str, Any]] = [
    {
        "name": "code_correctness",
        "description": "Evaluates whether generated code is syntactically and logically correct",
        "criteria_template": [
            "Code is syntactically valid {language}",
            "No undefined variables or functions",
            "Handles edge cases (empty input, None, zero)",
            "Follows {language} naming conventions",
        ],
        "tags": ["code", "correctness"],
    },
    {
        "name": "code_efficiency",
        "description": "Evaluates algorithmic efficiency and resource usage",
        "criteria_template": [
            "Time complexity meets the requirement: {complexity}",
            "No unnecessary data copies or allocations",
            "Uses appropriate data structures",
        ],
        "tags": ["code", "performance"],
    },
    {
        "name": "explanation_quality",
        "description": "Evaluates the quality of explanations and documentation",
        "criteria_template": [
            "Explanation is clear and concise",
            "Uses correct technical terminology",
            "Provides examples where helpful",
            "Covers edge cases and limitations",
        ],
        "tags": ["explanation", "documentation"],
    },
    {
        "name": "bash_scripting",
        "description": "Evaluates bash/shell script quality",
        "criteria_template": [
            "Script is POSIX-compatible or uses correct shebang",
            "Handles errors (set -e or explicit checks)",
            "Quotes variables to prevent word splitting",
            "Uses appropriate tools (awk, sed, grep) idiomatically",
        ],
        "tags": ["bash", "scripting"],
    },
]

_SEED_PROMPTS: list[dict[str, Any]] = [
    {
        "name": "strict_evaluator",
        "description": "System prompt for strict code evaluation",
        "content": (
            "You are a strict code reviewer. Evaluate the given code against "
            "the criteria. Be precise about errors. Score 1.0 only if every "
            "criterion is fully met. Return JSON with verdict, score, errors, "
            "and feedback fields."
        ),
        "tags": ["evaluation", "code"],
    },
    {
        "name": "gentle_corrector",
        "description": "Correction prompt that explains errors constructively",
        "content": (
            "Your previous attempt had some issues. I'll explain each one so "
            "you can learn from them and produce a better response. Focus on "
            "understanding WHY each issue matters, not just fixing it."
        ),
        "tags": ["correction", "teaching"],
    },
    {
        "name": "step_by_step",
        "description": "Prompt that encourages step-by-step reasoning",
        "content": (
            "Think through this problem step by step before writing any code. "
            "First, identify the inputs and outputs. Then, consider edge cases. "
            "Finally, choose an algorithm and implement it. Show your reasoning."
        ),
        "tags": ["reasoning", "methodology"],
    },
]


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------


@dataclass
class ManifestEntry:
    """One item in the knowledge base manifest."""

    id: str
    kind: str  # "task", "pattern", "prompt"
    name: str
    tags: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "name": self.name,
            "tags": self.tags,
            "created_at": self.created_at,
        }


@dataclass
class Manifest:
    """Catalog of all knowledge base items."""

    entries: list[ManifestEntry] = field(default_factory=list)
    version: str = "1.0"
    exported_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "exported_at": self.exported_at,
            "entries": [e.to_dict() for e in self.entries],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Manifest:
        entries = [
            ManifestEntry(
                id=e["id"],
                kind=e["kind"],
                name=e["name"],
                tags=e.get("tags", []),
                created_at=e.get("created_at", 0.0),
            )
            for e in data.get("entries", [])
        ]
        return cls(
            entries=entries,
            version=data.get("version", "1.0"),
            exported_at=data.get("exported_at", 0.0),
        )


# ---------------------------------------------------------------------------
# Knowledge base manager
# ---------------------------------------------------------------------------


class KnowledgeBase:
    """Manages the offline knowledge base on disk."""

    def __init__(self, base_dir: str | Path) -> None:
        self._base = Path(base_dir)
        self._tasks_dir = self._base / "tasks"
        self._patterns_dir = self._base / "patterns"
        self._prompts_dir = self._base / "prompts"
        self._manifest_path = self._base / "manifest.json"

        # Ensure directories exist
        for d in (self._tasks_dir, self._patterns_dir, self._prompts_dir):
            d.mkdir(parents=True, exist_ok=True)

    # --- Seed ---

    def seed_if_empty(self) -> int:
        """Populate with built-in data if the knowledge base is empty.

        Returns the number of items seeded.
        """
        manifest = self._load_manifest()
        if manifest.entries:
            return 0

        count = 0

        for task_data in _SEED_TASKS:
            item_id = uuid.uuid4().hex[:12]
            task_data["id"] = item_id
            self._write_json(self._tasks_dir / f"{item_id}.json", task_data)
            manifest.entries.append(
                ManifestEntry(
                    id=item_id,
                    kind="task",
                    name=task_data.get("title", ""),
                    tags=task_data.get("tags", []),
                )
            )
            count += 1

        for pattern_data in _SEED_PATTERNS:
            item_id = uuid.uuid4().hex[:12]
            pattern_data["id"] = item_id
            self._write_json(self._patterns_dir / f"{item_id}.json", pattern_data)
            manifest.entries.append(
                ManifestEntry(
                    id=item_id,
                    kind="pattern",
                    name=pattern_data.get("name", ""),
                    tags=pattern_data.get("tags", []),
                )
            )
            count += 1

        for prompt_data in _SEED_PROMPTS:
            item_id = uuid.uuid4().hex[:12]
            prompt_data["id"] = item_id
            self._write_json(self._prompts_dir / f"{item_id}.json", prompt_data)
            manifest.entries.append(
                ManifestEntry(
                    id=item_id,
                    kind="prompt",
                    name=prompt_data.get("name", ""),
                    tags=prompt_data.get("tags", []),
                )
            )
            count += 1

        self._save_manifest(manifest)
        return count

    # --- CRUD ---

    def list_items(
        self, kind: str | None = None, tag: str | None = None
    ) -> list[dict[str, Any]]:
        """List knowledge base items, optionally filtered by kind or tag."""
        manifest = self._load_manifest()
        results: list[dict[str, Any]] = []
        for entry in manifest.entries:
            if kind and entry.kind != kind:
                continue
            if tag and tag not in entry.tags:
                continue
            results.append(entry.to_dict())
        return results

    def get_item(self, item_id: str) -> dict[str, Any] | None:
        """Load a single item by ID."""
        manifest = self._load_manifest()
        for entry in manifest.entries:
            dir_map = {
                "task": self._tasks_dir,
                "pattern": self._patterns_dir,
                "prompt": self._prompts_dir,
            }
            target_dir = dir_map.get(entry.kind)
            if target_dir is None:
                continue
            if entry.id == item_id:
                path = target_dir / f"{item_id}.json"
                if path.exists():
                    return self._read_json(path)
        return None

    def get_task(self, item_id: str) -> Task | None:
        """Load a task by ID and return as a Task object."""
        data = self.get_item(item_id)
        if data is None:
            return None
        return Task.from_dict(data)

    def add_task(self, task: Task) -> str:
        """Add a new task to the knowledge base. Returns the task ID."""
        manifest = self._load_manifest()
        self._write_json(self._tasks_dir / f"{task.id}.json", task.to_dict())
        manifest.entries.append(
            ManifestEntry(
                id=task.id,
                kind="task",
                name=task.title,
                tags=task.tags,
            )
        )
        self._save_manifest(manifest)
        return task.id

    def delete_item(self, item_id: str) -> bool:
        """Remove an item from the knowledge base."""
        manifest = self._load_manifest()
        found = False
        new_entries: list[ManifestEntry] = []
        for entry in manifest.entries:
            if entry.id == item_id:
                found = True
                dir_map = {
                    "task": self._tasks_dir,
                    "pattern": self._patterns_dir,
                    "prompt": self._prompts_dir,
                }
                target_dir = dir_map.get(entry.kind)
                if target_dir:
                    path = target_dir / f"{item_id}.json"
                    if path.exists():
                        path.unlink()
            else:
                new_entries.append(entry)
        if found:
            manifest.entries = new_entries
            self._save_manifest(manifest)
        return found

    # --- Export / Import ---

    def export_archive(self, output_path: str | Path) -> str:
        """Export the entire knowledge base as a zip archive.

        Returns the path to the created archive.
        """
        output = Path(output_path)
        # shutil.make_archive wants the base name without extension
        base_name = str(output.with_suffix(""))
        archive_path = shutil.make_archive(base_name, "zip", str(self._base))
        return archive_path

    def import_archive(self, archive_path: str | Path) -> int:
        """Import a knowledge base archive, merging with existing data.

        Returns the number of new items imported.
        """
        import tempfile

        archive = Path(archive_path)
        if not archive.exists():
            raise FileNotFoundError(f"Archive not found: {archive}")

        with tempfile.TemporaryDirectory() as tmp:
            shutil.unpack_archive(str(archive), tmp)
            tmp_path = Path(tmp)

            # Load the imported manifest
            imported_manifest_path = tmp_path / "manifest.json"
            if not imported_manifest_path.exists():
                raise ValueError("Archive does not contain a manifest.json")

            imported_manifest = Manifest.from_dict(
                self._read_json(imported_manifest_path)
            )
            current_manifest = self._load_manifest()
            existing_ids = {e.id for e in current_manifest.entries}

            count = 0
            for entry in imported_manifest.entries:
                if entry.id in existing_ids:
                    continue  # skip duplicates

                dir_map = {
                    "task": ("tasks", self._tasks_dir),
                    "pattern": ("patterns", self._patterns_dir),
                    "prompt": ("prompts", self._prompts_dir),
                }
                mapping = dir_map.get(entry.kind)
                if mapping is None:
                    continue
                src_subdir, dst_dir = mapping
                src_file = tmp_path / src_subdir / f"{entry.id}.json"
                if src_file.exists():
                    shutil.copy2(str(src_file), str(dst_dir / f"{entry.id}.json"))
                    current_manifest.entries.append(entry)
                    count += 1

            self._save_manifest(current_manifest)
            return count

    # --- Stats ---

    def stats(self) -> dict[str, Any]:
        """Return summary statistics about the knowledge base."""
        manifest = self._load_manifest()
        by_kind: dict[str, int] = {}
        all_tags: set[str] = set()
        for entry in manifest.entries:
            by_kind[entry.kind] = by_kind.get(entry.kind, 0) + 1
            all_tags.update(entry.tags)
        return {
            "total_items": len(manifest.entries),
            "by_kind": by_kind,
            "unique_tags": sorted(all_tags),
            "version": manifest.version,
        }

    # --- Internal helpers ---

    def _load_manifest(self) -> Manifest:
        if self._manifest_path.exists():
            return Manifest.from_dict(self._read_json(self._manifest_path))
        return Manifest()

    def _save_manifest(self, manifest: Manifest) -> None:
        manifest.exported_at = time.time()
        self._write_json(self._manifest_path, manifest.to_dict())

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        with open(path, encoding="utf-8") as f:
            result: dict[str, Any] = json.load(f)
            return result

    @staticmethod
    def _write_json(path: Path, data: dict[str, Any]) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
