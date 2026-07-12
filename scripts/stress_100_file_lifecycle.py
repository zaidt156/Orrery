"""Run the real 100-file FileGen + project-context lifecycle stress test.

Needs Docker, ``orrery-sandbox:latest``, and Orrery's local Postgres/pgvector database.
No AI provider is called and all generated files/database rows are scratch data.

Run:  .venv/Scripts/python scripts/stress_100_file_lifecycle.py --allow-configured-database
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import pathlib
import sys
import tempfile
import time
import urllib.parse
import uuid

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from scripts import _stress_100_file_fixture as fixture

file_library = fixture.file_library
filegen = fixture.filegen
filepreview = fixture.filepreview
projects = fixture.projects
rag = fixture.rag
retrieval = fixture.retrieval
sandbox = fixture.sandbox


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def request_for(fmt: str) -> str:
    return f"Create five simple .{fmt} files"


def file_index(name: str) -> int:
    return int(pathlib.Path(name).stem.rsplit("-", 1)[1])


def marker(fmt: str, index: int) -> str:
    return f"{fmt.upper()}-{1000 + index}"


def as_attachment(file: sandbox.SandboxFile) -> dict:
    fmt = filegen._format_for_name(file.name)
    mime = fixture.MIME[fmt]
    if fmt in fixture.TEXT_FORMATS:
        return {"name": file.name, "mime": mime, "kind": "text", "content": file.data.decode("utf-8")}
    encoded = base64.b64encode(file.data).decode("ascii")
    kind = "pdf" if fmt == "pdf" else "image" if fmt in fixture.IMAGE_FORMATS else "file"
    return {"name": file.name, "mime": mime, "kind": kind, "content": f"data:{mime};base64,{encoded}"}


def generate_corpus() -> tuple[list[sandbox.SandboxFile], list[dict]]:
    generated: list[sandbox.SandboxFile] = []
    manifests: list[dict] = []
    for position, fmt in enumerate(fixture.FORMATS):
        request = request_for(fmt)
        require(filegen.wants_file(request), f"routing did not recognize {request!r}")
        require(fixture.taskrouter.plan(request).route == "file", f"task router missed {fmt}")
        code = f"FMT = {fmt!r}\nSTART = {position * fixture.FILES_PER_FORMAT}\nCOUNT = {fixture.FILES_PER_FORMAT}\n" + fixture._GENERATOR
        result = sandbox.run_code(code)
        require(result.ok, f"sandbox failed for {fmt}: {result.stderr or result.stdout}")
        require(len(result.files) == fixture.FILES_PER_FORMAT, f"{fmt}: expected 5 outputs, got {len(result.files)}")
        require(result.manifest.get("limits", {}).get("max_output_files") == 12, "sandbox file limit changed")
        approval = filegen._approve_files(result.files, request)
        require(approval.ok, f"FileGen validation failed for {fmt}: {approval.reason}")
        require(len(approval.files) == fixture.FILES_PER_FORMAT, f"FileGen dropped {fmt} outputs")
        generated.extend(approval.files)
        manifests.extend(approval.manifest)
        print(f"[filegen] {fmt:>4}: sandboxed + validated {len(approval.files)} files")
    require(len(generated) == 100, f"expected exactly 100 files, got {len(generated)}")
    require(len({file.name for file in generated}) == 100, "generated names are not unique")
    require(all(item.get("ok") for item in manifests), "a validation manifest reported failure")
    return generated, manifests


def exercise_library(generated: list[sandbox.SandboxFile]) -> list[dict]:
    records = []
    for file in generated:
        fmt = filegen._format_for_name(file.name)
        record = file_library.store(file.name, fixture.MIME[fmt], file.data)
        loaded = file_library.load(record["id"])
        require(loaded is not None, f"stored file vanished: {file.name}")
        meta, data = loaded
        require(data == file.data and meta == record, f"stored file changed: {file.name}")
        preview, preview_mime = filepreview.to_preview(meta["name"], meta["mime"], data)
        require(bool(preview) and bool(preview_mime), f"preview failed: {file.name}")
        records.append(record)
    require(file_library.load("../escape") is None, "file id path traversal was accepted")
    try:
        file_library.store("too-large.bin", "application/octet-stream", b"x" * (file_library.MAX_FILE_BYTES + 1))
    except ValueError:
        pass
    else:
        raise AssertionError("generated-file size cap was not enforced")
    return records


async def main(*, allow_configured_database: bool = False) -> int:
    if not allow_configured_database:
        print("FAIL: pass --allow-configured-database to permit temporary rows in Orrery's configured local database")
        return 2
    url = fixture.database.resolve_database_url()
    if not url or not await fixture.database.check_connection(force=True):
        print("FAIL: the local Orrery database is not available")
        return 1
    host = urllib.parse.urlsplit(fixture.database.normalize_url(url)).hostname
    if host not in {"localhost", "127.0.0.1", "::1"}:
        print("FAIL: this stress harness refuses to mutate a non-local database")
        return 2
    if not sandbox.image_ready(refresh=True):
        print("FAIL: Docker is unavailable or orrery-sandbox:latest is missing")
        return 1

    project_id: str | None = None
    collection_id: str | None = None
    original_library_dir = file_library._DIR
    started = time.perf_counter()
    status = 0

    with tempfile.TemporaryDirectory(prefix=fixture.PREFIX) as tmp:
        scratch_dir = pathlib.Path(tmp) / "generated"
        file_library._DIR = scratch_dir
        try:
            t0 = time.perf_counter()
            generated, manifests = generate_corpus()
            generation_seconds = time.perf_counter() - t0

            t0 = time.perf_counter()
            records = exercise_library(generated)
            library_seconds = time.perf_counter() - t0
            require(len(records) == 100 and len(manifests) == 100, "file lifecycle count mismatch")
            print(f"[library] stored, reloaded, and previewed {len(records)} files")

            attachments = [as_attachment(file) for file in generated]
            payload_bytes = len(json.dumps({"files": attachments}, separators=(",", ":")).encode("utf-8"))
            max_upload_bytes = fixture.database.settings.max_upload_bytes
            require(payload_bytes < max_upload_bytes, "100-file serialized payload exceeds the configured request cap")

            run_name = f"{fixture.PREFIX}{uuid.uuid4().hex}"
            project = await projects.create_project(
                run_name,
                "Disposable mixed-format lifecycle verification.",
                "Use project facts only when they are relevant to the current question.",
            )
            project_id = project["id"]
            collection_id = await projects.ensure_collection(project_id)
            require(collection_id is not None, "project collection was not created")
            t0 = time.perf_counter()
            added = await projects.add_files(project_id, attachments)
            indexing_seconds = time.perf_counter() - t0

            readable_formats = fixture.TEXT_FORMATS | {"pdf", "docx", "xlsx", "pptx"}
            expected_sources = {
                file.name for file in generated if filegen._format_for_name(file.name) in readable_formats
            }
            documents = await projects.list_files(project_id)
            actual_sources = {item["source"] for item in documents}
            require(actual_sources == expected_sources, f"context indexed {len(actual_sources)}/50 expected sources")
            require(added["added"] >= len(expected_sources), "not every readable source produced a chunk")

            trusted = await projects.trusted_context(project_id)
            require(trusted and run_name in trusted and "relevant" in trusted, "trusted project context is incomplete")

            t0 = time.perf_counter()
            for file in generated:
                fmt = filegen._format_for_name(file.name)
                if fmt not in readable_formats:
                    continue
                index = file_index(file.name)
                expected_marker = marker(fmt, index)
                results = await rag.search(collection_id, f"{fmt} stress marker unit {index} {expected_marker}", k=5)
                require(any(expected_marker in row["content"] and row["source"] == file.name for row in results),
                        f"retrieval missed {file.name}")
            search_seconds = time.perf_counter() - t0

            for fmt in sorted(readable_formats):
                file = next(item for item in generated if filegen._format_for_name(item.name) == fmt)
                index = file_index(file.name); expected_marker = marker(fmt, index)
                block, sources = await retrieval._gather_rag(
                    "openai/gpt-test", [collection_id], f"Find {expected_marker} for unit {index}"
                )
                require(block and expected_marker in block and file.name in sources, f"chat context missed {fmt}")

            block, sources = await retrieval._gather_rag(
                "openai/gpt-test", [collection_id], "best pasta recipe for dinner tonight", strict=True
            )
            require(not block and not sources, f"unrelated query leaked project context: {sources[:5]}")

            victim = next(iter(expected_sources)); before = len(documents)
            require(await projects.delete_file(project_id, victim), "project file delete failed")
            require(len(await projects.list_files(project_id)) == before - 1, "deleted source still appears")

            print(f"[context] indexed {len(expected_sources)} readable files; skipped 50 media/archive files as designed")
            print(f"[payload] {payload_bytes / 1024 / 1024:.2f} MiB serialized; "
                  f"configured cap {max_upload_bytes / 1024 / 1024:.0f} MiB (no HTTP request in this harness)")
            print(f"[time] sandbox {generation_seconds:.1f}s | library {library_seconds:.1f}s | "
                  f"index {indexing_seconds:.1f}s | 50 searches {search_seconds:.1f}s")
        except Exception as exc:  # cleanup still runs for every assertion/runtime failure
            status = 1
            print(f"FAIL: {exc}")
        finally:
            cleanup_errors: list[str] = []
            if project_id and not collection_id:
                try:
                    collection_id = await projects.collection_id_for(project_id)
                except Exception as exc:  # best effort; report after every cleanup path runs
                    cleanup_errors.append(f"resolve collection: {exc}")
            if project_id:
                try:
                    if not await projects.delete_project(project_id):
                        cleanup_errors.append("delete scratch project: not found")
                except Exception as exc:
                    cleanup_errors.append(f"delete scratch project: {exc}")
            if collection_id:
                try:
                    if not await rag.delete_collection(collection_id):
                        cleanup_errors.append("delete scratch collection: not found")
                except Exception as exc:
                    cleanup_errors.append(f"delete scratch collection: {exc}")
            try:
                if scratch_dir.exists():
                    old = time.time() - 7200
                    for path in scratch_dir.iterdir():
                        if path.is_file():
                            os.utime(path, (old, old))
                    removed = file_library.cleanup(ttl_hours=1)
                    if any(scratch_dir.iterdir()):
                        cleanup_errors.append("local generated-file cleanup left residue")
                    print(f"[cleanup] removed {removed} blob/metadata entries; current-run database rows removed")
            except Exception as exc:
                cleanup_errors.append(f"clean local files: {exc}")
            finally:
                file_library._DIR = original_library_dir
            if cleanup_errors:
                status = 1
                print("CLEANUP FAILURES: " + " | ".join(cleanup_errors))

    if status == 0:
        print(f"ALL 100-FILE LIFECYCLE CHECKS PASSED in {time.perf_counter() - started:.1f}s")
    return status


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--allow-configured-database", action="store_true",
        help="allow temporary UUID-scoped rows in Orrery's configured local database",
    )
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(allow_configured_database=args.allow_configured_database)))
