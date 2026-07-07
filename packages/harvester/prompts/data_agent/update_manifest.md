# Data Protocol - Update Manifest

## Role

Create or update data manifests using `docs/schemas/data_manifest.schema.json`.

## Required Fields

- manifest ID
- dataset ID
- provider
- local path
- frequency policy
- no-lookahead policy
- allowed uses

## Forbidden

- marking unchecked data as paper allowed
- omitting release lag when timing matters
