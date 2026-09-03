# es — how to run the re-emission

> Written 2026-09-04, after the code landed on `feat/es-reemission`. Everything
> below has been rehearsed on a 20-law scratch repo; nothing has been pushed.

The code is done. What is left is one long, irreversible run and two switches
that must not be flipped before it.

## 0. The two switches

They are deliberately off. Each is a **claim about a repo that already
exists**, so flipping one before the rebuild breaks the corpus it describes.

```diff
--- a/src/legalize/countries.py
-ESCAPES_LEGAL_NUMBERING: set[str] = set()
+ESCAPES_LEGAL_NUMBERING: set[str] = {"es"}

--- a/src/legalize/layout.py
     "eu": SHARDED,
+    "es": SHARDED,
 }
```

- **`ESCAPES_LEGAL_NUMBERING`** — with it on, a daily run would start writing
  escaped numbering into a corpus that has not been re-emitted, and the next
  reform of any law would carry a whole-file reformat inside its diff. That is
  what `diff_law` shows a reader.
- **`LAYOUT["es"]`** — `.legalize.yml` is generated from it. Published before
  the rebuild, the manifest promises consumers a path shape the repo is not in
  and every body 404s.

Flip both in the same commit as the rebuild, never earlier.

## 1. Rebuild

```sh
cd engine
legalize bootstrap -c es --fresh          # ~12,400 norms, full history
```

`--fresh` re-inits `countries/es` and deletes `data-es/json/`. The local repo
is clean at `origin/main` (`cc3d02128`, 0 unpushed) — verify that first, and
note that the `countries/data-*` caches were deleted on 2026-08-28, so this
re-fetches everything: ~12,400 metadata + ~12,400 text requests at the
configured rate.

Discovery is two requests (`?limit=10000&offset=`); it used to be an
ImportError.

## 2. Verify before pushing

On the rebuilt `countries/es`:

```sh
git -C ../countries/es log --oneline | wc -l          # ~44,000
find ../countries/es/es -name '*.md' | head -3        # es/61/BOE-A-....md
cat ../countries/es/.legalize.yml                     # path must say {id_sha1_2}
grep -c 'article_count' ../countries/es/es/*/*.md | head
```

and the four the rehearsal checked: sharded paths, a `.legalize.yml` declaring
that shape, escaped numbering with no unescaped survivors, and **zero per-file
commit chains out of `Source-Date` order**.

## 3. Push

`legalize-es` is 1.6 GiB and GitHub rejects a pack over 2.00 GiB, so it goes in
slices — `scripts/push_slices.sh`, see `adding-a-country/step-9-production.md`
§9.4 and the `legalize_push_2gib` note.

## 4. Re-seed the database — mandatory

Every SHA changes, so an incremental sync cannot see it:

```sh
cd ../enrichment
law-sync full --repo ../countries/es
```

`pt` must not ride the same batch (see `full_sync_prod_load`).

## 5. What does *not* go in this pass

- **The non-consolidated corpus (#66).** Adding files later needs no rebuild —
  only changing the frontmatter or the path of files that already exist does.
  Tranche 1 is 2010→today, ~14,300 acts, 0 % structure failure in the dry run.
- **Moving the 51-entry BOE class map into `fetcher/es/`** (the other half of
  #128). It is a refactor with a byte-for-byte safety net and needs no
  reprocess.
- **#131**, the backfill regression. It is about what the backfill does *after*
  this, and its guard belongs in shared code.
