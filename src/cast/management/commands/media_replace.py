from uuid import uuid4

from django.core.files.storage import FileSystemStorage
from django.core.management.base import BaseCommand, CommandError

from .storage_backend import get_production_and_backup_storage


def temporary_replacement_path(path: str) -> str:
    return f"{path}.django-cast-replace-{uuid4().hex}.tmp"


class Command(BaseCommand):
    help = (
        "replace paths on production storage backend with local versions - useful for compressed videos for example "
        "(requires production and backup storage backends configured)"
    )

    def add_arguments(self, parser):
        parser.add_argument("paths", nargs="+", type=str)
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Preview replacements without writing to production storage.",
        )
        parser.add_argument(
            "--yes",
            action="store_true",
            default=False,
            help="Confirm destructive writes to production storage.",
        )

    def handle(self, *args, **options):
        production, _ = get_production_and_backup_storage()
        fs_storage = FileSystemStorage()
        dry_run = options["dry_run"]
        confirmed = options["yes"]
        planned = 0
        replaced = 0
        skipped = 0
        errors = 0

        if dry_run and confirmed:
            self.stderr.write("warning: --yes is ignored in dry-run mode")

        for path in options["paths"]:
            if fs_storage.exists(path):
                planned += 1
                if dry_run:
                    self.stdout.write(f"DRY RUN would replace: {path}")
                    continue
                if not confirmed:
                    self.stdout.write(f"planned replace: {path}")
                    continue
                staged_name = ""
                saved_name = ""
                try:
                    with fs_storage.open(path, "rb") as in_f:
                        staged_name = production.save(temporary_replacement_path(path), in_f)
                    if not production.exists(staged_name):
                        raise RuntimeError(f"staged replacement {staged_name} was not saved")
                    target_exists = production.exists(path)
                    with production.open(staged_name, "rb") as staged_f:
                        saved_name = production.save(path, staged_f)
                    if target_exists and saved_name != path:
                        if production.exists(saved_name):
                            try:
                                production.delete(saved_name)
                            except Exception as exc:
                                self.stderr.write(
                                    f"warning: could not remove generated replacement {saved_name}: {exc}"
                                )
                        raise RuntimeError(
                            f"storage saved replacement as {saved_name}; original {path} was not replaced"
                        )
                    if saved_name != path:
                        self.stderr.write(f"warning: {path} saved as {saved_name}")
                    replaced += 1
                    self.stdout.write(f"replaced: {path}")
                except Exception as exc:
                    errors += 1
                    self.stderr.write(f"error replacing {path}: {exc}")
                finally:
                    if staged_name:
                        try:
                            if production.exists(staged_name):
                                production.delete(staged_name)
                        except Exception as exc:
                            self.stderr.write(f"warning: could not remove staged replacement {staged_name}: {exc}")
            else:
                skipped += 1
                self.stdout.write(f"skipped (not found locally): {path}")

        if not dry_run and not confirmed and planned > 0:
            self.stdout.write("No files were changed. Re-run with --yes or use --dry-run to preview.")
            self.stdout.write(f"planned={planned} replaced={replaced} skipped={skipped} errors={errors}")
            raise CommandError("Use --yes to confirm destructive replacements.")

        self.stdout.write(f"planned={planned} replaced={replaced} skipped={skipped} errors={errors}")
