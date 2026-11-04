# Glossary

The terms of the curation, one meaning each. The Drakkar database's terms (publication, run, state, curation pass, description, mapping…) are defined in its `glossary.md`, and used here with that meaning.

| Term | Meaning |
| -- | -- |
| Batch | Up to 20 publications of a run whose download is complete, formed from its pool by the `fetch` skill, and curated together by the `batch` skill: one curator agent each, merged into one set of files that passes the dry run, and committed together when the user asks. Never "run". |
| Pool | The publications of a run being downloaded: each stays there until its download is complete, the article and every supplementary file it lists, then goes into a batch. A publication whose download cannot be completed stays in the pool and is never curated. |
