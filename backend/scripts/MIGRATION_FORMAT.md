# Legacy metadata migration format

`migrate_metadata.py` accepts one UTF-8 JSON object with `format_version: 1`
and a `tables` object containing all eight arrays shown in
`migration_export.example.json`. The command only reads this file.

Run a validation-only dry-run first:

```bash
cd backend
python scripts/migrate_metadata.py export.json \
  --map 'oss://legacy-bucket/archive=tos://target-bucket/media'
```

Commit only after the report has `"valid": true`:

```bash
python scripts/migrate_metadata.py export.json \
  --map 'oss://legacy-bucket/archive=tos://target-bucket/media' \
  --apply
```

Mappings are repeatable and use the longest matching source prefix. Every
`media_files.oss_url` and `import_tasks.oss_directory` must match exactly one
mapping. Object bytes must be copied to TOS separately before vector rebuild.

The importer preserves supplied primary keys, password hashes, roles, manual
tags, login history, search history, sessions, and import-task history. It
validates source and target primary/unique keys plus user/media relations.
Identical target rows are skipped, making an applied import repeatable.

Old vectors are never imported. Every imported media row is marked `pending`
with empty vector identity. Old OSS and model-provider credentials, old model
selection fields, and embedded vector payloads are accepted only as ignored
legacy fields. They are not printed in reports or copied to MySQL.

After object migration and metadata import:

```bash
python scripts/rebuild_vectors.py --limit 100
python scripts/rebuild_vectors.py --after-id LAST_MEDIA_UUID --limit 100
python scripts/rebuild_vectors.py --failed-only --limit 100
```

The rebuild tool validates all collection identity fields before work. A row
is complete only when status, stable vector ID, model, dimension, corpus
instruction version, and collection all match. For each row it obtains a TOS
signed URL, calls Ark, upserts Milvus, then records completion in MySQL. Failed
rows are recorded without credentials or signed URLs and can be retried. The
final report compares the exact Milvus count with current-version MySQL rows;
the CLI exits nonzero on processing failures or a count mismatch.
